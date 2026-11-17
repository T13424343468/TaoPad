using AntPad.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;

namespace AntPad.Views;

/// <summary>
/// 文章预览面板（1.1.0 拍板）：Markdown 与 Fountain 剧本的排版预览。
/// 只读旁路——正文永远在编辑器里，本面板只按规则渲染一份映像。
/// 颜色全部走 ThemeResource（道映设计法：禁内联 hex），字号走 4-8 网格档位。
/// </summary>
public sealed class ArticlePreview : ContentControl
{
    readonly ScrollViewer _scroll;
    readonly RichTextBlock _rtb;

    public ArticlePreview()
    {
        _rtb = new RichTextBlock
        {
            Margin = new Thickness(32, 24, 32, 32),
            TextWrapping = Microsoft.UI.Xaml.TextWrapping.Wrap,
        };
        _scroll = new ScrollViewer { Content = _rtb };
        Content = _scroll;
        PaintBg();
        ThemeService.ThemeApplied += PaintBg;   // 换肤跟随：字典交换后重涂
    }

    /// <summary>背景直涂 Ant.Bg（主题字典交换后 ThemeResource 重估不可靠，与窗体大面同口径）。</summary>
    void PaintBg()
    {
        try
        {
            if (Application.Current.Resources.TryGetValue("Ant.Bg", out var v) && v is Brush br)
                Background = br;
        }
        catch { /* 取不到键保持现状 */ }
    }

    /// <summary>按语言渲染全文；非文章语言调用本方法不渲染（保持上次内容，由 MainWindow 控制可见性）。</summary>
    public void Render(string text, string langId)
    {
        _rtb.Blocks.Clear();
        var lines = text.Replace("\r\n", "\n").Split('\n');
        if (langId == "fountain") RenderFountain(lines);
        else RenderMarkdown(lines);
    }

    // ================= Markdown =================

    void RenderMarkdown(string[] lines)
    {
        bool inFence = false;
        for (int i = 0; i < lines.Length; i++)
        {
            var t = lines[i];
            var trimmed = t.TrimStart();
            // 代码围栏：内部原样等宽渲染，跳过行内解析
            if (trimmed.StartsWith("```") || trimmed.StartsWith("~~~"))
            {
                inFence = !inFence;
                if (inFence) continue;
                continue;
            }
            if (inFence)
            {
                _rtb.Blocks.Add(Block(InlineRuns(t, mono: true), top: 2));
                continue;
            }
            // ATX 标题：#..######
            int h = 0;
            while (h < trimmed.Length && trimmed[h] == '#') h++;
            if (h is >= 1 and <= 6 && h < trimmed.Length && trimmed[h] == ' ')
            {
                _rtb.Blocks.Add(Block(
                    new List<Inline> { new Run { Text = trimmed[(h + 1)..].Trim(), FontWeight = Microsoft.UI.Text.FontWeights.Bold } },
                    top: h <= 2 ? 16 : 12, size: HeadingSize(h)));
                continue;
            }
            // 无序/有序列表：符号后缩进，正文照常行内解析
            if (trimmed.Length > 1 && (trimmed[0] is '-' or '*' or '+') && trimmed[1] == ' ')
            {
                var runs = new List<Inline> { new Run { Text = "•  " } };
                runs.AddRange(InlineRuns(trimmed[2..]));
                _rtb.Blocks.Add(Block(runs, indent: 24, top: 2));
                continue;
            }
            if (Ordered(trimmed, out string? rest))
            {
                var runs = new List<Inline> { new Run { Text = trimmed[..^rest.Length] + "  " } };
                runs.AddRange(InlineRuns(rest));
                _rtb.Blocks.Add(Block(runs, indent: 24, top: 2));
                continue;
            }
            if (t.Length == 0) { _rtb.Blocks.Add(Block(new List<Inline> { new Run { Text = "" } }, top: 4)); continue; }
            _rtb.Blocks.Add(Block(InlineRuns(t), top: 2));
        }
    }

    /// <summary>识别「1. 」「10) 」有序列表头，返回符号后的正文。</summary>
    static bool Ordered(string s, out string rest)
    {
        rest = "";
        int i = 0;
        while (i < s.Length && char.IsAsciiDigit(s[i])) i++;
        if (i == 0 || i >= s.Length || s[i] is not ('.' or ')') || i + 1 >= s.Length || s[i + 1] != ' ') return false;
        rest = s[(i + 2)..];
        return true;
    }

    static double HeadingSize(int level) => level switch
    {
        1 => 28, 2 => 24, 3 => 20, 4 => 18, 5 => 16, _ => 14,
    };

    /// <summary>行内解析：`code` 等宽、**粗体**、*斜体*。嵌套场景按先粗后斜的顺序拆分。</summary>
    List<Inline> InlineRuns(string text, bool mono = false)
    {
        var list = new List<Inline>();
        int pos = 0;
        while (pos < text.Length)
        {
            // `code` 优先：整段原样等宽
            int code = text.IndexOf('`', pos);
            if (code >= 0)
            {
                int end = text.IndexOf('`', code + 1);
                if (end > code + 1)
                {
                    if (code > pos) list.AddRange(BasicRuns(text[pos..code], mono));
                    list.Add(new Run
                    {
                        Text = text[(code + 1)..end],
                        FontFamily = new FontFamily("Cascadia Mono, Consolas"),
                    });
                    pos = end + 1;
                    continue;
                }
            }
            int bold = text.IndexOf("**", pos, StringComparison.Ordinal);
            if (bold >= 0)
            {
                int end = text.IndexOf("**", bold + 2, StringComparison.Ordinal);
                if (end > bold + 2)
                {
                    if (bold > pos) list.AddRange(BasicRuns(text[pos..bold], mono));
                    list.AddRange(BasicRuns(text[(bold + 2)..end], mono, bold: true));
                    pos = end + 2;
                    continue;
                }
            }
            list.AddRange(BasicRuns(text[pos..], mono));
            break;
        }
        if (list.Count == 0) list.Add(new Run { Text = text });
        return list;
    }

    /// <summary>粗/斜体拆分后的剩余部分：只处理 *斜体*。</summary>
    static List<Inline> BasicRuns(string text, bool mono, bool bold = false)
    {
        var list = new List<Inline>();
        int pos = 0;
        while (!mono && pos < text.Length)
        {
            int star = text.IndexOf('*', pos);
            if (star < 0) break;
            int end = text.IndexOf('*', star + 1);
            if (end > star + 1)
            {
                if (star > pos) list.Add(MakeRun(text[pos..star], mono, bold, italic: false));
                list.Add(MakeRun(text[(star + 1)..end], mono, bold, italic: true));
                pos = end + 1;
                continue;
            }
            break;
        }
        if (pos < text.Length) list.Add(MakeRun(text[pos..], mono, bold, italic: false));
        return list;
    }

    static Run MakeRun(string text, bool mono, bool bold, bool italic) => new()
    {
        Text = text,
        FontFamily = mono ? new FontFamily("Cascadia Mono, Consolas") : null,
        FontWeight = bold ? Microsoft.UI.Text.FontWeights.Bold : Microsoft.UI.Text.FontWeights.Normal,
        FontStyle = italic ? Windows.UI.Text.FontStyle.Italic : Windows.UI.Text.FontStyle.Normal,
    };

    static Paragraph Block(List<Inline> runs, double top, double? size = null, double indent = 0)
    {
        var p = new Paragraph { Margin = new Thickness(indent, top, 0, 2), LineHeight = size is null ? 22 : size.Value * 1.5 };
        if (size is { } s)
            foreach (var r in runs.OfType<Run>()) r.FontSize = s;
        foreach (var r in runs) p.Inlines.Add(r);
        return p;
    }

    // ================= Fountain 剧本 =================

    void RenderFountain(string[] lines)
    {
        for (int i = 0; i < lines.Length; i++)
        {
            var line = lines[i].TrimEnd('\r');
            var t = line.Trim();
            if (t.Length == 0)
            {
                _rtb.Blocks.Add(SceneBlock(new List<Inline> { new Run { Text = "" } }, top: 6));
                continue;
            }
            // 场景标题：INT./EXT. 前缀或结尾 # 强制——居中加粗
            if (IsScene(t))
            {
                var runs = new List<Inline> { new Run { Text = t.TrimEnd('#').Trim(), FontWeight = Microsoft.UI.Text.FontWeights.Bold } };
                _rtb.Blocks.Add(SceneBlock(runs, top: 16, size: 16, center: true));
                continue;
            }
            // 转场（结尾 TO: 或 > 前缀）：右对齐
            if (t.StartsWith('>') || t.EndsWith("TO:", StringComparison.OrdinalIgnoreCase) && t.Length > 4 && char.IsUpper(t[0]))
            {
                var text = t.StartsWith('>') ? t[1..].Trim() : t;
                _rtb.Blocks.Add(SceneBlock(new List<Inline> { new Run { Text = text } }, top: 12, right: true));
                continue;
            }
            // 人物（全大写且下一行非空）：居中
            if (IsCharacter(t, lines, i))
            {
                _rtb.Blocks.Add(SceneBlock(new List<Inline> { new Run { Text = t } }, top: 14, center: true));
                continue;
            }
            // 普通动作/台词：统一左对齐，台词缩进由上下文人眼可读即可
            _rtb.Blocks.Add(SceneBlock(new List<Inline> { new Run { Text = t } }, top: 2));
        }
    }

    static bool IsScene(string t)
    {
        foreach (var head in new[] { "INT.", "EXT.", "EST.", "INT/EXT.", "I/E." })
            if (t.StartsWith(head, StringComparison.OrdinalIgnoreCase)) return true;
        return t.Length > 1 && t.EndsWith("#", StringComparison.Ordinal) && char.IsUpper(t[0]);
    }

    static bool IsCharacter(string t, string[] lines, int idx) =>
        t.Length > 1 && t == t.ToUpperInvariant() && idx + 1 < lines.Length && lines[idx + 1].Trim().Length > 0;

    static Paragraph SceneBlock(List<Inline> runs, double top, double? size = null, bool center = false, bool right = false)
    {
        var p = new Paragraph
        {
            Margin = new Thickness(0, top, 0, 2),
            LineHeight = 22,
            TextAlignment = center ? TextAlignment.Center : right ? TextAlignment.Right : TextAlignment.Left,
        };
        if (size is { } s)
            foreach (var r in runs.OfType<Run>()) r.FontSize = s;
        foreach (var r in runs) p.Inlines.Add(r);
        return p;
    }
}
