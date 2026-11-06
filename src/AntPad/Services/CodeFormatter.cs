using AntPad.Syntax;
using System.Text;
using System.Text.RegularExpressions;

namespace AntPad.Services;

/// <summary>
/// 按语言风格格式化整篇文档：
/// - SQL：关键字统一大写，主要子句换行分层
/// - JSON：标准两空格缩进
/// - XML/HTML：标准缩进重排
/// - C 系：花括号缩进归一
/// 其余语言不自动重排（避免破坏内容），仅去行尾空白。
/// 字符串与注释内容一律原样保留。
/// </summary>
public static class CodeFormatter
{
    public static string Format(string text, LangDef lang)
    {
        var r = lang.Id switch
        {
            "sql" => FormatSql(text, lang),
            "json" => FormatJson(text),
            "xml" => FormatXml(text),
            "clike" or "csharp" => FormatBraces(text, lang),
            _ => FormatTrailing(text),
        };
        return r.Replace("\r\n", "\n").Replace('\r', '\n');
    }

    // ================= SQL =================

    static string FormatSql(string text, LangDef lang)
    {
        // 1) 保护字符串与注释
        var vault = new List<string>();
        string protected1 = Regex.Replace(text, @"'(?:[^']|'')*|--[^\n]*|/\*.*?\*/",
            m => { vault.Add(m.Value); return $"\u0001{vault.Count - 1}\u0001"; }, RegexOptions.Singleline);

        // 2) 关键字大写（含双词如 GROUP BY）
        protected1 = Regex.Replace(protected1, @"\b[a-zA-Z_]\w*\b", m =>
            lang.ControlWords.Contains(m.Value, StringComparer.OrdinalIgnoreCase)
                ? m.Value.ToUpperInvariant() : m.Value);

        // 3) 主要子句换行
        protected1 = Regex.Replace(protected1, @"\s+\b(FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|VALUES|SET|UNION(?: ALL)?|(?:INNER |LEFT(?: OUTER)? |RIGHT(?: OUTER)? |FULL(?: OUTER)? |CROSS )?JOIN)\b",
            m => "\n" + m.Value.TrimStart());

        // 4) 压缩多余空白（占位符段之外）
        var lines = protected1.Split('\n');
        for (int i = 0; i < lines.Length; i++)
        {
            var l = Regex.Replace(lines[i].Trim(), @"\s{2,}", " ");
            if (l.Length > 0 && !l.EndsWith(",") && i < lines.Length - 1) l += "";
            lines[i] = l;
        }
        var outText = string.Join('\n', lines.Where(l => l.Length > 0));

        // 5) 还原字符串与注释
        return Regex.Replace(outText, "\u0001(\\d+)\u0001", m => vault[int.Parse(m.Groups[1].Value)]);
    }

    // ================= JSON =================

    static string FormatJson(string text)
    {
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(text);
            var opts = new System.Text.Json.JsonSerializerOptions
            {
                WriteIndented = true,
                Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            };
            return System.Text.Json.JsonSerializer.Serialize(doc.RootElement, opts);
        }
        catch { return text; }   // 不是合法 JSON 就原样保留
    }

    // ================= XML / HTML =================

    static string FormatXml(string text)
    {
        try
        {
            var doc = System.Xml.Linq.XDocument.Parse(text);
            var sb = new StringBuilder();
            using (var w = System.Xml.XmlWriter.Create(sb, new System.Xml.XmlWriterSettings
            {
                Indent = true,
                IndentChars = "  ",
                NewLineChars = "\n",
                OmitXmlDeclaration = string.IsNullOrEmpty(doc.Declaration?.ToString()),
            }))
            {
                doc.Save(w);
            }
            return sb.ToString();
        }
        catch { return text; }
    }

    // ================= C 系花括号缩进 =================

    static string FormatBraces(string text, LangDef lang)
    {
        var sb = new StringBuilder();
        int depth = 0;
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.TrimEnd();
            var trimmed = line.Trim();

            // 该行缩进按此前累计括号深度；闭括号开头的行先回退一级
            int shown = depth;
            if (trimmed.StartsWith('}') || trimmed.StartsWith(')') || trimmed.StartsWith(']'))
                shown = Math.Max(0, depth - 1);

            if (trimmed.Length > 0)
                sb.Append(new string(' ', 4 * shown)).Append(trimmed);
            sb.Append('\n');

            // 更新深度（粗略统计本行括号；字符串已含引号内内容，极端嵌套可能偏差）
            foreach (var ch in trimmed)
            {
                if (ch == '{' || ch == '(' || ch == '[') depth++;
                else if (ch == '}' || ch == ')' || ch == ']') depth = Math.Max(0, depth - 1);
            }
        }
        return sb.ToString().TrimEnd('\n');
    }

    // ================= 其他语言 =================

    static string FormatTrailing(string text)
    {
        var lines = text.Split('\n');
        for (int i = 0; i < lines.Length; i++) lines[i] = lines[i].TrimEnd();
        return string.Join('\n', lines).TrimStart('\n');
    }
}
