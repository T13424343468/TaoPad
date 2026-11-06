using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace AntPad.Views;

public sealed partial class FindReplacePanel : UserControl
{
    public event Action? FindNextRequested;
    public event Action? FindPrevRequested;
    public event Action? ReplaceRequested;
    public event Action? ReplaceAllRequested;
    public event Action? CloseRequested;

    bool _shift;    // 本面板内跟踪 Shift（CorePhysicalKeyStatus 无 Shift 成员，不猜 API）

    public FindReplacePanel()
    {
        InitializeComponent();
        PatternBox.KeyDown += (_, e) =>
        {
            if (e.Key == Windows.System.VirtualKey.Shift) { _shift = true; return; }
            if (e.Key == Windows.System.VirtualKey.Enter)
            {
                if (e.KeyStatus.IsMenuKeyDown || _shift) FindPrevRequested?.Invoke();
                else FindNextRequested?.Invoke();
                e.Handled = true;
            }
            if (e.Key == Windows.System.VirtualKey.Escape) { CloseRequested?.Invoke(); e.Handled = true; }
        };
        PatternBox.KeyUp += (_, e) =>
        {
            if (e.Key == Windows.System.VirtualKey.Shift) _shift = false;
        };
        ReplaceBox.KeyDown += (_, e) =>
        {
            if (e.Key == Windows.System.VirtualKey.Enter) { ReplaceRequested?.Invoke(); e.Handled = true; }
            if (e.Key == Windows.System.VirtualKey.Escape) { CloseRequested?.Invoke(); e.Handled = true; }
        };
        // 构造完成即涂一次（IThemePaintable：字典交换后由 MainWindow.OnThemeApplied 再涂）
        ApplyTheme();
    }

    public string Pattern => PatternBox.Text ?? "";
    public string Replacement => ReplaceBox.Text ?? "";

    public Services.FindOpts Options => new(
        Regex: RegexCheck.IsChecked == true,
        CaseSensitive: CaseCheck.IsChecked == true,
        WholeWord: WordCheck.IsChecked == true);

    public void SetResult(string text) => ResultText.Text = text;

    public void Show(bool withReplace)
    {
        ReplaceRow.Visibility = withReplace ? Visibility.Visible : Visibility.Collapsed;
        Visibility = Visibility.Visible;
        PatternBox.Focus(FocusState.Keyboard);
        PatternBox.SelectAll();
    }

    public void Hide() { Visibility = Visibility.Collapsed; }

    /// <summary>VS 式直涂主题（Ant.Surface/Ant.Border/Ant.Text）：换肤面板即时随主题，
    /// 取不到键时保持回退色，不依赖 ThemeResource 重估（与 CodeEditor.TryBrush 同法）。</summary>
    public void ApplyTheme()
    {
        var res = Application.Current.Resources;
        Brush? Res(string key) =>
            res.TryGetValue(key, out var v) && v is Brush b ? b : null;

        var surface = Res("Ant.Surface") ?? Solid(255, 255, 255);
        var border = Res("Ant.Border") ?? Solid(205, 212, 220);
        var text = Res("Ant.Text") ?? Solid(31, 36, 48);
        var subText = Res("Ant.SubText") ?? Solid(108, 117, 125);

        RootBorder.Background = surface;
        RootBorder.BorderBrush = border;

        // 输入框：底、字、框线、占位符随主题（防止墨夜下输入框仍白底黑字）
        PaintBox(PatternBox, surface, border, text, subText);
        PaintBox(ReplaceBox, surface, border, text, subText);

        // 图标/操作按钮：统一底与字
        PaintButton(FindPrevBtn, surface, border, text);
        PaintButton(FindNextBtn, surface, border, text);
        PaintButton(CloseBtn, surface, border, text);
        PaintButton(ReplaceBtn, surface, border, text);
        PaintButton(ReplaceAllBtn, surface, border, text);

        ResultText.Foreground = subText;
        foreach (var cb in new[] { CaseCheck, WordCheck, RegexCheck })
            cb.Foreground = text;
    }

    static SolidColorBrush Solid(byte r, byte g, byte b) =>
        new() { Color = Windows.UI.Color.FromArgb(255, r, g, b) };

    static void PaintBox(TextBox box, Brush bg, Brush border, Brush fg, Brush placeholder)
    {
        box.Background = bg;
        box.Foreground = fg;
        box.BorderBrush = border;
        box.PlaceholderForeground = placeholder;
    }

    static void PaintButton(Button btn, Brush bg, Brush border, Brush fg)
    {
        btn.Background = bg;
        btn.Foreground = fg;
        btn.BorderBrush = border;
    }

    void OnReplace(object sender, RoutedEventArgs e) => ReplaceRequested?.Invoke();
    void OnReplaceAll(object sender, RoutedEventArgs e) => ReplaceAllRequested?.Invoke();
    void OnClose(object sender, RoutedEventArgs e) => CloseRequested?.Invoke();
    void OnFindNext(object sender, RoutedEventArgs e) => FindNextRequested?.Invoke();
    void OnFindPrev(object sender, RoutedEventArgs e) => FindPrevRequested?.Invoke();
}
