//using System.Text;

namespace AntPad.Controls;

/// <summary>
/// 列块（矩形）选区编辑的纯文本算法，与 UI 解耦以便充分测试。
/// 行内列按字符计（0 起），制表符按 1 列处理（编辑器内核口径一致）。
/// </summary>
public static class BlockEditEngine
{
    /// <summary>由锚点与当前光标（行,列）归纳出规范矩形（左上/右下角）。</summary>
    public static (int RowA, int ColA, int RowB, int ColB) Normalize(
        (int Line, int Col) anchor, (int Line, int Col) caret)
    {
        int rowA = Math.Min(anchor.Line, caret.Line), rowB = Math.Max(anchor.Line, caret.Line);
        int colA = Math.Min(anchor.Col, caret.Col), colB = Math.Max(anchor.Col, caret.Col);
        return (rowA, colA, rowB, colB);
    }

    /// <summary>矩形覆盖的每行区间（0 计行；行不足列长时区间收缩到该行末尾；空行跳过）。</summary>
    public static List<(int Line, int ColStart, int ColEnd)> CoveredRanges(
        IReadOnlyList<string> lines, (int Line, int Col) anchor, (int Line, int Col) caret)
    {
        var (rowA, colA, rowB, colB) = Normalize(anchor, caret);
        var result = new List<(int, int, int)>();
        for (int r = rowA; r <= rowB && r < lines.Count; r++)
        {
            int len = lines[r].Length;
            int s = Math.Min(colA, len), e = Math.Min(colB, len);
            if (e > s) result.Add((r, s, e));   // 起点在行尾之外时不虚占该行
        }
        return result;
    }

    /// <summary>对矩形覆盖的每一行等量插入文本（在 ColStart 处），返回新行列表。</summary>
    public static List<string> Insert(IReadOnlyList<string> lines, (int Line, int Col) anchor, (int Line, int Col) caret, string text)
    {
        var ranges = CoveredRanges(lines, anchor, caret);
        var arr = new List<string>(lines);
        if (ranges.Count == 0) return arr;
        int at = ranges[0].ColStart;                 // 全部行取同一列（矩形语义）
        foreach (var (r, _, _) in ranges)
            if (r < arr.Count && at <= arr[r].Length)
                arr[r] = arr[r].Insert(at, text);
        return arr;
    }

    /// <summary>对矩形覆盖的每一行删除 [colA, colB) 区间，返回新行列表。</summary>
    public static List<string> Delete(IReadOnlyList<string> lines, (int Line, int Col) anchor, (int Line, int Col) caret)
    {
        var ranges = CoveredRanges(lines, anchor, caret);
        var arr = new List<string>(lines);
        if (ranges.Count == 0) return arr;
        foreach (var (r, s, e) in ranges)   // s/e 已收缩到各行实际长度
            if (r < arr.Count && e > s)
                arr[r] = arr[r].Remove(s, e - s);
        return arr;
    }
}
