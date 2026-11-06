namespace AntPad.Services;

/// <summary>一个可折叠区间（0 计行号）：StartLine 含开括号，EndLine 含闭括号/块尾。</summary>
public sealed class FoldRange
{
    public int StartLine;
    public int EndLine;
}

/// <summary>
/// 代码折叠的纯逻辑引擎（不依赖 UI，可独立单测）：
/// - C 系/JSON：按花括号/圆括号/方括号配对找区间，字符串与注释内的括号不参与；
/// - Python：按缩进层级找区间（块体缩进更深，空行不打断）；
/// - 折叠 = 从显示文本里摘掉区间内部行，保留锚点行；展开 = 按锚点行原文插回，往返无损。
/// </summary>
public static class FoldEngine
{
    /// <summary>该语言是否支持折叠（其余语言返回空表，UI 不显示折叠标记）。</summary>
    public static bool Supports(string langId) => Syntax.LangDef.IsCLike(langId) || langId is "json" or "python";

    /// <summary>计算整篇文本的全部折叠区间（按起始行升序）。</summary>
    public static List<FoldRange> Compute(string text, string langId)
    {
        var result = new List<FoldRange>();
        if (text.Length == 0 || !Supports(langId)) return result;
        var lines = text.Split('\n');
        if (langId == "python") ComputeIndent(lines, result);
        else ComputeBraces(lines, Syntax.LangDef.IsCLike(langId), result);

        result.RemoveAll(r => r.EndLine <= r.StartLine);
        result.Sort((a, b) => a.StartLine != b.StartLine
            ? a.StartLine.CompareTo(b.StartLine)
            : b.EndLine.CompareTo(a.EndLine));   // 同起点先外层后内层
        return result;
    }

    /// <summary>括号配对找区间：line/comment 里的括号不参与（C 系含行/块注释与字符串；JSON 只有字符串）。</summary>
    static void ComputeBraces(string[] lines, bool isClike, List<FoldRange> result)
    {
        var stack = new Stack<(int line, char open)>();
        bool inBlockComment = false;
        for (int i = 0; i < lines.Length; i++)
        {
            var line = lines[i];
            bool inStr = false;
            for (int j = 0; j < line.Length; j++)
            {
                char c = line[j];
                if (inBlockComment)
                {
                    if (c == '*' && j + 1 < line.Length && line[j + 1] == '/') { inBlockComment = false; j++; }
                    continue;
                }
                if (inStr)
                {
                    if (c == '\\' && isClike) j++;      // 转义跳过（JSON 也按 C 风格转义）
                    else if (c == '"') inStr = false;
                    continue;
                }
                if (isClike)
                {
                    if (c == '/' && j + 1 < line.Length && line[j + 1] == '/') break;   // 行注释：剩余忽略
                    if (c == '/' && j + 1 < line.Length && line[j + 1] == '*') { inBlockComment = true; j++; continue; }
                    if (c == '"') { inStr = true; continue; }
                    if (c == '\'')   // 字符字面量：跳到配对引号
                    {
                        int k = j + 1;
                        while (k < line.Length) { if (line[k] == '\\') k += 2; else if (line[k] == '\'') break; else k++; }
                        j = Math.Min(k, line.Length - 1);
                        continue;
                    }
                }
                else if (c == '"') { inStr = true; continue; }

                if (c == '{' || c == '(' || c == '[') stack.Push((i, c));
                else if (c == '}' || c == ')' || c == ']')
                {
                    char want = c == '}' ? '{' : c == ')' ? '(' : '[';
                    var skipped = new List<(int, char)>();
                    while (stack.Count > 0 && stack.Peek().open != want)
                    {
                        skipped.Add(stack.Pop());                       // 交错括号：暂时摘开再放回
                        if (skipped.Count > 64) break;
                    }
                    if (stack.Count > 0)
                    {
                        var top = stack.Pop();
                        if (top.line < i) result.Add(new FoldRange { StartLine = top.line, EndLine = i });
                    }
                    for (int k = skipped.Count - 1; k >= 0; k--) stack.Push(skipped[k]);
                }
            }
        }
    }

    /// <summary>缩进找区间（Python）：某行块体（后续缩进更深的行，空行跳过）超过一行即可折叠。</summary>
    static void ComputeIndent(string[] lines, List<FoldRange> result)
    {
        for (int i = 0; i < lines.Length; i++)
        {
            var head = lines[i];
            if (head.TrimEnd().Length == 0) continue;   // 空行/纯空白不作块头
            int ind = Indent(head);
            int last = i, j = i + 1;
            while (j < lines.Length)
            {
                if (lines[j].TrimEnd().Length == 0) { j++; continue; }
                if (Indent(lines[j]) > ind) { last = j; j++; }
                else break;
            }
            if (last > i) result.Add(new FoldRange { StartLine = i, EndLine = last });
        }
    }

    static int Indent(string s)
    {
        int n = 0;
        for (int i = 0; i < s.Length; i++)
        {
            if (s[i] == ' ') n++;
            else if (s[i] == '\t') n += 4;
            else break;
        }
        return n;
    }

    /// <summary>
    /// 折叠：摘掉 (start0+1 .. end0) 的内部行，返回折叠后文本 + 锚点行原文 + 被隐藏的行。
    /// 锚点行用于展开时定位插回位置。
    /// </summary>
    public static (string folded, string anchor, string[] hidden) Collapse(string text, int start0, int end0)
    {
        var lines = text.Split('\n');
        start0 = Math.Max(0, Math.Min(start0, lines.Length - 1));
        end0 = Math.Max(start0, Math.Min(end0, lines.Length - 1));
        string[] hidden = lines.Skip(start0 + 1).Take(end0 - start0).ToArray();
        var kept = lines.Take(start0 + 1).Concat(lines.Skip(end0 + 1));
        return (string.Join("\n", kept), lines[start0], hidden);
    }

    /// <summary>
    /// 展开：在折叠文本里按锚点行原文找到位置，把隐藏行原样插回去。
    /// 找不到锚点（锚点行被改/删）时 ok=false，原文不变——由调用方兜底，绝不丢内容。
    /// </summary>
    public static (bool ok, string text) Expand(string folded, string anchor, IReadOnlyList<string> hidden)
    {
        var lines = folded.Split('\n');
        int at = -1;
        for (int i = 0; i < lines.Length; i++)
            if (lines[i] == anchor) { at = i; break; }
        if (at < 0) return (false, folded);

        var res = new List<string>(lines.Length + hidden.Count);
        for (int i = 0; i < lines.Length; i++)
        {
            res.Add(lines[i]);
            if (i == at)
                for (int k = 0; k < hidden.Count; k++) res.Add(hidden[k]);
        }
        return (true, string.Join("\n", res));
    }
}
