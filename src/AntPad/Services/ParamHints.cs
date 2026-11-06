namespace AntPad.Services;

/// <summary>参数提示结果：函数名、当前正在输入的参数序号（0 计）与签名文本。</summary>
public sealed class ParamHint
{
    public string FuncName = "";
    public int ArgIndex;
    public string Signature = "";     // 完整签名，如 print(value, ..., sep=' ', end='\n')
    public string Source = "";        // 签名来源：builtin / doc
}

/// <summary>
/// 参数提示的纯逻辑引擎（不依赖 UI，可独立单测）：
/// 从光标向前找最近一层未闭合的调括号，识别函数名与当前参数序号；
/// 签名优先查内置常用函数表，再查当前文档里定义的函数。
/// </summary>
public static class ParamHints
{
    // ---------- 内置签名表（覆盖常用内置/标准函数，按语言分组） ----------

    static readonly Dictionary<string, string> BuiltinPy = new()
    {
        ["print"] = "print(*values, sep=' ', end='\\n', file=None, flush=False)",
        ["range"] = "range(start, stop, step)",
        ["len"] = "len(obj)",
        ["open"] = "open(file, mode='r', buffering=-1, encoding=None)",
        ["sorted"] = "sorted(iterable, *, key=None, reverse=False)",
        ["int"] = "int(x=0, base=10)",
        ["str"] = "str(object='')",
        ["float"] = "float(x=0.0)",
        ["bool"] = "bool(x=False)",
        ["list"] = "list(iterable=())",
        ["dict"] = "dict(**kwargs)",
        ["set"] = "set(iterable=())",
        ["sum"] = "sum(iterable, start=0)",
        ["min"] = "min(*args, key=None)",
        ["max"] = "max(*args, key=None)",
        ["abs"] = "abs(x)",
        ["round"] = "round(number, ndigits=None)",
        ["enumerate"] = "enumerate(iterable, start=0)",
        ["zip"] = "zip(*iterables, strict=False)",
        ["map"] = "map(function, *iterables)",
        ["filter"] = "filter(function, iterable)",
        ["isinstance"] = "isinstance(obj, class_or_tuple)",
        ["input"] = "input(prompt='')",
        ["format"] = "format(value, format_spec='')",
    };

    static readonly Dictionary<string, string> BuiltinCs = new()
    {
        ["Math.Abs"] = "Math.Abs(value)",
        ["Math.Max"] = "Math.Max(a, b)",
        ["Math.Min"] = "Math.Min(a, b)",
        ["Math.Round"] = "Math.Round(value, digits)",
        ["Math.Pow"] = "Math.Pow(x, y)",
        ["Math.Sqrt"] = "Math.Sqrt(value)",
        ["Console.WriteLine"] = "Console.WriteLine(value)",
        ["Console.Write"] = "Console.Write(value)",
        ["Console.ReadLine"] = "Console.ReadLine()",
        ["String.Format"] = "String.Format(format, args)",
        ["String.Join"] = "String.Join(separator, values)",
        ["int.Parse"] = "int.Parse(s)",
        ["int.TryParse"] = "int.TryParse(s, out result)",
        ["double.Parse"] = "double.Parse(s)",
        ["ToString"] = "value.ToString(format)",
        ["Split"] = "text.Split(separator)",
        ["Substring"] = "text.Substring(startIndex, length)",
        ["Replace"] = "text.Replace(oldValue, newValue)",
        ["Contains"] = "text.Contains(value)",
        ["IndexOf"] = "text.IndexOf(value)",
    };

    /// <summary>查内置签名表；查不到返回 null。</summary>
    public static string? Builtin(string langId, string name)
    {
        if (langId == "python") return BuiltinPy.TryGetValue(name, out var s) ? s : null;
        if (Syntax.LangDef.IsCLike(langId)) return BuiltinCs.TryGetValue(name, out var s) ? s : null;
        return null;
    }

    /// <summary>在当前文档里找函数定义签名（Python: def；C 系: 类型 + 名称(参数) {）。</summary>
    public static string? FindDocSignature(string text, string langId, string name)
    {
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.TrimEnd();
            if (langId == "python")
            {
                int i = line.IndexOf("def ");
                if (i < 0) continue;
                var rest = line[i..].TrimStart();
                if (!rest.StartsWith("def ")) continue;
                var after = rest[4..].TrimStart();
                if (!after.StartsWith(name, StringComparison.Ordinal)) continue;
                var tail = after[name.Length..].TrimStart();
                if (!tail.StartsWith("(")) continue;
                int close = tail.IndexOf(')');
                if (close < 0) continue;
                var seg = tail.Substring(1, close - 1);
                // 默认参数里的字符串/冒号原样保留，仅去掉换行痕迹
                var sig = (name + "(" + seg + ")").Trim();
                return sig.Length > 0 ? sig : null;
            }
            else if (Syntax.LangDef.IsCLike(langId))
            {
                // 排除控制语句；形如 "Type Name(args) {" 或 "Name(args) {" 的定义行
                if (line.Length == 0 || line.Contains(';')) continue;
                if (line.Contains(" if(") || line.StartsWith("if(") || line.Contains("for(") ||
                    line.Contains("for (") || line.Contains("while") || line.Contains("switch") ||
                    line.Contains("catch") || line.Contains("return ")) continue;
                int p = line.IndexOf('(');
                if (p <= 0) continue;
                var head = line[..p].TrimEnd();
                int sp = head.LastIndexOf(' ');
                var fname = sp >= 0 ? head[(sp + 1)..] : head;
                if (fname != name || fname.Length == 0) continue;
                bool looksDef = sp >= 0 || line.TrimStart().StartsWith(name);   // 前面有返回类型或顶格
                if (!looksDef) continue;
                int close = line.IndexOf(')', p);
                if (close < 0) continue;
                var seg = line.Substring(p + 1, close - p - 1);
                var sig = (name + "(" + seg + ")").Trim();
                return sig;
            }
        }
        return null;
    }

    // ---------- 调用点识别 ----------

    /// <summary>
    /// 识别光标所在的函数调用：返回 false 表示当前不在参数输入位置。
    /// caret 为 0 计字符偏移（与编辑器内部一致）。
    /// </summary>
    public static bool TryGetHint(string text, int caret, string langId,
        out string funcName, out int argIndex, out string signature, out string source)
    {
        funcName = ""; argIndex = 0; signature = ""; source = "";
        if (string.IsNullOrEmpty(text) || caret <= 0) return false;
        caret = Math.Min(caret, text.Length);

        // 窗口：向前最多 4000 字符，足够覆盖一次调用
        int start = Math.Max(0, caret - 4000);
        var mask = Masked(text, start, caret, langId);

        // 正向扫描窗口，维护未闭合括号栈（跳过字符串/注释），光标处栈顶即最内层调括号
        var stack = new List<int>();
        var brackets = new List<int>();     // 与 stack 平行：该括号是 ( 还是 [
        for (int i = start; i < caret; i++)
        {
            if (mask[i]) continue;
            char c = text[i];
            if (c == '(') { stack.Add(i); brackets.Add('('); }
            else if (c == ')')
            {
                if (stack.Count > 0 && brackets[^1] == '(') { stack.RemoveAt(stack.Count - 1); brackets.RemoveAt(brackets.Count - 1); }
            }
            else if (c == '[') { if (stack.Count > 0) { stack.Add(i); brackets.Add('['); } }
            else if (c == ']') { if (stack.Count > 0 && brackets[^1] == '[') { stack.RemoveAt(stack.Count - 1); brackets.RemoveAt(brackets.Count - 1); } }
        }
        if (stack.Count == 0 || brackets[^1] != '(') return false;   // 不在调括号内
        int open = stack[^1];

        // 函数名：向前取标识符（可含点号的成员调用）
        int e = open;
        while (e > start && (text[e - 1] == ' ' || text[e - 1] == '\t')) e--;
        int b = e;
        while (b > start && (char.IsLetterOrDigit(text[b - 1]) || text[b - 1] == '_' || text[b - 1] == '.')) b--;
        if (b == e) return false;
        funcName = text[b..e];
        if (funcName.StartsWith(".")) return false;

        // 当前参数序号：括号内顶层逗号计数（嵌套调用/下标里的逗号不计）
        int commas = 0, depth = 0, bdepth = 0;
        for (int i = open + 1; i < caret; i++)
        {
            if (mask[i]) continue;
            char c = text[i];
            if (c == '(') depth++;
            else if (c == ')') depth--;
            else if (c == '[') bdepth++;
            else if (c == ']') bdepth--;
            else if (c == ',' && depth == 0 && bdepth == 0) commas++;
        }
        argIndex = commas;

        // 签名：先内置表，再文档定义
        var builtin = Builtin(langId, funcName);
        if (builtin is not null) { signature = builtin; source = "builtin"; }
        else
        {
            var doc = FindDocSignature(text, langId, funcName);
            if (doc is not null) { signature = doc; source = "doc"; }
        }
        return true;
    }

    /// <summary>窗口内的字符串/注释掩码：true = 该字符在字符串或注释里（括号/逗号不参与解析）。</summary>
    public static bool[] Masked(string text, int start, int end, string langId)
    {
        var mask = new bool[text.Length];
        bool inBlock = false;
        for (int i = start; i < end; i++)
        {
            char c = text[i];
            if (inBlock)
            {
                mask[i] = true;
                if (c == '*' && i + 1 < end && text[i + 1] == '/') { mask[i + 1] = true; inBlock = false; i++; }
                continue;
            }
            if (Syntax.LangDef.IsCLike(langId) && c == '/' && i + 1 < end && text[i + 1] == '/')
            {
                int j = i;
                while (j < end && text[j] != '\n') mask[j++] = true;
                i = j - 1;
                continue;
            }
            if (Syntax.LangDef.IsCLike(langId) && c == '/' && i + 1 < end && text[i + 1] == '*') { mask[i] = true; mask[i + 1] = true; inBlock = true; i++; continue; }
            if (langId == "python" && c == '#')
            {
                int j = i;
                while (j < end && text[j] != '\n') mask[j++] = true;
                i = j - 1;
                continue;
            }
            if (c == '"' || c == '\'')
            {
                char quote = c;
                mask[i] = true;
                i++;
                while (i < end)
                {
                    mask[i] = true;
                    if (text[i] == '\\' && langId != "json") { if (i + 1 < end) mask[i + 1] = true; i += 2; continue; }
                    if (text[i] == quote) break;
                    i++;
                }
                continue;
            }
        }
        return mask;
    }
}
