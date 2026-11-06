using System.Text;
using System.Text.RegularExpressions;

namespace AntPad.Services;

public readonly record struct FindOpts(
    bool Regex = false,
    bool CaseSensitive = false,
    bool WholeWord = false);

/// <summary>查找/替换引擎：字面量与正则统一处理。</summary>
public static class SearchEngine
{
    /// <summary>正则匹配超时：防灾难回溯把界面冻死（用户可能输入恶意模式）。</summary>
    static readonly TimeSpan RegexTimeout = TimeSpan.FromSeconds(1);
    /// <summary>正则表达式能否通过编译（无效时界面给出明确提示而非"未找到"）。</summary>
    public static bool IsValidRegex(string pattern)
    {
        try { _ = new Regex(pattern, RegexOptions.None, RegexTimeout); return true; }
        catch (ArgumentException) { return false; }
        catch (System.TimeoutException) { return false; }
    }

    public static (int Pos, int Len) Find(string text, string pattern, FindOpts o, int start, bool backwards)
    {
        if (pattern.Length == 0) return (-1, 0);
        start = Math.Clamp(start, 0, text.Length);

        if (o.Regex)
        {
            var opts = o.CaseSensitive ? RegexOptions.None : RegexOptions.IgnoreCase;
            try
            {
                if (!backwards)
                {
                    var m = new Regex(pattern, opts, RegexTimeout).Match(text, start);
                    return m.Success ? (m.Index, m.Length) : (-1, 0);
                }
                else
                {
                    var ms = new Regex(pattern, opts, RegexTimeout).Matches(text);
                    Match? best = null;
                    foreach (Match m in ms)
                        if (m.Index < start && (m.Index + m.Length) <= start || m.Index < start)
                            if (m.Index < start && (best is null || m.Index > best.Index))
                                best = m;
                    return best is null ? (-1, 0) : (best.Index, best.Length);
                }
            }
            catch (ArgumentException) { return (-1, 0); }
            catch (System.TimeoutException) { return (-1, 0); }   // 灾难回溯：超时按未找到处理
        }

        var cmp = o.CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;

        if (!backwards)
        {
            int p = text.IndexOf(pattern, start, cmp);
            while (p >= 0 && o.WholeWord && !IsWordBoundary(text, p, pattern.Length))
                p = text.IndexOf(pattern, p + 1, cmp);
            return p < 0 ? (-1, 0) : (p, pattern.Length);
        }
        else
        {
            int p = text.LastIndexOf(pattern, Math.Min(start, text.Length - pattern.Length), cmp);
            if (start == text.Length) p = text.LastIndexOf(pattern, cmp);
            while (p >= 0 && o.WholeWord && !IsWordBoundary(text, p, pattern.Length))
                p = p > 0 ? text.LastIndexOf(pattern, p - 1, cmp) : -1;
            return p < 0 ? (-1, 0) : (p, pattern.Length);
        }
    }

    static bool IsWordBoundary(string text, int pos, int len)
    {
        bool before = pos > 0 && IsWordChar(text[pos - 1]);
        bool after = pos + len < text.Length && IsWordChar(text[pos + len]);
        return !before && !after;
    }

    static bool IsWordChar(char c) => char.IsLetterOrDigit(c) || c == '_';

    /// <summary>统计并返回全部匹配（用于高亮），限制上限防止超大文件卡顿。</summary>
    public static List<(int Start, int Len)> FindAll(string text, string pattern, FindOpts o, int cap = 5000)
    {
        var list = new List<(int, int)>();
        if (pattern.Length == 0) return list;

        if (o.Regex)
        {
            try
            {
                var opts = o.CaseSensitive ? RegexOptions.None : RegexOptions.IgnoreCase;
                foreach (Match m in new Regex(pattern, opts, RegexTimeout).Matches(text))
                {
                    list.Add((m.Index, m.Length));
                    if (list.Count >= cap) break;
                }
            }
            catch (ArgumentException) { }
            catch (System.TimeoutException) { }   // 灾难回溯：超时返回已有结果
        }
        else
        {
            var cmp = o.CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
            int p = 0;
            while (list.Count < cap && (p = text.IndexOf(pattern, p, cmp)) >= 0)
            {
                if (!o.WholeWord || IsWordBoundary(text, p, pattern.Length))
                    list.Add((p, pattern.Length));
                p += Math.Max(1, pattern.Length);
            }
        }
        return list;
    }

    /// <summary>执行"全部替换"，返回替换次数。</summary>
    public static int ReplaceAll(ref string text, string pattern, string replacement, FindOpts o)
    {
        if (pattern.Length == 0) return 0;
        if (o.Regex)
        {
            try
            {
                var opts = o.CaseSensitive ? RegexOptions.None : RegexOptions.IgnoreCase;
                var re = new Regex(pattern, opts, RegexTimeout);
                int replacedCount = re.Matches(text).Count;
                text = re.Replace(text, replacement);
                return replacedCount;
            }
            catch (ArgumentException) { return 0; }
            catch (System.TimeoutException) { return 0; }   // 灾难回溯：超时放弃替换
        }

        int count = 0;
        var sb = new StringBuilder();
        int i = 0;
        while (i < text.Length)
        {
            if (i + pattern.Length <= text.Length &&
                string.Compare(text, i, pattern, 0, pattern.Length, o.CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase) == 0 &&
                (!o.WholeWord || IsWordBoundary(text, i, pattern.Length)))
            {
                sb.Append(replacement);
                i += pattern.Length;
                count++;
            }
            else
            {
                sb.Append(text[i]);
                i++;
            }
        }
        text = sb.ToString();
        return count;
    }
}
