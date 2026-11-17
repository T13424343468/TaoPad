using AntPad.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace AntPad.Views;

/// <summary>
/// 大纲面板（1.1.0 拍板）：Markdown/Fountain 大纲导航。
/// 条目按层级缩进，单击跳到对应行；内容由 MainWindow 用 WritingDoc 抽取后喂入。
/// 纯展示控件，不含任何文件读写。
/// </summary>
public sealed class OutlinePanel : ContentControl
{
    readonly ListView _list;

    /// <summary>单击条目：参数为该条目对应的一级行号（1 起）。</summary>
    public event Action<int>? ItemClicked;

    public OutlinePanel()
    {
        _list = new ListView
        {
            SelectionMode = ListViewSelectionMode.Single,
            Margin = new Thickness(4, 4, 4, 4),
        };
        _list.ItemClick += (_, e) =>
        {
            if (e.ClickedItem is OutlineRow r) ItemClicked?.Invoke(r.Line + 1);
        };
        Content = new ScrollViewer
        {
            Content = _list,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        };
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

    /// <summary>刷新大纲条目；空大纲给出空态提示（道映设计法：空态不可静默）。</summary>
    public void Refresh(List<WritingDoc.OutlineItem> items)
    {
        _list.Items.Clear();
        if (items.Count == 0)
        {
            _list.Items.Add(new TextBlock
            {
                Text = "暂无大纲——先写点标题或场景",
                Margin = new Thickness(12, 8, 12, 8),
                TextWrapping = Microsoft.UI.Xaml.TextWrapping.Wrap,
            });
            return;
        }
        foreach (var it in items)
            _list.Items.Add(new OutlineRow(it.Line, it.Level, it.Title));
    }

    sealed class OutlineRow : Grid
    {
        public int Line { get; }
        public OutlineRow(int line0Based, int level, string title)
        {
            Line = line0Based;
            Margin = new Thickness(8 + Math.Min(level - 1, 5) * 16, 2, 8, 2);
            Children.Add(new TextBlock
            {
                Text = title.Length > 48 ? title[..48] + "…" : title,
                TextTrimming = Microsoft.UI.Xaml.TextTrimming.CharacterEllipsis,
                VerticalAlignment = VerticalAlignment.Center,
            });
        }
    }
}
