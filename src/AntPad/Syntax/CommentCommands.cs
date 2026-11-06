using System.Text;

namespace AntPad.Syntax;

/// <summary>
/// VS 语义的注释/取消注释命令（纯文本变换，便于三层测试）：
/// - C 系/Python/SQL：按各自语言的行注释标记逐行加/去（标记对齐到行首第一个非空白字符，
///   与 Visual Studio"注释选区/取消注释选区"行为一致；空行不加注释）。
/// - XML/HTML：用 &lt;!-- --&gt; 包裹/解除（VS 对 XML 的注释方式）。
/// - JSON/Markdown/纯文本：无注释语法，原样返回。
/// </summary>
public static class CommentCommands
{
    /// <summary>对 [lineStart, lineEnd] 行区间（0 起，含端点）做注释/取消注释。
    /// 返回变换后的完整文本；无法操作时返回 null。</summary>
    public static string? Toggle(string text, int lineStart, int lineEnd, LangDef lang, bool comment)
    {
        if (text is null || lang is null) return null;
        if (lang.XmlMode) return comment ? WrapXml(text) : UnwrapXml(text);
        var marker = lang.LineComments.FirstOrDefault(m => !string.IsNullOrEmpty(m));
        if (marker is null) return null;

        var lines = SplitLines(text, out var eols);
        lineStart = Math.Max(0, lineStart);
        lineEnd = Math.Min(lines.Length - 1, lineEnd);
        for (int i = lineStart; i <= lineEnd; i++)
        {
            lines[i] = comment ? CommentLine(lines[i], marker) : UncommentLine(lines[i], marker);
        }
        return JoinLines(lines, eols);
    }

    /// <summary>XML 包裹注释：对整个选中区段包 &lt;!-- --&gt;（VS 的 XML 注释方式）。
    /// 文本已含注释标记（&lt;!-- 或 --&gt;）时拒绝包裹：XML 注释不允许嵌套，
    /// 强行包裹会让解除时找错边界（有损），宁可不做。</summary>
    public static string? WrapXml(string text)
    {
        if (text.Contains("<!--", StringComparison.Ordinal)) return null;
        if (text.Contains("-->", StringComparison.Ordinal)) return null;
        return "<!-- " + text + " -->";
    }

    /// <summary>XML 解除包裹：去掉首个 &lt;!-- 与其后首个 --&gt;，
    /// 以及包裹时各补的一个空格（保证 解包(包裹(x)) == x 严格无损）。</summary>
    public static string? UnwrapXml(string text)
    {
        int open = text.IndexOf("<!--", StringComparison.Ordinal);
        if (open < 0) return null;
        int close = text.IndexOf("-->", open + 4, StringComparison.Ordinal);
        if (close < 0) return null;
        var inner = text[(open + 4)..close];
        if (inner.Length > 0 && inner[0] == ' ') inner = inner[1..];   // 包裹时补的首空格
        if (inner.Length > 0 && inner[^1] == ' ') inner = inner[..^1]; // 包裹时补的尾空格
        return text[..open] + inner + text[(close + 3)..];
    }

    /// <summary>单行加注释：标记插到行首第一个非空白字符前；空白行原样。</summary>
    public static string CommentLine(string line, string marker)
    {
        int w = 0;
        while (w < line.Length && (line[w] == ' ' || line[w] == '\t')) w++;
        if (w >= line.Length) return line;           // 空行/纯空白：VS 不注释空行
        return line[..w] + marker + line[w..];
    }

    /// <summary>单行去注释：行首第一个非空白处若为标记则移除，并顺带移除其后的一个空格。</summary>
    public static string UncommentLine(string line, string marker)
    {
        int w = 0;
        while (w < line.Length && (line[w] == ' ' || line[w] == '\t')) w++;
        if (!line[w..].StartsWith(marker, StringComparison.Ordinal)) return line;
        int p = w + marker.Length;
        if (p < line.Length && line[p] == ' ') p++;  // 去 "// " 的空格
        return line[..w] + line[p..];
    }

    static string[] SplitLines(string text, out List<int> eolLens)
    {
        eolLens = new();
        var lines = new List<string>();
        int start = 0;
        for (int i = 0; i < text.Length; i++)
        {
            if (text[i] == '\n')
            {
                int end = (i > start && text[i - 1] == '\r') ? i - 1 : i;
                lines.Add(text[start..end]);
                eolLens.Add(i + 1 - end);
                start = i + 1;
            }
        }
        lines.Add(text[start..]);
        eolLens.Add(0);
        return lines.ToArray();
    }

    static string JoinLines(string[] lines, List<int> eolLens)
    {
        var sb = new StringBuilder();
        for (int i = 0; i < lines.Length; i++)
        {
            sb.Append(lines[i]);
            int eol = eolLens[i];
            if (eol == 2) sb.Append("\r\n");
            else if (eol == 1) sb.Append('\n');
        }
        return sb.ToString();
    }
}
