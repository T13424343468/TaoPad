using AntPad.Syntax;
using System.Text.RegularExpressions;

namespace AntPad.Services;

/// <summary>
/// 语法智能提示引擎（VS 风格交互）：
/// - 输入标识符前缀（≥2 个字符）→ 提示当前语言关键字 + 文档中已有的词
///   （大小写不敏感过滤；接受补全时插入关键字的标准写法，如 SQL 输入 sele → SELECT）
/// - 输入"."→ 提示文档中出现过的成员名（形如 a.b 的 b）
/// 提示与过滤均为纯文本计算，不依赖任何编译器服务。
/// </summary>
public static class CompletionEngine
{
    /// <summary>计算光标处的补全候选；无候选时返回空表。prefix 为将被替换的前缀。</summary>
    public static List<string> GetCompletions(string text, int caret, LangDef lang, out string prefix)
    {
        prefix = "";
        if (string.IsNullOrEmpty(text) || caret <= 0 || caret > text.Length) return new();

        // "." 触发：成员提示
        if (text[caret - 1] == '.')
        {
            prefix = "";
            return DocMembers(text);
        }

        // 标识符前缀
        int i = caret - 1;
        while (i >= 0 && (char.IsLetterOrDigit(text[i]) || text[i] == '_')) i--;
        prefix = text[(i + 1)..caret];
        if (prefix.Length < 2 || !char.IsLetter(prefix[0]) && prefix[0] != '_') return new();

        // 前缀紧跟"."（如输入 a.in）→ 成员提示
        if (i >= 0 && text[i] == '.')
        {
            var p0 = prefix;
            return DocMembers(text).Where(w => w.StartsWith(p0, StringComparison.OrdinalIgnoreCase)).ToList();
        }

        // 词表 = 控制流词 + 关键词 + 内置类型（三表合并，缺一不可：
        // 此前只取 Keywors 表，Python 的 def/if、C# 的 for/while 都提示不出来）。
        // 之后按文档中出现顺序补充标识符。
        var pool = new List<string>(lang.ControlWords.Length + lang.Keywords.Length + lang.Types.Length);
        pool.AddRange(lang.ControlWords);
        pool.AddRange(lang.Keywords);
        pool.AddRange(lang.Types);
        pool.AddRange(DocIdentifiers(text));

        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var w in pool)
            if (w.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)
                && !string.Equals(w, prefix, StringComparison.Ordinal)
                && seen.Add(w))
                result.Add(w);
        return result;
    }

    /// <summary>文档中出现过的成员名（a.b 的 b），按出现频次降序。</summary>
    public static List<string> DocMembers(string text)
    {
        var freq = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (Match m in Regex.Matches(text, @"(?<=\.)[A-Za-z_]\w*"))
        {
            var w = m.Value;
            freq[w] = freq.TryGetValue(w, out var n) ? n + 1 : 1;
            if (freq.Count > 400) break;
        }
        return freq.OrderByDescending(kv => kv.Value).Select(kv => kv.Key).ToList();
    }

    /// <summary>文档中出现过的标识符（去重，保序）。</summary>
    public static List<string> DocIdentifiers(string text)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var list = new List<string>();
        foreach (Match m in Regex.Matches(text, @"[A-Za-z_]\w*"))
            if (m.Value.Length >= 3 && seen.Add(m.Value))
            {
                list.Add(m.Value);
                if (list.Count > 300) break;
            }
        return list;
    }
}
