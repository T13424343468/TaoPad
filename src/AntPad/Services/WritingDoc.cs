using System.Security.Cryptography;
using System.Text;

namespace AntPad.Services;

/// <summary>
/// 写作模式纯逻辑件（2026-11-17 拍板 1.1.0）：大纲抽取、字数统计、快照留底。
/// 全部无 UI 依赖，LogicTests 直测；正文永远是用户的纯文本文件，
/// 快照只是旁路副本（数据之道：不碰正文真源）。
/// </summary>
public static class WritingDoc
{
    // ================= 大纲 =================

    public sealed record OutlineItem(int Line, int Level, string Title);

    /// <summary>抽取 Markdown 大纲：ATX 标题（#..######，允许行首至多 3 空格）。
    /// 跳过代码块（```/~~~ 围栏）内的 # 行。</summary>
    public static List<OutlineItem> MarkdownOutline(string text)
    {
        var result = new List<OutlineItem>();
        bool inFence = false;
        string fence = "";
        var lines = text.Split('\n');
        for (int i = 0; i < lines.Length; i++)
        {
            var line = lines[i].TrimEnd('\r');
            var t = line.TrimStart();
            if (inFence)
            {
                if (t.StartsWith(fence, StringComparison.Ordinal)) { inFence = false; fence = ""; }
                continue;
            }
            if (t.StartsWith("```") || t.StartsWith("~~~"))
            {
                inFence = true;
                fence = t[..3];
                continue;
            }
            int h = 0;
            while (h < t.Length && t[h] == '#') h++;
            if (h is >= 1 and <= 6 && h < t.Length && t[h] == ' ')
                result.Add(new(i, h, t[(h + 1)..].Trim()));
        }
        return result;
    }

    /// <summary>抽取 Fountain 大纲：场景标题行（INT./EXT. 前缀或结尾 # 强制）。</summary>
    public static List<OutlineItem> FountainOutline(string text)
    {
        var result = new List<OutlineItem>();
        var lines = text.Split('\n');
        for (int i = 0; i < lines.Length; i++)
        {
            var line = lines[i].TrimEnd('\r');
            var t = line.Trim();
            if (t.Length == 0) continue;
            if (IsSceneHeading(t)) result.Add(new(i, 1, t.TrimEnd('#').Trim()));
        }
        return result;
    }

    static bool IsSceneHeading(string line)
    {
        foreach (var head in new[] { "INT.", "EXT.", "EST.", "INT/EXT.", "I/E." })
            if (line.StartsWith(head, StringComparison.OrdinalIgnoreCase)) return true;
        return line.Length > 1 && line.EndsWith("#", StringComparison.Ordinal) && char.IsUpper(line[0]);
    }

    // ================= 字数统计 =================

    public sealed record WordStats(int Chars, int Words, int CjkChars, int Lines);

    /// <summary>字数统计（码字口径）：西文按空白切词，中日韩字符按字计。
    /// 展示口径「字数 = 西文词数 + CJK 字符数」。</summary>
    public static WordStats CountWords(string text)
    {
        if (string.IsNullOrEmpty(text)) return new(0, 0, 0, 0);
        int cjk = 0, words = 0;
        bool inWord = false;
        foreach (var ch in text)
        {
            if (char.IsWhiteSpace(ch)) { inWord = false; continue; }
            if (ch >= '\u4e00' && ch <= '\u9fff' || ch >= '\u3400' && ch <= '\u4dbf' ||
                ch >= '\u3040' && ch <= '\u30ff' || ch >= '\xac00' && ch <= '\ud7af')
            {
                cjk++;
                inWord = false;
            }
            else if (char.IsLetterOrDigit(ch))
            {
                if (!inWord) { words++; inWord = true; }
            }
            else inWord = false;
        }
        return new(text.Length, words + cjk, cjk, text.Split('\n').Length);
    }

    // ================= 快照留底 =================

    /// <summary>快照目录：数据根/snapshots/&lt;文件指纹&gt;/，同一文件一组。</summary>
    public static string SnapshotDir(string? filePath)
    {
        string key = string.IsNullOrEmpty(filePath) ? "untitled" : HashKey(filePath);
        string dir = Path.Combine(TaoPaths.Root, "snapshots", key);
        Directory.CreateDirectory(dir);
        return dir;
    }

    static string HashKey(string s)
    {
        var bytes = MD5.HashData(Encoding.UTF8.GetBytes(s));
        return Convert.ToHexString(bytes)[..12];
    }

    /// <summary>保存快照；返回快照文件全路径。文件名带序号防同秒覆盖。</summary>
    public static string SaveSnapshot(string? filePath, string text, DateTimeOffset when)
    {
        string dir = SnapshotDir(filePath);
        string name = $"{when:yyyyMMdd-HHmmss}-{Random.Shared.Next(1000):d3}.txt";
        string path = Path.Combine(dir, name);
        File.WriteAllText(path, text);
        return path;
    }

    public sealed record SnapInfo(string Path, DateTimeOffset When, long Size);

    /// <summary>列出某文件的快照（新→旧）。</summary>
    public static List<SnapInfo> ListSnapshots(string? filePath)
    {
        var dir = SnapshotDir(filePath);
        var list = new List<SnapInfo>();
        foreach (var f in Directory.EnumerateFiles(dir, "*.txt"))
        {
            try
            {
                var fi = new FileInfo(f);
                list.Add(new(fi.FullName, fi.LastWriteTime, fi.Length));
            }
            catch { /* 单个坏文件不挡清单 */ }
        }
        return list.OrderByDescending(x => x.When).ToList();
    }

    /// <summary>读取快照正文；读不到返回 null。</summary>
    public static string? ReadSnapshot(string path)
    {
        try { return File.ReadAllText(path); }
        catch { return null; }
    }

    /// <summary>清理旧快照：每组只保留 keepN 份（新→旧）。</summary>
    public static void TrimSnapshots(string? filePath, int keepN)
    {
        var list = ListSnapshots(filePath);
        for (int i = keepN; i < list.Count; i++)
        {
            try { File.Delete(list[i].Path); } catch { /* 删不掉不挡 */ }
        }
    }

    /// <summary>每组快照保留上限（常量集中：写作快照默认 20 份）。</summary>
    public const int SnapshotKeep = 20;

    // ================= 字数每日目标 =================

    /// <summary>每日目标持久化：数据根下 wordgoal.json，坏文件按默认 1000 处理。</summary>
    public static int LoadGoal()
    {
        try
        {
            string p = Path.Combine(TaoPaths.Root, "wordgoal.json");
            if (!File.Exists(p)) return DefaultGoal;
            var v = System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, int>>(File.ReadAllText(p));
            return v is { } d && d.TryGetValue("goal", out int g) && g > 0 ? g : DefaultGoal;
        }
        catch { return DefaultGoal; }
    }

    public static void SaveGoal(int goal)
    {
        try
        {
            Directory.CreateDirectory(TaoPaths.Root);
            string p = Path.Combine(TaoPaths.Root, "wordgoal.json");
            File.WriteAllText(p, System.Text.Json.JsonSerializer.Serialize(new Dictionary<string, int> { ["goal"] = goal }));
        }
        catch { /* 目标写不进去不致命，保持内存值 */ }
    }

    public const int DefaultGoal = 1000;
}
