using AntPad.Models;
using AntPad.Services;
using AntPad.Syntax;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace AntPad.Controls;

/// <summary>
/// 代码编辑器控件（双内核，按语言自动切换）：
/// - 纯文本/Markdown：系统 TextBox（轻快）
/// - 代码语言（C 系/Python/JSON/XML/SQL 等）：RichEditBox，支持分段着色
///   （关键字/类型/成员/字符串/注释/数字）+ 彩虹括号（按嵌套层级着色，
///   参考 VS 彩虹括号插件效果）
/// 两个内核共用同一套查找替换、行操作、缩放与 VS 风格智能提示。
/// </summary>
public sealed class CodeEditor : Grid
{
    readonly TextBox _tb;           // 轻量内核（纯文本/Markdown）
    readonly RichEditBox _re;      // 着色内核（代码语言）
    bool _rich;                     // 当前是否使用着色内核
    bool _syncing;                  // 程序化改文本期间屏蔽事件重入
    double _zoom = 1.0;
    const double BaseFontSize = 14.0;
    LangDef _lang = LangDef.Plain;

    // 着色内核的默认前景色与彩虹括号配色
    Windows.UI.Color _baseFg = Windows.UI.Color.FromArgb(255, 38, 38, 38);

    // 编辑区底色（随主题）：清背景一律用它，不用透明色——
    // 透明 alpha-0 在部分系统 RichEditBox 上会被渲染成黑色（黑块问题根源）
    Windows.UI.Color _baseBg = Windows.UI.Color.FromArgb(255, 255, 255, 255);
    static readonly Windows.UI.Color[] BracketColors =
    {
        Windows.UI.Color.FromArgb(255, 198, 84, 80),    // 朱红
        Windows.UI.Color.FromArgb(255, 190, 138, 50),   // 琥珀
        Windows.UI.Color.FromArgb(255, 104, 150, 90),   // 苔绿
        Windows.UI.Color.FromArgb(255, 84, 118, 168),   // 黛蓝
    };
    DispatcherQueueTimer? _colorTimer;
    bool _colorPending;     // 有挂起未执行的着色回调（ScheduleRecolor 置位，Tick/收敛后清零）

    /// <summary>整篇写入前强制同步收敛着色管线（审查 2026-11-14 红1）：
    /// 停掉 220ms 防抖定时器；若尚有挂起未执行的着色回调，先同步补跑一次
    /// Recolor 把内核格式化操作收敛完，再执行本次 SetText——
    /// 杜绝异步着色回调与整篇写入在 RichEditBox 内核中交叠
    /// （E07「切语言后立即注释」崩溃的头号嫌疑）。</summary>
    void ConvergeRecolor()
    {
        try { _colorTimer?.Stop(); } catch { }
        bool pending = _colorPending;
        _colorPending = false;
        if (pending) Recolor();
    }

    // ---------- 行号栏 ----------
    readonly Canvas _gutter;            // 行号画布（左列）
    double _gutterWidth = 40;           // 行号栏宽度（随行数位数自适应）
    ScrollViewer? _tbScroll;            // 内核滚动区（同步滚动位置）
    ScrollViewer? _reScroll;
    string _gutterKey = "";             // 行号重绘指纹：可见首行/光标行/总行数没变就不重画

    // ---------- 智能提示 ----------
    readonly Popup _popup;
    readonly Border _popupBorder;
    readonly StackPanel _listPanel;
    readonly Popup _hintPopup;      // 参数提示浮层
    readonly Border _hintBorder;
    readonly TextBlock _hintText;
    readonly List<string> _items = new();
    string _prefix = "";
    string _listKey = "";       // 候选列表指纹：内容没变就不重建弹层（防闪烁）
    string _lastRaw = "";       // 上次规范文本：识别着色引发的"伪文本变化"事件
    int _sel;
    bool _accepting;
    bool _ctrlDown;
    bool _shiftDown;
    bool _chordK;
    DateTime _chordAt;

    // ---------- 代码折叠（细节见 FoldFold 部分） ----------
    List<FoldRange> _folds = new();     // 当前文本的可折叠区间缓存（未折叠态）
    string _foldsKey = "";              // 区间缓存指纹：文本没变就重算
    string _foldFull = "";              // 折叠前的完整文本（异常兜底还原用）

    /// <summary>折叠期间被隐藏的行块（当前实现一次最多一个折叠，保证安全往返）。</summary>
    sealed class HiddenBlock
    {
        public string Anchor = "";              // 锚点行原文（折叠区开头的行）
        public List<string> Lines = new();      // 被隐藏的行
        public int StartLine0;                  // 锚点在全文/折叠视图中的 0 计行号（前缀不变，两者一致）
    }
    readonly List<HiddenBlock> _hidden = new();
    bool FoldActive => _hidden.Count > 0;

    // ---------- 小地图 ----------
    public bool ShowMinimap { get; set; } = true;
    const double MiniWidth = 72.0;
    const double MiniLineH = 2.2;
    readonly Canvas _minimap = new();
    readonly Border _miniView = new()
    {
        Background = new SolidColorBrush(Windows.UI.Color.FromArgb(46, 84, 118, 168)),
        IsHitTestVisible = false,
    };
    string _minimapKey = "";
    DispatcherQueueTimer? _miniTimer;
    bool _miniDragging;

    // ---------- 滚动条（VSCode 风：细条常显，悬停/拖拽加宽，全文件常驻右侧） ----------
    const double SbTrackWidth = 14;     // 右侧命中区宽度
    const double SbThumbThin = 3;       // 细条宽度（常态）
    const double SbThumbWide = 14;      // 加宽宽度（悬停/拖拽）
    readonly Canvas _sbTrack = new()
    {
        Width = SbTrackWidth,
        HorizontalAlignment = HorizontalAlignment.Right,
        VerticalAlignment = VerticalAlignment.Stretch,
        // 透明底保留命中：不溢出时整个隐藏，不会挡选区
        Background = new SolidColorBrush(Windows.UI.Color.FromArgb(0, 0, 0, 0)),
        IsHitTestVisible = true,
    };
    readonly Border _sbThumb = new()
    {
        Width = SbThumbThin,
        HorizontalAlignment = HorizontalAlignment.Right,
        VerticalAlignment = VerticalAlignment.Top,
        CornerRadius = new CornerRadius(1.5),
        IsHitTestVisible = false,       // 命中统一由轨道层处理（含拖拽起点判断）
    };
    bool _sbHover;
    bool _sbDragging;
    double _sbDragStartY;
    double _sbDragStartOffset;

    // ---------- 公共事件 ----------
    public event EventHandler? StatusChanged;
    public event EventHandler? Modified;

    public CodeEditor()
    {
        HorizontalAlignment = HorizontalAlignment.Stretch;
        VerticalAlignment = VerticalAlignment.Stretch;

        // 主题色：查不到时用保底色，避免不可见（TryGetValue 兼容主题字典缺失场景）
        var bgBrush = TryBrush("Ant.EdBg", 255, 255, 255);
        _baseBg = TryColor("Ant.EdBg", 255, 255, 255);
        _baseFg = TryColor("Ant.EdText", 38, 38, 38);

        // 内核一：轻量 TextBox（纯文本/Markdown）
        _tb = new TextBox
        {
            AcceptsReturn = true,
            IsSpellCheckEnabled = false,
            TextWrapping = TextWrapping.NoWrap,
            FontFamily = new FontFamily("Consolas"),
            FontSize = BaseFontSize,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Stretch,
            Background = bgBrush,
            Foreground = new SolidColorBrush(_baseFg),
            BorderThickness = new Thickness(0),
            CornerRadius = new CornerRadius(0),
        };

        // 内核二：RichEditBox（代码语言，可分段着色）
        _re = new RichEditBox
        {
            IsSpellCheckEnabled = false,
            TextWrapping = TextWrapping.NoWrap,
            FontFamily = new FontFamily("Consolas"),
            FontSize = BaseFontSize,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Stretch,
            Background = bgBrush,
            BorderThickness = new Thickness(0),
            CornerRadius = new CornerRadius(0),
        };
        _re.Visibility = Visibility.Collapsed;

        // 智能提示浮层
        _listPanel = new StackPanel { MinWidth = 220 };
        _popupBorder = new Border
        {
            Child = new ScrollViewer { Content = _listPanel, MaxHeight = 232 },
            Background = new SolidColorBrush(Windows.UI.Color.FromArgb(255, 255, 255, 255)),
            BorderBrush = new SolidColorBrush(Windows.UI.Color.FromArgb(255, 200, 205, 212)),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(6),
            Padding = new Thickness(4),
        };
        // 不用轻量关闭：它会抢走键盘焦点导致方向键/回车失灵；改由焦点与选区变化手动收起
        _popup = new Popup { Child = _popupBorder, IsLightDismissEnabled = false };
        _popup.Closed += (_, _) => HidePopup();
        // 焦点万一落在弹窗层时键盘也能接管（方向键/回车照常工作）
        _popup.KeyDown += OnKeyDown;
        _popupBorder.KeyDown += OnKeyDown;

        // 参数提示浮层（与补全弹层互斥，样式一致）
        _hintText = new TextBlock
        {
            FontFamily = new FontFamily("Consolas"),
            FontSize = 13,
            TextWrapping = TextWrapping.NoWrap,
        };
        _hintBorder = new Border
        {
            Child = _hintText,
            Background = new SolidColorBrush(Windows.UI.Color.FromArgb(255, 255, 255, 255)),
            BorderBrush = new SolidColorBrush(Windows.UI.Color.FromArgb(200, 205, 212, 220)),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(6),
            Padding = new Thickness(8, 4, 8, 4),
        };
        _hintPopup = new Popup { Child = _hintBorder, IsLightDismissEnabled = false, IsOpen = false };

        // 布局：左列行号栏（自适应宽度），中列编辑区，右列小地图
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(_gutterWidth) });
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(0) });
        // 1.0.9：行号栏底色改走专属键 Ant.GutterBg（三象齐备、纯色、不经陶瓷渐变换装）
        // ——此前取 Ant.Surface，该键被 ApplyCeramic 换成渐变后真机读取失灵退保底白，
        // 墨夜下行号栏停首主题白（1.0.7/1.0.8 真机复现，截图像素定案 248,249,250=保底色）。
        _gutter = new Canvas
        {
            Background = TryBrush("Ant.GutterBg", 239, 239, 239),
            VerticalAlignment = VerticalAlignment.Stretch,
            HorizontalAlignment = HorizontalAlignment.Left,
            IsHitTestVisible = true,   // 可点：行号栏上点击折叠/展开标记
        };
        _gutter.PointerPressed += OnGutterPressed;
        SetColumn(_gutter, 0);
        SetColumn(_tb, 1);
        SetColumn(_re, 1);
        SetColumn(_minimap, 2);
        _minimap.Width = MiniWidth;
        _minimap.Background = TryBrush("Ant.GutterBg", 239, 239, 239);   // 1.0.9：随行号栏走专属键，绕开渐变换装
        _minimap.PointerPressed += OnMiniPointer;
        _minimap.PointerMoved += OnMiniPointer;
        _minimap.PointerReleased += OnMiniPointer;
        _minimap.Visibility = Visibility.Collapsed;
        Children.Add(_gutter);
        Children.Add(_tb);
        Children.Add(_re);
        Children.Add(_minimap);
        Children.Add(_popup);
        Children.Add(_hintPopup);
        // 滚动条最后入树：压在最上层（小地图/弹层之上），右缘覆盖整个编辑区。
        // 必须显式钉到第 1 列（编辑区）：Grid 子元素缺省落第 0 列，此前漏设列号，
        // 整条滚动条被挤进行号栏右缘——真机上表现为"看不见滚动条"的根因。
        _sbTrack.Children.Add(_sbThumb);
        SetColumn(_sbTrack, 1);
        Children.Add(_sbTrack);
        _sbTrack.PointerEntered += OnSbPointerEnter;
        _sbTrack.PointerExited += OnSbPointerExit;
        _sbTrack.PointerPressed += OnSbPointerPressed;
        _sbTrack.PointerMoved += OnSbPointerMove;
        _sbTrack.PointerReleased += OnSbPointerRelease;
        _sbTrack.SizeChanged += (_, _) => UpdateScrollBar();

        // 公共事件挂到两个内核（RichEditBox 的 TextChanged 与 TextBox 签名不同）
        _tb.TextChanged += OnTextChanged;
        _re.TextChanged += (s, e) => OnTextChanged(s, (object)e);
        _tb.SelectionChanged += OnSelChanged;
        _tb.LostFocus += OnLostFocus;
        _re.LostFocus += OnLostFocus;
        _tb.SizeChanged += (_, _) => StatusChanged?.Invoke(this, EventArgs.Empty);
        _re.SizeChanged += (_, _) => StatusChanged?.Invoke(this, EventArgs.Empty);
        _tb.KeyDown += OnKeyDown;
        _re.KeyDown += OnKeyDown;
        _tb.KeyUp += OnKeyUp;
        _re.KeyUp += OnKeyUp;
        _tb.PointerReleased += (_, _) => RedrawGutter();     // 鼠标点击移动光标
        _re.PointerReleased += (_, _) => RedrawGutter();

        // 加载完成后找到内核内部滚动区，同步滚动驱动行号重绘
        Loaded += (_, _) =>
        {
            try
            {
                _tbScroll = FindScroll(_tb);
                _reScroll = FindScroll(_re);
                if (_tbScroll is not null) _tbScroll.ViewChanged += (_, _) => { RedrawGutter(); UpdateMiniViewport(); UpdateScrollBar(); };
                if (_reScroll is not null) _reScroll.ViewChanged += (_, _) => { RedrawGutter(); UpdateMiniViewport(); UpdateScrollBar(); };
                RedrawGutter();
                UpdateScrollBar();
            }
            catch { /* 行号栏失败不影响编辑 */ }
        };

        // 主题切换：同步编辑器配色并重置着色/弹层状态，避免切换后提示失效
        Services.ThemeService.ThemeApplied += OnThemeApplied;
    }

    void OnThemeApplied()
    {
        // 【真凶预防】着色缓存复位必须在任何可能失败的操作之前：
        // 此前排在取色/文档格式等操作之后，中间任何一步抛异常（catch 吞掉）缓存
        // 就没清，Recolor 的幂等检查会直接跳过——关键字永远留在旧主题色，
        // 表现为"切换主题后关键字不着色"。先复位再干活，失败只丢外观不丢着色。
        _lastColorText = "";
        // 1.0.8 换肤加固：以前整段套一个 try，任何一环异常（如弹层赋值）都会让排在
        // 后面的行号栏/小地图/滚动条拿不到新主题（真机表现：正文换成了墨夜、行号栏
        // 停在首主题白）。现在逐块隔离并记入崩溃日志，单块失败不影响其余块。
        try
        {
            _baseFg = TryColor("Ant.EdText", 38, 38, 38);
            _baseBg = TryColor("Ant.EdBg", 255, 255, 255);
            var bg = TryBrush("Ant.EdBg", 255, 255, 255);
            _tb.Background = bg;
            _tb.Foreground = new SolidColorBrush(_baseFg);
            _re.Background = bg;
        }
        catch (Exception ex) { Services.CrashLog.Report(ex, "编辑器主题-正文底色"); }
        try
        {
            _popupBorder.Background = TryBrush("Ant.Surface", 255, 255, 255);
            _popupBorder.BorderBrush = TryBrush("Ant.Border", 205, 212, 220);
            _hintBorder.Background = TryBrush("Ant.Surface", 255, 255, 255);
            _hintBorder.BorderBrush = TryBrush("Ant.Border", 205, 212, 220);
            // 参数提示文字也随主题显式设色，避免任何主题下不可见
            _hintText.Foreground = TryBrush("Ant.Text", 31, 36, 48);
        }
        catch (Exception ex) { Services.CrashLog.Report(ex, "编辑器主题-弹层"); }
        // 富文本内核的默认字符格式同步新主题：之后新输入的文字颜色立即正确
        try
        {
            if (_re.Document is { } doc)
            {
                var fmt = doc.GetRange(0, 0).CharacterFormat;
                fmt.ForegroundColor = _baseFg;
                doc.SetDefaultCharacterFormat(fmt);
            }
        }
        catch { }
        try { HideHint(); } catch { }   // 参数提示随主题复位，下次输入重新弹出
        try { HidePopup(); } catch { }  // 弹层状态整体复位，下次输入重新弹出
        try
        {
            _gutterKey = "";        // 行号栏按新主题强制重绘
            RedrawGutter();
        }
        catch (Exception ex) { Services.CrashLog.Report(ex, "编辑器主题-行号栏"); }
        try
        {
            RenderMinimap(true);    // 小地图随主题重绘（含底色直涂，见 RenderMinimap）
            UpdateScrollBar();      // 滑条随主题直涂换色（Ant.ScrollThumb[Hover]）
        }
        catch (Exception ex) { Services.CrashLog.Report(ex, "编辑器主题-小地图/滚动条"); }
        try { Recolor(); }              // 当场同步重墨：不等 220ms 防抖，切象即净（含全背景复位）
        catch (Exception ex) { Services.CrashLog.Report(ex, "编辑器主题-重墨"); }
        ScheduleRecolor();      // 独立排队重着色（Recolor 幂等，重复无害）
    }

    /// <summary>把键盘焦点还给编辑器：菜单操作（如切换主题）后焦点常留在菜单栏，
    /// 编辑器收不到按键，表现为"打字没反应、智能提示失效"，主题应用后主动叫回。</summary>
    public void RestoreFocus() => FocusEd();

    void OnSelChanged(object? s, object e)
    {
        if (!_accepting) HidePopup();
        // 文本变化刚刷新过提示时，同一按键紧跟的选区事件不算"光标移走"；
        // 真正的光标移动（方向键/点击）没有这个标记 → 收起提示
        if (_hintKeep) _hintKeep = false; else HideHint();
        StatusChanged?.Invoke(this, EventArgs.Empty);
        RedrawGutter();
        UpdateBracketMatch();   // 光标移动后刷新括号匹配（滚动路径不刷，见 RedrawGutter）
    }
    bool _hintKeep;
    void OnSelChanged(object sender, SelectionChangedEventArgs e) => OnSelChanged(sender, (object)e);
    // WinUI 1.5 的 RichEditBox 选区接口没有变化事件：弹层收起与状态刷新
    // 由文本变化、键盘事件与失焦兜底驱动（OnTextChanged/OnKeyUp/OnLostFocus）。
    void OnLostFocus(object? s, RoutedEventArgs e) { if (!_accepting) HidePopup(); HideHint(); }
    void OnKeyUp(object? s, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Control) _ctrlDown = false;
        if (e.Key == Windows.System.VirtualKey.Shift) _shiftDown = false;
        RedrawGutter();
    }

    // ---------- 主题取色（键缺失时给保底色，不让启动失败） ----------

    static SolidColorBrush TryBrush(string key, byte r, byte g, byte b)
    {
        var c = TryColor(key, r, g, b);
        return new SolidColorBrush(c);
    }

    static Windows.UI.Color TryColor(string key, byte r, byte g, byte b)
    {
        // 1.0.9 真机加固：陶瓷渐变换装后，应用级合并链对渐变键的解析在部分真机上
        // 失灵（1.0.7/1.0.8 真机均复现：行号栏/小地图退保底白）。现在应用级查不到
        // 或类型不符时，再直连 ThemeService 当前主题字典本身查一次——字典是 Swap
        // 刚合并的原对象，不经过合并链解析，真机表现以它为准。
        if (Application.Current.Resources.TryGetValue(key, out var v) && TryColorValue(v, r, g, b, out var hit))
            return hit;
        try
        {
            var cur = Services.ThemeService.CurrentDictionary;
            if (cur is not null && cur is ResourceDictionary dict && dict.TryGetValue(key, out var v2)
                && TryColorValue(v2, r, g, b, out var hit2))
                return hit2;
        }
        catch { /* 直连兜底失败，走保底色 */ }
        return Windows.UI.Color.FromArgb(255, r, g, b);
    }

    /// <summary>从资源值提取颜色：纯色/颜色值/任意渐变（取 0.55 停止点主体帧）。</summary>
    static bool TryColorValue(object? v, byte r, byte g, byte b, out Windows.UI.Color color)
    {
        color = Windows.UI.Color.FromArgb(255, r, g, b);
        if (v is SolidColorBrush sc) { color = sc.Color; return true; }
        if (v is Windows.UI.Color c) { color = c; return true; }
        // 陶瓷渐变键（ThemeService.ApplyCeramic）：取 0.55 停止点主体帧。
        // 1.0.9 放宽到 GradientBrush 基类——真机上按精确类型 LinearGradientBrush
        // 匹配失灵（回归线：1.0.5 修复、1.0.6 陶瓷后复发），基类拦截任何渐变实体。
        // 命名注意：渐变变量不得叫 g——与颜色分量参数 byte g 撞名（CS0841/CS0136）。
        if (v is Microsoft.UI.Xaml.Media.GradientBrush grad)
        {
            var stop = grad.GradientStops.OrderBy(s => Math.Abs(s.Offset - 0.55)).FirstOrDefault();
            if (stop is not null) { color = stop.Color; return true; }
        }
        return false;
    }

    // ---------- 行号栏 ----------

    /// <summary>重绘行号栏：只画可见行，光标行加亮；状态没变时直接跳过。</summary>
    void RedrawGutter()
    {
        try
        {
            // 自动换行下视觉行与逻辑行不对应，行号会错位：暂时隐藏行号栏
            if (WordWrap || !ShowLineNumbers) { _gutter.Visibility = Visibility.Collapsed; return; }
            _gutter.Visibility = Visibility.Visible;

            // 滚动热路径（拖动滚动条时每帧进入）：一律用缓存文本 _lastRaw，
            // 绝不实时读内核文档（COM 调用），更不写文档——拖动滚动条闪退的根因
            var t = _lastRaw;
            int total = 1;
            foreach (var c in t) if (c == '\n') total++;

            // 折叠区间缓存：文本变化才重算（折叠态下不重算，标记只画锚点行）
            if (!FoldActive) EnsureFolds();

            double fs = BaseFontSize * _zoom;
            double lineH = fs * 1.4;                       // 与智能提示定位同一估算口径
            var scroll = _rich ? _reScroll : _tbScroll;
            int first = scroll is null ? 0 : (int)Math.Floor(scroll.VerticalOffset / lineH);
            int visible = scroll is null ? 30 : (int)Math.Ceiling(scroll.ViewportHeight / lineH) + 2;
            int cur = CaretLC(t).line;

            // 指纹比对：首行/光标行/总行数/折叠态没变就不重画（滚动微抖也不闪）
            var key = $"{first}|{cur}|{total}|{_zoom}|{RenderSize.Height}|{Bookmarks.Count}|{_hidden.Count}|{_folds.Count}";
            if (key == _gutterKey && _gutter.Children.Count > 0) return;
            _gutterKey = key;

            int digits = Math.Max(2, total.ToString().Length);
            _gutterWidth = digits * fs * 0.62 + 20;
            _gutter.Width = _gutterWidth;
            ColumnDefinitions[0].Width = new GridLength(_gutterWidth);
            // 1.0.9：Ant.GutterBg 专属键——Ant.Surface 被陶瓷渐变换装后真机读取
            // 失灵退保底白，行号栏停首主题白（1.0.7/1.0.8 真机复现）。
            _gutter.Background = TryBrush("Ant.GutterBg", 239, 239, 239);
            var dim = TryColor("Ant.SubText", 150, 156, 165);
            var hi = TryColor("Ant.TokKeyword", 166, 74, 62);

            _gutter.Children.Clear();
            for (int i = first; i < first + visible && i < total; i++)
            {
                bool isCur = i == cur;
                var tb = new TextBlock
                {
                    Text = (i + 1).ToString(),
                    FontFamily = new FontFamily("Consolas"),
                    FontSize = fs,
                    Width = _gutterWidth - 14,
                    TextAlignment = TextAlignment.Right,
                    Foreground = new SolidColorBrush(isCur ? hi : dim),
                    FontWeight = isCur ? Microsoft.UI.Text.FontWeights.Bold : Microsoft.UI.Text.FontWeights.Normal,
                };
                Canvas.SetTop(tb, (i - first) * lineH + (lineH - fs * 1.3) / 2);
                Canvas.SetLeft(tb, 0);
                _gutter.Children.Add(tb);

                if (Bookmarks.Contains(i + 1))   // 书签：行号左侧朱红圆点
                {
                    var dot = new Ellipse
                    {
                        Width = 7, Height = 7,
                        Fill = new SolidColorBrush(TryColor("Ant.TokKeyword", 166, 74, 62)),
                    };
                    Canvas.SetLeft(dot, 4);
                    Canvas.SetTop(dot, (i - first) * lineH + (lineH - 7) / 2);
                    _gutter.Children.Add(dot);
                }

                // 折叠标记：行号右侧 +/-（折叠态只画锚点行的 +）
                if (!WordWrap && ShowLineNumbers && FoldEngine.Supports(_lang.Id))
                {
                    bool? collapsedHere = FoldActive ? (i == _hidden[0].StartLine0 ? true : null)
                                                     : _folds.Any(f => f.StartLine == i && f.EndLine > f.StartLine) ? false : null;
                    if (collapsedHere is bool on)
                    {
                        var mk = new TextBlock
                        {
                            Text = on ? "+" : "-",
                            FontFamily = new FontFamily("Consolas"),
                            FontSize = Math.Max(10, fs - 2),
                            Foreground = new SolidColorBrush(hi),
                        };
                        Canvas.SetLeft(mk, Math.Max(2, _gutterWidth - 12));
                        Canvas.SetTop(mk, (i - first) * lineH + (lineH - fs * 1.3) / 2);
                        _gutter.Children.Add(mk);
                    }
                }
            }

            // 括号匹配高亮只在光标移动（OnSelChanged）与重着色（Recolor）后刷新，
            // 不随滚动刷新：滚动不需要它，而它要写文档格式，不该进滚动热路径
        }
        catch { /* 行号栏任何异常都不影响编辑 */ }
    }

    // ================= 小地图 =================

    /// <summary>文本变化后防抖重绘小地图（编辑密集时避免每键重画）。</summary>
    void ScheduleMinimap()
    {
        if (!ShowMinimap) return;
        try
        {
            _miniTimer ??= DispatcherQueue.CreateTimer();
            _miniTimer.Interval = TimeSpan.FromMilliseconds(300);
            _miniTimer.Stop();
            _miniTimer.Tick -= MiniTimerTick;
            _miniTimer.Tick += MiniTimerTick;
            _miniTimer.Start();
        }
        catch { /* 小地图失败不影响编辑 */ }
    }

    void MiniTimerTick(object? s, object e)
    {
        if (_miniTimer is not null) _miniTimer.Stop();
        RenderMinimap(true);
    }

    /// <summary>整体重绘小地图行条；force 时忽略指纹。</summary>
    void RenderMinimap(bool force)
    {
        try
        {
            bool show = ShowMinimap && !WordWrap;
            _minimap.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
            ColumnDefinitions[2].Width = show ? new GridLength(MiniWidth) : new GridLength(0);
            if (!show) return;

            // 小地图底色随主题直涂：此前只在构造时设过一次，切主题后不更新——
            // 墨夜里变过的底色切回浅主题仍留深底，真机表现为"右缘一条黑带不跟主题"。
            // 每次重绘都从当前象取 Ant.GutterBg（本方法在主题切换时被 force 重入）。
            // 1.0.9：改走专属键——Ant.Surface 被陶瓷渐变换装后真机读取失灵退保底白，
            // 小地图停首主题白（1.0.7/1.0.8 真机复现，截图像素定案）。
            _minimap.Background = TryBrush("Ant.GutterBg", 239, 239, 239);
            // 视口矩形同走滚动条字典：三象下浅/深自动可辨，不再硬编码蓝色
            var vp = TryColor("Ant.ScrollThumb", 84, 118, 168);
            _miniView.Background = new SolidColorBrush(Windows.UI.Color.FromArgb(92, vp.R, vp.G, vp.B));

            var t = _lastRaw;   // 缓存文本：不实时读内核文档
            int total = 1;
            foreach (var c in t) if (c == '\n') total++;

            // 指纹：文本规模或高度变化才重画
            var key = $"{t.Length}|{total}|{RenderSize.Height:0}";
            if (!force && key == _minimapKey && _minimap.Children.Count > 0) { UpdateMiniViewport(); return; }
            _minimapKey = key;

            double h = RenderSize.Height;
            if (h < 10) return;
            int maxRows = Math.Max(20, (int)(h / MiniLineH));
            int step = Math.Max(1, (total + maxRows - 1) / maxRows);   // 降采样聚合
            var barColor = Windows.UI.Color.FromArgb(120, 130, 140, 155);
            var cmtColor = Windows.UI.Color.FromArgb(70, 130, 140, 155);

            _minimap.Children.Clear();
            int agg = 0; int width = 0; bool comment = false;
            var lines = t.Split('\n');
            for (int i = 0; i < lines.Length; i++)
            {
                var line = lines[i];
                agg++;
                width = Math.Max(width, line.Length);
                var tr = line.TrimStart();
                if (agg == 1) comment = tr.Length > 0 && (tr.StartsWith("//") || tr.StartsWith("#") || tr.StartsWith("--") || tr.StartsWith("/*"));

                if (agg == step || i == lines.Length - 1)
                {
                    if (width > 0)
                    {
                        var bar = new Microsoft.UI.Xaml.Shapes.Rectangle
                        {
                            Height = Math.Max(1.0, MiniLineH - 0.5),
                            Width = Math.Min(MiniWidth - 8, width * 1.05),
                            Fill = new SolidColorBrush(comment ? cmtColor : barColor),
                            RadiusX = 1, RadiusY = 1,
                        };
                        Canvas.SetLeft(bar, 4);
                        Canvas.SetTop(bar, (i / step) * MiniLineH + 0.5);
                        _minimap.Children.Add(bar);
                    }
                    agg = 0; width = 0; comment = false;
                }
            }
            _minimap.Children.Add(_miniView);
            UpdateMiniViewport();
        }
        catch { /* 小地图任何异常不影响编辑 */ }
    }

    /// <summary>轻量更新：只挪视口矩形，不重画行条。</summary>
    void UpdateMiniViewport()
    {
        try
        {
            if (!ShowMinimap || WordWrap) return;
            var t = _lastRaw;   // 缓存文本：滚动热路径不实时读内核文档
            int total = 1;
            foreach (var c in t) if (c == '\n') total++;
            var scroll = _rich ? _reScroll : _tbScroll;
            if (scroll is null || scroll.ScrollableHeight <= 0 || _minimap.Children.Count == 0)
            {
                _miniView.Visibility = Visibility.Collapsed;
                return;
            }
            double miniH = Math.Min(RenderSize.Height, total * MiniLineH);
            double y = scroll.VerticalOffset / (scroll.ScrollableHeight + scroll.ViewportHeight) * miniH;
            double vh = Math.Max(8, scroll.ViewportHeight / (scroll.ScrollableHeight + scroll.ViewportHeight) * miniH);
            _miniView.Height = vh; _miniView.Width = MiniWidth - 2;
            Canvas.SetLeft(_miniView, 1);
            Canvas.SetTop(_miniView, y);
            _miniView.Visibility = Visibility.Visible;
        }
        catch { }
    }

    void OnMiniPointer(object sender, PointerRoutedEventArgs e)
    {
        try
        {
            var pt = e.GetCurrentPoint(_minimap);
            if (pt.Properties.IsLeftButtonPressed)
            {
                if (!_miniDragging)
                {
                    _miniDragging = true;
                    _minimap.CapturePointer(e.Pointer);
                }
                double ratio = pt.Position.Y / Math.Max(1, _minimap.ActualHeight);
                var t = RawText;
                int total = 1;
                foreach (var c in t) if (c == '\n') total++;
                int line = (int)(ratio * total);
                GoToLine(Math.Clamp(line + 1, 1, total));
                UpdateMiniViewport();
            }
            else if (_miniDragging)
            {
                _miniDragging = false;
                _minimap.ReleasePointerCapture(e.Pointer);
            }
        }
        catch { }
    }

    static ScrollViewer? FindScroll(DependencyObject root)
    {
        if (root is ScrollViewer sv) return sv;
        int n = VisualTreeHelper.GetChildrenCount(root);
        for (int i = 0; i < n; i++)
        {
            var r = FindScroll(VisualTreeHelper.GetChild(root, i));
            if (r is not null) return r;
        }
        return null;
    }

    // ---------- 滚动条（VSCode 风，几何全在 ScrollBarMath，万链在测） ----------

    ScrollViewer? ActiveScroll => _rich ? _reScroll : _tbScroll;

    /// <summary>滑条颜色直涂：常态/悬停两键均出自当前主题字典（Ant.ScrollThumb[Hover]）。</summary>
    Brush SbFill()
    {
        bool active = _sbHover || _sbDragging;
        string key = active ? "Ant.ScrollThumbHover" : "Ant.ScrollThumb";
        if (Application.Current.Resources.TryGetValue(key, out var v) && v is SolidColorBrush sc)
            return sc;
        return new SolidColorBrush(Windows.UI.Color.FromArgb(
            active ? (byte)0x99 : (byte)0x66, 0x1C, 0x24, 0x2C));
    }

    /// <summary>滚动条整体刷新：按当前内核的溢出量定显隐，几何交 ScrollBarMath，
    /// 宽度/颜色随悬停与拖拽态切换。内核未就绪/不溢出时整条隐藏（不挡选区）。</summary>
    void UpdateScrollBar()
    {
        try
        {
            var s = ActiveScroll;
            if (s is null || s.ScrollableHeight <= 0 || _sbTrack.ActualHeight < 40)
            {
                _sbTrack.Visibility = Visibility.Collapsed;
                return;
            }
            _sbTrack.Visibility = Visibility.Visible;
            var (len, pos) = Services.ScrollBarMath.Compute(
                _sbTrack.ActualHeight, s.ExtentHeight, s.ViewportHeight, s.VerticalOffset);
            if (len <= 0)
            {
                _sbThumb.Visibility = Visibility.Collapsed;
                return;
            }
            _sbThumb.Visibility = Visibility.Visible;
            bool wide = _sbHover || _sbDragging;
            _sbThumb.Width = wide ? SbThumbWide : SbThumbThin;
            _sbThumb.CornerRadius = new CornerRadius(wide ? SbThumbWide / 2 : 1.5);
            _sbThumb.Margin = new Thickness(0, pos, wide ? 0 : 1, 0);   // 细条留 1px 右缝
            _sbThumb.Background = SbFill();
            _sbThumb.Height = len;
        }
        catch { /* 滚动条失败不影响编辑 */ }
    }

    void OnSbPointerEnter(object sender, PointerRoutedEventArgs e)
    {
        _sbHover = true;
        UpdateScrollBar();
    }

    void OnSbPointerExit(object sender, PointerRoutedEventArgs e)
    {
        if (_sbDragging) return;   // 拖拽出界不收条，松手再算
        _sbHover = false;
        UpdateScrollBar();
    }

    void OnSbPointerPressed(object sender, PointerRoutedEventArgs e)
    {
        try
        {
            var s = ActiveScroll;
            if (s is null || s.ScrollableHeight <= 0) return;
            double y = e.GetCurrentPoint(_sbTrack).Position.Y;
            var (len, pos) = Services.ScrollBarMath.Compute(
                _sbTrack.ActualHeight, s.ExtentHeight, s.ViewportHeight, s.VerticalOffset);
            _sbDragging = true;
            _sbDragStartY = y;
            _sbDragStartOffset = s.VerticalOffset;
            if (y < pos || y > pos + len)
            {
                // 点在轨道上：先向点击方向翻一屏（VSCode 手感），再进入拖拽
                double dir = y < pos ? -1 : 1;
                _sbDragStartOffset = Math.Max(0, Math.Min(s.ScrollableHeight,
                    s.VerticalOffset + dir * s.ViewportHeight * 0.9));
                s.ChangeView(null, _sbDragStartOffset, null, true);
            }
            _sbTrack.CapturePointer(e.Pointer);
            UpdateScrollBar();
        }
        catch { /* 命中失败退回内核默认行为 */ }
    }

    void OnSbPointerMove(object sender, PointerRoutedEventArgs e)
    {
        if (!_sbDragging) return;
        try
        {
            var s = ActiveScroll;
            if (s is null || s.ScrollableHeight <= 0) return;
            var (len, _) = Services.ScrollBarMath.Compute(
                _sbTrack.ActualHeight, s.ExtentHeight, s.ViewportHeight, s.VerticalOffset);
            double track = Math.Max(1, _sbTrack.ActualHeight - len);
            double y = e.GetCurrentPoint(_sbTrack).Position.Y;
            double off = _sbDragStartOffset + (y - _sbDragStartY) * (s.ScrollableHeight / track);
            s.ChangeView(null, Math.Max(0, Math.Min(s.ScrollableHeight, off)), null, true);
            UpdateScrollBar();
        }
        catch { /* 拖拽失败不影响编辑 */ }
    }

    void OnSbPointerRelease(object sender, PointerRoutedEventArgs e)
    {
        if (!_sbDragging) return;
        _sbDragging = false;
        try { _sbTrack.ReleasePointerCapture(e.Pointer); } catch { }
        try
        {
            // 松手时指针若已离轨，悬停态一并收掉
            var p = e.GetCurrentPoint(_sbTrack).Position;
            _sbHover = p.Y >= 0 && p.Y <= _sbTrack.ActualHeight && p.X >= 0 && p.X <= SbTrackWidth;
        }
        catch { _sbHover = false; }
        UpdateScrollBar();
    }

    // ---------- 括号匹配高亮（仅着色内核） ----------

    List<TokenSpan>? _toks;      // 最近一次着色的分词结果（恢复颜色用）
    int _hlA = -1, _hlB = -1;    // 当前高亮的括号位置

    /// <summary>光标旁是括号时，高亮它的配对括号；找不配就全部熄灭。</summary>
    void UpdateBracketMatch()
    {
        try
        {
            if (!_rich || _re.Document is not { } doc) return;
            var text = RawText;
            if (text != _lastColorText || _toks is null) return;   // 分词不新鲜时不显示，避免恢复错色

            int caret = Math.Min(SelPos, text.Length);
            const string open = "([{", close = ")]}";
            char At(int p) => p >= 0 && p < text.Length ? text[p] : '\0';

            int self = -1;
            if (open.IndexOf(At(caret - 1)) >= 0 || close.IndexOf(At(caret - 1)) >= 0) self = caret - 1;
            else if (open.IndexOf(At(caret)) >= 0 || close.IndexOf(At(caret)) >= 0) self = caret;
            if (self < 0) { ClearBracketHi(); return; }

            int m = FindMatch(text, self);
            if (m < 0) { ClearBracketHi(); return; }
            if (_hlA == self && _hlB == m) return;   // 没变不重画

            ClearBracketHi();
            ApplyBracketHi(self);
            ApplyBracketHi(m);
            _hlA = self; _hlB = m;
        }
        catch { /* 括号高亮失败不影响编辑 */ }
    }

    /// <summary>给定括号位置，返回配对括号位置；不配对返回 -1（限 1 万字符搜索范围）。</summary>
    static int FindMatch(string text, int p)
    {
        const string open = "([{", close = ")]}";
        char c = text[p];
        int oi = open.IndexOf(c), ci = close.IndexOf(c);
        if (oi >= 0)
        {
            int d = 0;
            for (int i = p; i < text.Length && i - p < 10000; i++)
            {
                if (text[i] == open[oi]) d++;
                else if (text[i] == close[oi] && --d == 0) return i;
            }
        }
        else if (ci >= 0)
        {
            int d = 0;
            for (int i = p; i >= 0 && p - i < 10000; i--)
            {
                if (text[i] == close[ci]) d++;
                else if (text[i] == open[ci] && --d == 0) return i;
            }
        }
        return -1;
    }

    void ApplyBracketHi(int p)
    {
        if (_re.Document is not { } doc) return;
        // GetRange 两参是"起点, 终点"（官方 ITextDocument 语义）：单字符区间是 (p, p+1)
        var f = doc.GetRange(p, p + 1).CharacterFormat;
        // 只换文字颜色，不再碰背景色/加粗：背景与加粗都会被内核插入继承，
        // 是"从括号开始所有内容都有背景色/变黑"一整类问题的根源
        f.ForegroundColor = BracketHiFg;
    }

    /// <summary>配对括号高亮文字色（醒目橙红，白底深底都可见）。</summary>
    static readonly Windows.UI.Color BracketHiFg = Windows.UI.Color.FromArgb(255, 204, 82, 0);

    void ClearBracketHi()
    {
        if (_hlA < 0) return;
        try
        {
            if (_re.Document is not { } doc) return;
            foreach (var p in new[] { _hlA, _hlB })
            {
                if (p < 0) continue;
                var f = doc.GetRange(p, p + 1).CharacterFormat;
                f.ForegroundColor = TokenColor(TokenAt(p));
            }
        }
        catch { }
        _hlA = _hlB = -1;
    }

    TokKind TokenAt(int p)
    {
        if (_toks is not null)
            foreach (var t in _toks)
                if (p >= t.Start && p < t.Start + t.Length) return t.Kind;
        return TokKind.Text;
    }

    // ---------- 书签（1 计行号；上方增删行后位置会漂移，属已知限制） ----------

    public HashSet<int> Bookmarks { get; } = new();

    /// <summary>Ctrl+F2：在光标行打/取消书签。</summary>
    public void ToggleBookmark()
    {
        int l = CaretLC().line + 1;
        if (!Bookmarks.Remove(l)) Bookmarks.Add(l);
        _gutterKey = "";
        RedrawGutter();
    }

    /// <summary>F2：跳到下一个书签（到底回绕）；无书签返回 false。</summary>
    public bool NextBookmark()
    {
        if (Bookmarks.Count == 0) return false;
        int cur = CaretLC().line + 1;
        int next = Bookmarks.Where(b => b > cur).DefaultIfEmpty(Bookmarks.Min()).Min();
        return JumpBookmark(next);
    }

    /// <summary>Shift+F2：跳到上一个书签（到头回绕）。</summary>
    public bool PrevBookmark()
    {
        if (Bookmarks.Count == 0) return false;
        int cur = CaretLC().line + 1;
        int prev = Bookmarks.Where(b => b < cur).DefaultIfEmpty(Bookmarks.Max()).Max();
        return JumpBookmark(prev);
    }

    bool JumpBookmark(int line)
    {
        var (s, _) = LineSpan(line);
        FocusEd();
        Sel(s, 0);
        return true;
    }

    /// <summary>Ctrl+\：光标在括号旁或括号内时，跳到配对括号。</summary>
    public void GotoMatchingBracket()
    {
        try
        {
            var text = RawText;
            int caret = Math.Min(SelPos, text.Length);
            const string open = "([{", close = ")]}";
            char At(int p) => p >= 0 && p < text.Length ? text[p] : '\0';
            int self = -1;
            if (open.IndexOf(At(caret - 1)) >= 0 || close.IndexOf(At(caret - 1)) >= 0) self = caret - 1;
            else if (open.IndexOf(At(caret)) >= 0 || close.IndexOf(At(caret)) >= 0) self = caret;
            else
            {
                // 光标在括号对内部：向前找最近的未配对左括号
                for (int i = caret - 1; i >= 0 && caret - i < 5000; i--)
                    if (open.IndexOf(At(i)) >= 0) { self = i; break; }
            }
            if (self < 0) return;
            int m = FindMatch(text, self);
            if (m < 0) return;
            Sel(m, 0);
        }
        catch { }
    }

    // ---------- 代码折叠 ----------
    // 原则：折叠绝不能弄丢内容。隐藏的行连同锚点行原文一起保存，展开时按锚点原样插回；
    // 折叠期间任何会改文本的按键/粘贴/撤销，先自动展开再执行，宁可少折叠一秒也不丢代码。

    /// <summary>当前文本的折叠区间缓存（未折叠态；折叠态下标记只画锚点行，不重算）。</summary>
    void EnsureFolds()
    {
        if (WordWrap || !FoldEngine.Supports(_lang.Id)) { _folds.Clear(); _foldsKey = ""; return; }
        var t = _lastRaw;   // 缓存文本：折叠计算不实时读内核文档
        var key = $"{t.Length}:{t.GetHashCode()}";
        if (key == _foldsKey) return;
        _foldsKey = key;
        _folds = FoldEngine.Compute(t, _lang.Id);
    }

    /// <summary>清空折叠状态（换文件/换语言/换内核/自动换行时调用）。</summary>
    void ClearFolds()
    {
        if (_hidden.Count == 0 && _folds.Count == 0 && _foldsKey.Length == 0) return;
        _hidden.Clear();
        _foldFull = "";
        _folds.Clear();
        _foldsKey = "";
        _gutterKey = "";
    }

    void OnGutterPressed(object s, PointerRoutedEventArgs e)
    {
        try
        {
            if (WordWrap || !ShowLineNumbers) return;
            var p = e.GetCurrentPoint(_gutter).Position;
            double fs = BaseFontSize * _zoom;
            double lineH = fs * 1.4;
            var scroll = _rich ? _reScroll : _tbScroll;
            int first = scroll is null ? 0 : (int)Math.Floor(scroll.VerticalOffset / lineH);
            int line = first + (int)Math.Max(0, p.Y / lineH);

            if (FoldActive)
            {
                if (line == _hidden[0].StartLine0) { ExpandAll(); e.Handled = true; }
                return;
            }
            if (!FoldEngine.Supports(_lang.Id)) return;
            EnsureFolds();
            var r = _folds.FirstOrDefault(f => f.StartLine == line && f.EndLine > f.StartLine);
            if (r is null) return;
            CollapseRange(r);
            e.Handled = true;
        }
        catch { /* 折叠交互失败不影响编辑 */ }
    }

    /// <summary>折叠一个区间：隐藏内部行，锚点行保留。已有折叠先展开（保证一次一个，往返可靠）。</summary>
    void CollapseRange(FoldRange r)
    {
        if (FoldActive) ExpandAll();
        var t = RawText;
        if (r.EndLine <= r.StartLine) return;
        var (folded, anchor, hidden) = FoldEngine.Collapse(t, r.StartLine, r.EndLine);
        if (hidden.Length == 0) return;
        int caret = Math.Min(SelPos, folded.Length);
        _foldFull = t;
        _hidden.Add(new HiddenBlock { Anchor = anchor, Lines = hidden.ToList(), StartLine0 = r.StartLine });
        SetRawSafe(folded);
        _folds.Clear();
        _foldsKey = "";
        _gutterKey = "";
        Sel(Math.Min(caret, folded.Length), 0);
        ScheduleRecolor();
        RedrawGutter();
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>展开：隐藏行按锚点原样插回；光标回到锚点行尾。</summary>
    public void ExpandAll()
    {
        if (!FoldActive) return;
        var blk = _hidden[0];
        var (ok, full) = FoldEngine.Expand(RawText, blk.Anchor, blk.Lines);
        _hidden.Clear();
        _foldFull = "";
        _folds.Clear();
        _foldsKey = "";
        _gutterKey = "";
        if (ok)
        {
            SetRawSafe(full);
            int target = Math.Min(SelPos, full.Length);
            try { var (s, e2) = LineSpan(blk.StartLine0 + 1); target = e2; } catch { }
            Sel(Math.Min(target, full.Length), 0);
        }
        ScheduleRecolor();
        RedrawGutter();
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>程序化安全改文本：屏蔽事件重入，同步伪事件基线。</summary>
    void SetRawSafe(string s)
    {
        _syncing = true;
        try { RawText = s; }
        finally { _syncing = false; }
        _lastRaw = RawText;
    }

    /// <summary>
    /// 折叠期间的兜底：极少数绕过按键拦截的修改（如输入法提交）落进折叠视图时，
    /// 按锚点把隐藏行插回来；锚点找不到（被改/删）则整体回退到折叠前全文，绝不丢内容。
    /// </summary>
    void ReconcileFolded()
    {
        try
        {
            if (!FoldActive) return;
            var blk = _hidden[0];
            var (ok, full) = FoldEngine.Expand(RawText, blk.Anchor, blk.Lines);
            if (!ok) full = _foldFull;
            _hidden.Clear();
            _foldFull = "";
            _folds.Clear();
            _foldsKey = "";
            _gutterKey = "";
            SetRawSafe(full);
            Sel(Math.Min(SelPos, full.Length), 0);
            ScheduleRecolor();
            RedrawGutter();
        }
        catch { /* 兜底失败不影响后续编辑 */ }
    }

    /// <summary>折叠期间按键的修改保护：非导航键先自动展开，再让按键正常处理。</summary>
    void FoldGuardKeyDown(KeyRoutedEventArgs e)
    {
        if (!FoldActive) return;
        switch (e.Key)
        {
            case Windows.System.VirtualKey.Up:
            case Windows.System.VirtualKey.Down:
            case Windows.System.VirtualKey.Left:
            case Windows.System.VirtualKey.Right:
            case Windows.System.VirtualKey.Home:
            case Windows.System.VirtualKey.End:
            case Windows.System.VirtualKey.PageUp:
            case Windows.System.VirtualKey.PageDown:
            case Windows.System.VirtualKey.Escape:
            case Windows.System.VirtualKey.Shift:
            case Windows.System.VirtualKey.Control:
            case Windows.System.VirtualKey.Menu:
                return;                                          // 纯导航/修饰键：放行
            case Windows.System.VirtualKey.C:
            case Windows.System.VirtualKey.A:
            case Windows.System.VirtualKey.F2:
                if (_ctrlDown || e.Key == Windows.System.VirtualKey.F2) return;   // 复制/全选/书签：不改文本
                break;
        }
        ExpandAll();
    }

    // ================= 内核适配层 =================

    /// <summary>当前内核的规范文本（换行统一为单字符，与内部偏移一一对应）。</summary>
    string RawText
    {
        get
        {
            if (!_rich) return (_tb.Text ?? "").Replace("\r\n", "\n").Replace('\r', '\n');
            try
            {
                if (_re.Document is not { } doc) return "";
                doc.GetText(TextGetOptions.None, out var raw);
                return (raw ?? "").Replace("\r\n", "\n").Replace('\r', '\n');
            }
            catch { return ""; }
        }
        set
        {
            if (!_rich) { _tb.Text = value ?? ""; return; }
            // 红1修复：写入前强制同步收敛——挂起的着色回调若不收敛，
            // 220ms Tick 的批量 GetRange 与下面的整篇 SetText 会在内核中交叠
            ConvergeRecolor();
            // 复位永远先行：写入中途失败也保证下次按当前文本重新着色
            // （失败场景多一次幂等重涂，无害；漏复位则新文本永远不上色）
            _lastColorText = "";
            try
            {
                if (_re.Document is not { } doc) return;
                // Begin/End 必须成对走 finally：SetText 半途抛出时若组没关，
                // 之后每次 BeginUndoGroup 都失败——注释/格式化等全部文本命令
                // 会被 catch 静默吞掉，表现为"快捷键点了没反应"
                doc.BeginUndoGroup();
                try { doc.SetText(TextSetOptions.None, value ?? ""); }
                finally { doc.EndUndoGroup(); }
                // 收敛时停掉了原来的回调，这里统一重排一次重着色，语义不变
                ScheduleRecolor();
            }
            catch (Exception ex) { Services.CrashLog.Report(ex, "编辑器-整篇写入"); } // 黄2：不再静默
        }
    }

    /// <summary>对外文本：按文档换行风格输出（保存时还原原始换行符）。</summary>
    string OutputEol { get; set; } = "\r\n";

    int SelPos => _rich
        ? (int)(_re.Document?.Selection?.StartPosition ?? 0)
        : _tb.SelectionStart;

    int SelLen => _rich
        ? (int)((_re.Document?.Selection?.EndPosition ?? 0) - (_re.Document?.Selection?.StartPosition ?? 0))
        : _tb.SelectionLength;

    string SelTextRaw
    {
        get
        {
            if (!_rich) return _tb.SelectedText;
            var s = _re.Document?.Selection?.Text ?? "";
            return s.Replace("\r\n", "\n").Replace('\r', '\n');
        }
        set
        {
            if (!_rich) { _tb.SelectedText = value ?? ""; return; }
            var sel = _re.Document?.Selection;
            if (sel is not null) sel.Text = value ?? "";
        }
    }

    void Sel(int start, int len)
    {
        if (_rich)
        {
            if (_re.Document?.Selection is { } sel) sel.SetRange(start, start + len);
        }
        else _tb.Select(start, len);
    }

    void FocusEd() => (_rich ? (FrameworkElement)_re : _tb).Focus(FocusState.Programmatic);

    // ================= 内核切换 =================

    static bool UseRich(LangDef l) => l.Id is not ("plain" or "markdown");

    void SwitchCore(bool rich)
    {
        if (_rich == rich) return;
        string text = RawText;
        int caret = Math.Min(SelPos, text.Length);

        _rich = rich;
        ClearFolds();           // 换内核：折叠状态与隐藏块全部清空
        _tb.Visibility = rich ? Visibility.Collapsed : Visibility.Visible;
        _re.Visibility = rich ? Visibility.Visible : Visibility.Collapsed;
        UpdateScrollBar();      // 内核换了滚动区就换了，滑条立即跟手

        if (rich)
        {
            RawText = text;
            try
            {
                if (_re.Document is { } doc)
                {
                    var fmt = doc.GetRange(0, 0).CharacterFormat;
                    fmt.ForegroundColor = _baseFg;
                    fmt.Name = "Consolas";
                    fmt.Size = (float)(BaseFontSize * _zoom);
                    doc.SetDefaultCharacterFormat(fmt);
                }
            }
            catch { }
            ScheduleRecolor();
        }
        else
        {
            _tb.Text = text;
        }
        Sel(Math.Min(caret, RawText.Length), 0);
        FocusEd();
    }

    // ================= 公共属性 =================

    public string Text
    {
        get
        {
            var raw = RawText;
            return OutputEol == "\n" ? raw : raw.Replace("\n", OutputEol);
        }
        set
        {
            var v = value ?? "";
            // 记录文档换行风格（保存时还原）；文本内部统一为 \n
            int crlf = 0, lf = 0, cr = 0;
            for (int i = 0; i < v.Length; i++)
            {
                if (v[i] == '\r') { if (i + 1 < v.Length && v[i + 1] == '\n') { crlf++; i++; } else cr++; }
                else if (v[i] == '\n') lf++;
            }
            OutputEol = crlf > 0 && crlf * 2 >= lf ? "\r\n" : cr > 0 && cr > lf ? "\r" : "\n";

            _syncing = true;
            try { RawText = v.Replace("\r\n", "\n").Replace('\r', '\n'); }
            finally { _syncing = false; }
            _lastRaw = RawText; // 程序化改动后同步基线，后续伪事件才识别得出来
            ClearFolds();       // 换文档：折叠状态清空
            Sel(0, 0);
            HidePopup();
            ScheduleRecolor();
            _gutterKey = "";    // 换了文档，行号栏重绘
            RedrawGutter();
            Modified?.Invoke(this, EventArgs.Empty);
            StatusChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    public LangDef SyntaxLanguage
    {
        get => _lang;
        set
        {
            _lang = value ?? LangDef.Plain;
            ClearFolds();           // 换语言：折叠区间与折叠态重置
            SwitchCore(UseRich(_lang));
            ScheduleRecolor();
            HidePopup();
        }
    }

    /// <summary>只读模式：两个内核同时生效（大文件保护）。</summary>
    public bool IsReadOnly
    {
        get => _rich ? !_re.IsEnabled && _re.IsReadOnly : _tb.IsReadOnly;
        set { _tb.IsReadOnly = value; _re.IsReadOnly = value; }
    }

    public bool WordWrap
    {
        get
        {
            if (_rich) return _re.TextWrapping == TextWrapping.Wrap;
            return _tb.TextWrapping == TextWrapping.Wrap;
        }
        set
        {
            _tb.TextWrapping = value ? TextWrapping.Wrap : TextWrapping.NoWrap;
            _re.TextWrapping = value ? TextWrapping.Wrap : TextWrapping.NoWrap;
            ClearFolds();           // 换行模式下视觉行与逻辑行不对应：折叠状态清空
            _gutterKey = "";        // 换行模式切换后行号栏重估（换行时隐藏行号）
            RedrawGutter();
        }
    }

    public bool ShowLineNumbers { get; set; } = true;

    public double ZoomLevel => _zoom;

    public int CaretLine { get { var (l, _) = CaretLC(); return l + 1; } }
    public int CaretColumn { get { var (_, c) = CaretLC(); return c + 1; } }

    public int SelectionLength => SelLen;

    public int CharCount => RawText.Length;

    public int LineCount
    {
        get
        {
            var t = RawText;
            int n = 1;
            foreach (var ch in t) if (ch == '\n') n++;
            return n;
        }
    }

    public string SelectedText => SelTextRaw;

    // ================= 基础编辑 =================

    public void Insert(string text) => SelTextRaw = text ?? "";

    public void Cut() { CopyToClipboard(); SelTextRaw = ""; }
    public void Copy() => CopyToClipboard();

    void CopyToClipboard()
    {
        var text = SelTextRaw;
        if (text.Length == 0) return;
        try
        {
            var dp = new Windows.ApplicationModel.DataTransfer.DataPackage();
            dp.SetText(text);
            Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(dp);
        }
        catch
        {
            // 剪贴板被其他程序短暂锁定时复制失败即可，不闪退
        }
    }

    public async void Paste()
    {
        try
        {
            var dp = Windows.ApplicationModel.DataTransfer.Clipboard.GetContent();
            if (dp.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.Text))
            {
                var text = await dp.GetTextAsync();
                SelTextRaw = text.Replace("\r\n", "\n").Replace('\r', '\n');
            }
        }
        catch { /* 剪贴板不可用时忽略 */ }
    }

    public void SelectAll()
    {
        if (_rich) { if (_re.Document is { } doc) doc.Selection?.SetRange(0, RawText.Length); }
        else _tb.SelectAll();
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    public void Undo()
    {
        if (_rich) { try { if (_re.Document?.CanUndo() == true) { _re.Document.Undo(); MarkFormatsDirty(); } } catch { } }
        else if (_tb.CanUndo) _tb.Undo();
    }

    public void Redo()
    {
        if (_rich) { try { if (_re.Document?.CanRedo() == true) { _re.Document.Redo(); MarkFormatsDirty(); } } catch { } }
        else if (_tb.CanRedo) _tb.Redo();
    }

    /// <summary>撤销/重做会原样恢复字符格式（含旧主题背景色等历史格式），
    /// 而文本可能未变——Recolor 的幂等检查会因此跳过，旧底色残留
    /// 表现为"已编辑过的文本带高亮"。置脏强制下次重着色做全背景复位。</summary>
    void MarkFormatsDirty() { _lastColorText = ""; ScheduleRecolor(); }

    // ================= 行操作 =================

    (int start, int end) LineSpan(int line1Based)
    {
        var t = RawText;
        int line = 0, pos = 0;
        while (line < line1Based - 1 && pos < t.Length)
        {
            var nl = t.IndexOf('\n', pos);
            if (nl < 0) { pos = t.Length; break; }
            pos = nl + 1; line++;
        }
        int end = t.IndexOf('\n', pos);
        if (end < 0) end = t.Length;
        return (pos, end);
    }

    (int line, int col) CaretLC() => CaretLC(RawText);

    /// <summary>带文本入参的版本：滚动热路径传缓存文本，避免实时读内核文档。</summary>
    (int line, int col) CaretLC(string t)
    {
        int caret = Math.Min(SelPos, t.Length);
        int line = 0, lastNl = -1;
        for (int i = 0; i < caret; i++)
            if (t[i] == '\n') { line++; lastNl = i; }
        return (line, caret - lastNl - 1);
    }

    public void DeleteLine()
    {
        var (l0, _) = CaretLC();          // CaretLC 从 0 计行，LineSpan 按 1 计行
        var (s, e) = LineSpan(l0 + 1);
        if (e < RawText.Length) e++; // 连同换行符一起删
        Sel(s, e - s);
        SelTextRaw = "";
    }

    public void DuplicateLine()
    {
        var (l0, _) = CaretLC();
        var (s, e) = LineSpan(l0 + 1);
        var text = RawText[s..e];
        Sel(e, 0);
        SelTextRaw = "\n" + text;
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    public void MoveLine(int delta)
    {
        var (l0, _) = CaretLC();
        int l = l0 + 1;                    // 统一成 1 计行
        int target = l + delta;
        if (target < 1 || target > LineCount) return;
        var (s, e) = LineSpan(l);
        var text = RawText[s..e];
        if (delta > 0)
        {
            var (ns, ne) = LineSpan(l + 1);
            int neEnd = ne < RawText.Length ? ne + 1 : ne;
            Sel(s, neEnd - s);
            SelTextRaw = RawText[ns..ne] + "\n" + text;
            Sel(s + (ne - ns) + 1, 0);
        }
        else
        {
            var (ns, ne) = LineSpan(l - 1);
            int sEnd = e < RawText.Length ? e + 1 : e;
            Sel(ns, sEnd - ns);
            SelTextRaw = text + "\n" + RawText[ns..ne];
            Sel(ns, 0);
        }
    }

    public void TransformSelection(Func<string, string> f)
    {
        if (SelLen <= 0) return;
        var sel = SelTextRaw;
        SelTextRaw = f(sel);
    }

    public void GoToLine(int line1Based)
    {
        var (s, _) = LineSpan(line1Based);
        Sel(s, 0);
        FocusEd();
    }

    // ================= 注释 / 取消注释（VS 语义，标记按语言取） =================

    public void CommentSelection() => ToggleComment(comment: true);
    public void UncommentSelection() => ToggleComment(comment: false);

    void ToggleComment(bool comment)
    {
        try
        {
            var lang = _lang ?? LangDef.Plain;
            var text = RawText;
            if (text.Length == 0) return;

            // 受影响行：无选区=光标行；有选区=首行到尾行（与 VS 一致）
            int selStart = Math.Min(SelPos, text.Length);
            int selEnd = Math.Min(selStart + Math.Max(SelLen, 0), text.Length);
            if (SelLen > 0 && selEnd > selStart && selEnd > selStart && text[selEnd - 1] == '\n' && selEnd - 1 > selStart)
                selEnd--;   // 选区尾正好带换行时不含最后空行
            int lineStart = CountNL(text, 0, selStart);
            int lineEnd = CountNL(text, 0, Math.Max(selEnd, selStart));

            var result = CommentCommands.Toggle(text, lineStart, lineEnd, lang, comment);
            if (result is null || result == text) return;

            int caret = selStart;
            // 直接整篇写回，不走 SelTextRaw="" 先删选区——那会先产生一步
            // 删除撤销记录，再接一步全量替换，撤销栈出现脏步骤；
            // _syncing 包裹屏蔽事件重入，光标恢复单步完成
            _syncing = true;
            try { RawText = result; }
            finally { _syncing = false; }
            Sel(Math.Min(caret, RawText.Length), 0);
            Modified?.Invoke(this, EventArgs.Empty);
            StatusChanged?.Invoke(this, EventArgs.Empty);
        }
        catch { /* 注释命令失败不致命，保持原文 */ }
    }

    static int CountNL(string t, int start, int end)
    {
        int n = 0;
        for (int i = start; i < end && i < t.Length; i++) if (t[i] == '\n') n++;
        return n;
    }

    /// <summary>按当前语言风格格式化整篇文档。</summary>
    public void FormatDocument()
    {
        ReplaceWholeText(CodeFormatter.Format(RawText, _lang));
    }

    /// <summary>格式化选区（无选区时格式化整篇）。</summary>
    public void FormatSelection()
    {
        if (SelLen <= 0) { FormatDocument(); return; }
        var sel = SelTextRaw;
        var f = CodeFormatter.Format(sel, _lang);
        if (f == sel) return;
        int caret = SelPos;
        _accepting = true;
        try { SelTextRaw = f; }
        finally { _accepting = false; }
        HidePopup();
        Sel(Math.Min(caret, f.Length), 0);
        ScheduleRecolor();
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    void ReplaceWholeText(string f)
    {
        var t = RawText;
        if (f == t) return;
        int caret = SelPos;
        _syncing = true;
        try { RawText = f; }
        finally { _syncing = false; }
        HidePopup();
        Sel(Math.Min(caret, f.Length), 0);
        ScheduleRecolor();
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    public void ZoomIn() { _zoom = Math.Min(5.0, _zoom + 0.1); ApplyZoom(); }
    public void ZoomOut() { _zoom = Math.Max(0.25, _zoom - 0.1); ApplyZoom(); }
    public void ZoomReset() { _zoom = 1.0; ApplyZoom(); }

    void ApplyZoom()
    {
        _tb.FontSize = BaseFontSize * _zoom;
        _re.FontSize = BaseFontSize * _zoom;
        _gutterKey = "";        // 字号变了行高也变，强制重排行号
        RedrawGutter();
        RenderMinimap(true);    // 行高估算不变但视口比例变了，强制刷新
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    // ================= 查找替换 =================

    public void SetMatches(List<(int Start, int Len)> matches) { /* 查找高亮由 FindPanel 计数呈现 */ }
    public void ClearSearch() { }

    public bool FindNext(string pattern, FindOpts o, bool backwards)
    {
        var t = RawText;
        int from = backwards ? Math.Max(0, SelPos - 1) : SelPos + SelLen;
        var (pos, len) = SearchEngine.Find(t, pattern, o, from, backwards);
        if (pos < 0) return false;
        FocusEd();
        Sel(pos, len);
        return true;
    }

    public int CountMatches(string pattern, FindOpts o)
        => SearchEngine.FindAll(RawText, pattern, o).Count;

    public bool ReplaceCurrent(string pattern, string replacement, FindOpts o)
    {
        var t = RawText;
        int selStart = SelPos, selLen = SelLen;
        // 当前选区正好是匹配 → 直接替换
        if (selLen > 0)
        {
            var m = SearchEngine.Find(t, pattern, o, selStart, false);
            if (m.Pos == selStart && m.Len == selLen)
            {
                SelTextRaw = replacement;
                ScheduleRecolor();
                return true;
            }
        }
        return FindNext(pattern, o, false);
    }

    public int ReplaceAll(string pattern, string replacement, FindOpts o)
    {
        var t = RawText;
        int n = SearchEngine.ReplaceAll(ref t, pattern, replacement, o);
        if (n > 0)
        {
            int caret = SelPos;
            _syncing = true;
            try { RawText = t; }
            finally { _syncing = false; }
            Sel(Math.Min(caret, t.Length), 0);
            ScheduleRecolor();
            Modified?.Invoke(this, EventArgs.Empty);
            StatusChanged?.Invoke(this, EventArgs.Empty);
        }
        return n;
    }

    // ================= 语法着色（RichEditBox 内核） =================

    void ScheduleRecolor()
    {
        if (!_rich) return;
        try
        {
            _colorTimer ??= DispatcherQueue.CreateTimer();
            _colorTimer.Interval = TimeSpan.FromMilliseconds(220);
            _colorTimer.Stop();
            _colorTimer.Tick -= ColorTimerTick;
            _colorTimer.Tick += ColorTimerTick;
            _colorPending = true;
            _colorTimer.Start();
        }
        catch { }
    }

    void ColorTimerTick(object? s, object e)
    {
        try { _colorTimer?.Stop(); } catch { }
        _colorPending = false;
        Recolor();
    }

    void Recolor()
    {
        if (!_rich || _syncing) return;
        _syncing = true;    // 着色过程中触发的事件一律忽略
        try
        {
            if (_re.Document is not { } doc) return;
            var text = RawText;
            // 幂等保证：文本没变说明上次已着好色，格式化都不做，
            // 杜绝任何"着色→事件→再着色"的循环
            if (text == _lastColorText) return;

            // WinUI 文档对象没有字符计数属性：用规范文本长度（换行 1:1 对应）
            int n = text.Length;
            if (n <= 0) return;
            _lastPaintN = n;

            // 整体重置为默认色：一次取区间同时清前景与背景，
            // 少一次全文档 GetRange 往返（大文件上收益明显）
            var full = doc.GetRange(0, n);
            full.CharacterFormat.ForegroundColor = _baseFg;
            // 背景也要整体复位：编辑内核的插入会继承前一个字符的格式，
            // 括号配对高亮的黄底会被紧随其后输入的内容继承，表现为
            // "从括号开始所有内容都有背景色"。复位后由下方按需重亮。
            full.CharacterFormat.BackgroundColor = _baseBg;

            // 超大文档只保证默认色，不做分段着色（避免卡顿）
            if (text.Length > 300_000) return;

            var toks = new List<TokenSpan>();
            // 整篇逐行分词：行注释/未闭合字符串只作用于本行（此前整篇一次分词，
            // 一个 // 就会把其后所有内容涂成注释色），块注释状态跨行传递
            Tokenizer.TokenizeDocument(_lang, text, toks);

            // 相邻且同色的 token 合并成段后一次上色，减少 GetRange 次数。
            // 【关键】ITextDocument.GetRange 两参是"起点, 终点"（终点=区间尾，
            // 不是长度）：此前把"词长"当终点传进去，终点<起点时内核会做
            // 区间反转/钳制，实际涂出"从词首一路刷到文末"的大区间——
            // 这就是"关键字整段变注释绿/数字绿"反复出现的真根因。
            int runStart = -1, runEnd = -1;
            var runKind = TokKind.Text;
            foreach (var t in toks)
            {
                if (t.Start >= n || t.Length <= 0) continue;
                int end = t.Start + Math.Min(t.Length, n - t.Start);
                if (runStart >= 0 && t.Kind == runKind && t.Start == runEnd)
                {
                    runEnd = end;   // 连续同色：并入当前段
                }
                else
                {
                    if (runStart >= 0) PaintRun(_re, runStart, runEnd, runKind);
                    runStart = t.Start;
                    runEnd = end;
                    runKind = t.Kind;
                }
            }
            if (runStart >= 0) PaintRun(_re, runStart, runEnd, runKind);

            ApplyRainbow(text, toks, n);
            RepaintBlockFills(n);        // 背景复位后，把列块/全部高亮按记录重新点亮
            _lastColorText = text;
            _toks = toks;           // 缓存分词：括号匹配恢复颜色用
            _hlA = _hlB = -1;       // 重着色清掉了括号高亮，位置作废
            UpdateBracketMatch();   // 重着色后立即恢复括号高亮（此时 _syncing=true，无事件重入）
        }
        catch { /* 着色失败不影响编辑，下次文本变化时重试 */ }
        finally { _syncing = false; }
    }

    string _lastColorText = "";

    /// <summary>按"起点, 终点"语义涂一段文字色；终点越界自动钳到文末，
    /// 单段失败只跳过本段，不影响后续段的着色。</summary>
    void PaintRun(Microsoft.UI.Xaml.Controls.RichEditBox re, int start, int end, TokKind kind)
    {
        try
        {
            if (end <= start) return;
            if (end > _lastPaintN) end = _lastPaintN;
            if (end <= start || re.Document is not { } doc) return;
            doc.GetRange(start, end).CharacterFormat.ForegroundColor = TokenColor(kind);
        }
        catch { /* 单段着色失败不影响整体 */ }
    }

    int _lastPaintN;

    /// <summary>背景整体复位后，按记录重新点亮列块/全部高亮（区间随编辑可能漂移，下次交互会重算）。</summary>
    void RepaintBlockFills(int n)
    {
        try
        {
            if (_blockHi.Count == 0 || _re.Document is not { } doc) return;
            foreach (var (start, len, fill) in _blockHi)
            {
                if (len <= 0 || start < 0 || start >= n) continue;
                int end = start + Math.Min(len, n - start);
                doc.GetRange(start, end).CharacterFormat.BackgroundColor = fill;
            }
        }
        catch { }
    }

    Windows.UI.Color TokenColor(TokKind k)
    {
        string? key = k switch
        {
            TokKind.Keyword => "Ant.TokKeyword",
            TokKind.Control => "Ant.TokControl",
            TokKind.String => "Ant.TokString",
            TokKind.Comment => "Ant.TokComment",
            TokKind.DocComment => "Ant.TokDocComment",
            TokKind.Number => "Ant.TokNumber",
            TokKind.Type => "Ant.TokType",
            TokKind.Preproc => "Ant.TokPreproc",
            TokKind.Tag => "Ant.TokTag",
            TokKind.Attr => "Ant.TokAttr",
            TokKind.Heading => "Ant.TokHeading",
            TokKind.Member => "Ant.TokAttr",
            _ => null,
        };
        if (key is not null &&
            Application.Current.Resources.TryGetValue(key, out var v) &&
            v is SolidColorBrush sc)
            return sc.Color;
        return _baseFg;
    }

    /// <summary>彩虹括号：按嵌套层级给 ()[]{} 循环着色（字符串/注释内不着色）。</summary>
    void ApplyRainbow(string text, List<TokenSpan> toks, int n)
    {
        try
        {
            if (_re.Document is not { } doc) return;
            var masked = new bool[text.Length];
            foreach (var t in toks)
            {
                if (t.Kind is not (TokKind.String or TokKind.Comment or TokKind.DocComment)) continue;
                int end = Math.Min(t.Start + t.Length, masked.Length);
                for (int i = Math.Max(0, t.Start); i < end; i++) masked[i] = true;
            }

            int depth = 0, ops = 0;
            for (int i = 0; i < text.Length && ops < 5000; i++)
            {
                if (masked[i]) continue;
                char c = text[i];
                if (c == '(' || c == '[' || c == '{')
                {
                    // GetRange 两参是"起点, 终点"：单字符区间为 (i, i+1)
                    doc.GetRange(i, i + 1).CharacterFormat.ForegroundColor
                        = BracketColors[depth % BracketColors.Length];
                    depth++; ops++;
                }
                else if (c == ')' || c == ']' || c == '}')
                {
                    depth = Math.Max(0, depth - 1);
                    doc.GetRange(i, i + 1).CharacterFormat.ForegroundColor
                        = BracketColors[depth % BracketColors.Length];
                    ops++;
                }
            }
        }
        catch { }
    }

    // ================= 智能提示（VS 风格） =================

    // 内核重放预期：富内核（RichEditBox）对“已拦截”的字符键可能仍原生补插一次
    // （KeyDown 的 Handled 对字符键不总生效），表现为打 ( 得 "(("、回车多一行。
    // 拦截时记下预期字符与位置，OnTextChanged 里核对，发现重放就删掉。
    char _echo = '\0';
    int _echoAt = -1;

    void OnTextChanged(object sender, object e)
    {
        if (_syncing) return;
        // 着色引擎重刷颜色也会触发 TextChanged：文本没变就不是真编辑，
        // 直接跳过，避免"着色→伪事件→重着色"循环导致弹层闪烁
        var t = RawText;
        UpdateScrollBar();      // 内容长度变了，滑条显隐与长度随之变（防抖在内部 try）

        // ---------- 内核重放修复 ----------
        // 恰好多出我们拦截时预期的那个字符 → 是内核重放，删掉它
        if (_echo != '\0' && t.Length == _lastRaw.Length + 1 && _echoAt >= 0
            && _echoAt < t.Length && t[_echoAt] == _echo && t.Remove(_echoAt, 1) == _lastRaw)
        {
            int at = _echoAt;
            _echo = '\0'; _echoAt = -1;
            _syncing = true;
            try { Sel(at, 1); SelTextRaw = ""; }
            finally { _syncing = false; }
            Sel(at, 0);
            _lastRaw = RawText;
            return;                 // 文本回到基线，不算一次编辑
        }
        _echo = '\0'; _echoAt = -1; // 无回声：预期作废

        if (t == _lastRaw) return;
        _lastRaw = t;
        if (FoldActive) ReconcileFolded();   // 绕过按键拦截的修改（输入法等）：先还原完整文本
        MaybeShowPopup();
        MaybeShowParamHint();                // 参数提示：敲 ( 或 , 时跟随
        ScheduleRecolor();
        RedrawGutter();
        ScheduleMinimap();                   // 小地图防抖重绘
        if (_blockOn) ExitBlockMode();       // 文本变了，自管高亮区间失效
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    void MaybeShowPopup()
    {
        // 仅对代码语言启用（纯文本与 Markdown 等文章类内容不弹，
        // 避免写文档时每个词都冒出提示框）
        if (_lang.Id is "plain" or "markdown") { HidePopup(); return; }
        var t = RawText;
        int caret = Math.Min(SelPos, t.Length);
        var items = CompletionEngine.GetCompletions(t, caret, _lang, out var prefix);
        // 输入过程中逐步过滤已弹出的列表
        if (_popup.IsOpen && items.Count == 0)
        {
            // 退化：用当前前缀过滤现有列表
            var word = CurrentWordPrefix(t, caret);
            if (word.Length > 0)
                items = _items.Where(x => x.StartsWith(word, StringComparison.Ordinal)).ToList();
        }
        if (items.Count == 0 || items.Count > 200) { if (_popup.IsOpen) HidePopup(); return; }
        // 唯一候选就是已输入的词 → 没有可补的内容，不弹（VS 同款行为）
        if (items.Count == 1 && items[0] == CurrentWordPrefix(t, caret))
        { if (_popup.IsOpen) HidePopup(); return; }
        ShowPopup(items, prefix, caret);
    }

    string CurrentWordPrefix(string t, int caret)
    {
        int i = caret - 1;
        while (i >= 0 && (char.IsLetterOrDigit(t[i]) || t[i] == '_')) i--;
        return t[(i + 1)..caret];
    }

    void ShowPopup(List<string> items, string prefix, int caret)
    {
        try
        {
            _items.Clear();
            _items.AddRange(items);
            _prefix = prefix;
            _sel = 0;

            // 列表内容没变就复用现有弹层，只挪位置——避免每次按键都重建造成闪烁
            var key = prefix + "\u0001" + string.Join("\u0002", _items.Take(12));
            bool rebuild = !_popup.IsOpen || key != _listKey;
            _listKey = key;

            if (rebuild)
            {
                _listPanel.Children.Clear();
                for (int i = 0; i < _items.Count && i < 12; i++)
                {
                    var idx = i;
                    var tb = new TextBlock
                    {
                        Text = _items[i],
                        FontFamily = new FontFamily("Consolas"),
                        FontSize = 14,
                        Padding = new Thickness(8, 3, 12, 3),
                        // 前景色随主题显式设定：主题字典切换后继承色可能失联，杜绝"白字白底"
                        Foreground = TryBrush("Ant.Text", 31, 36, 48),
                    };
                    tb.Tapped += (_, _) => { _sel = idx; AcceptCompletion(); };
                    _listPanel.Children.Add(tb);
                }
                HighlightSelection();
            }

            // 定位到光标处：TextBox 用精确定位；RichEditBox 按等宽字体估算。
            // 定位与开弹层分开：定位失败时按估算兜底，绝不阻止弹层打开
            var (px, py) = LocateCaret(caret);
            _popupBorder.MinWidth = 200;
            _popupBorder.MaxWidth = 360;
            _popup.HorizontalOffset = Math.Max(0, px);
            _popup.VerticalOffset = Math.Max(0, py);
            // 已开时只挪位置不动焦点；新开时把焦点收回编辑框，方向键/回车才能继续操作
            if (!_popup.IsOpen) { _popup.IsOpen = true; FocusEd(); }
        }
        catch { /* 任何异常都不影响编辑 */ }
    }

    /// <summary>光标屏幕位置估算（补全弹层与参数提示共用）：TextBox 精确定位，RichEditBox 等宽估算。</summary>
    (double x, double y) LocateCaret(int caret)
    {
        try
        {
            if (!_rich)
            {
                try
                {
                    var rect = _tb.GetRectFromCharacterIndex(Math.Min(caret, _tb.Text.Length), true);
                    var origin = _tb.TransformToVisual(this).TransformPoint(new Windows.Foundation.Point(rect.X, rect.Bottom));
                    return (origin.X, origin.Y + 4);
                }
                catch
                {
                    var (line, col) = CaretLC();
                    return (col * _tb.FontSize * 0.55 + (_gutter.Visibility == Visibility.Visible ? _gutterWidth : 0),
                            (line + 1) * _tb.FontSize * 1.4 + 4);
                }
            }
            var (l, c) = CaretLC();
            return (c * _re.FontSize * 0.55 + (_gutter.Visibility == Visibility.Visible ? _gutterWidth : 0),
                    (l + 1) * _re.FontSize * 1.4 + 4);
        }
        catch
        {
            return (24, 24);   // 最坏情况：弹在编辑区左上角
        }
    }

    // ---------- 参数提示浮层 ----------

    void MaybeShowParamHint()
    {
        try
        {
            if (_lang.Id is not ("clike" or "csharp" or "python")) { HideHint(); return; }
            if (_popup.IsOpen) { HideHint(); return; }     // 补全弹层优先，互斥
            var t = RawText;
            int caret = Math.Min(SelPos, t.Length);
            // 触发时机：刚敲了 ( 或 ,，或提示已开着继续跟随
            char prev = caret > 0 ? t[caret - 1] : '\0';
            bool trigger = prev is '(' or ',' || (prev == ' ' && caret > 1 && t[caret - 2] == ',');
            if (!_hintPopup.IsOpen && !trigger) { HideHint(); return; }

            if (!ParamHints.TryGetHint(t, caret, _lang.Id, out var name, out var argIdx, out var sig, out var src))
            { HideHint(); return; }
            if (sig.Length == 0) { HideHint(); return; }   // 未知函数不硬弹

            _hintText.Inlines.Clear();
            _hintText.Inlines.Add(new Microsoft.UI.Xaml.Documents.Run { Text = name + "(", Foreground = new SolidColorBrush(_baseFg) });
            // 参数逐个着色：当前参数高亮，其余常规色
            var inner = sig[(name.Length + 1)..^1];    // 去掉 name( 和末尾 )
            var parts = inner.Split(',');
            var hiColor = TryColor("Ant.TokKeyword", 166, 74, 62);
            for (int i = 0; i < parts.Length; i++)
            {
                var piece = i == 0 ? parts[i] : "," + parts[i];
                _hintText.Inlines.Add(new Microsoft.UI.Xaml.Documents.Run
                {
                    Text = piece,
                    Foreground = new SolidColorBrush(i == argIdx ? hiColor : _baseFg),
                    FontWeight = i == argIdx ? Microsoft.UI.Text.FontWeights.Bold : Microsoft.UI.Text.FontWeights.Normal,
                });
            }
            _hintText.Inlines.Add(new Microsoft.UI.Xaml.Documents.Run { Text = ")", Foreground = new SolidColorBrush(_baseFg) });

            var (px, py) = LocateCaret(caret);
            _hintBorder.MinWidth = 120;
            _hintBorder.MaxWidth = 460;
            _hintPopup.HorizontalOffset = Math.Max(0, px);
            _hintPopup.VerticalOffset = Math.Max(0, py);
            if (!_hintPopup.IsOpen) _hintPopup.IsOpen = true;
            _hintKeep = true;                    // 本次文本变化刷新过提示，紧跟的选区事件不收起
        }
        catch { /* 提示失败不影响编辑 */ }
    }

    void HideHint()
    {
        if (_hintPopup.IsOpen) _hintPopup.IsOpen = false;
    }

    // ---------- 列块（矩形）选区高亮与词出现高亮（仅着色内核） ----------
    // 务实版：WinUI 内核不支持多插入点，这里提供 Alt+Shift+方向键的列块视觉高亮
    // 与 Ctrl+Shift+L 词出现高亮；跨行编辑算法在 BlockEditEngine（纯逻辑可测）。

    (int Line, int Col)? _blockAnchor;               // 列块锚点（0 计）
    readonly List<(int Start, int Len, Windows.UI.Color Fill)> _blockHi = new();  // 当前自管高亮区间
    bool _blockOn;                                    // 高亮是否生效
    DispatcherQueueTimer? _blockTimer;

    (int line, int col) PosLC(int pos)
    {
        var t = RawText;
        pos = Math.Clamp(pos, 0, t.Length);
        int line = 0, lastNl = -1;
        for (int i = 0; i < pos; i++)
            if (t[i] == '\n') { line++; lastNl = i; }
        return (line, pos - lastNl - 1);
    }

    /// <summary>Alt+Shift+方向键：记录/更新列块锚点，延后重画高亮（等内核完成光标移动）。</summary>
    void BlockExtend()
    {
        _blockAnchor ??= PosLC(SelPos + SelLen);      // 首次进入：选区另一端为锚点
        _blockTimer ??= DispatcherQueue.CreateTimer();
        _blockTimer.Interval = TimeSpan.FromMilliseconds(40);
        _blockTimer.Stop();
        _blockTimer.Tick -= BlockTimerTick;
        _blockTimer.Tick += BlockTimerTick;
        _blockTimer.Start();
    }

    void BlockTimerTick(object? s, object e)
    {
        if (_blockTimer is not null) _blockTimer.Stop();
        PaintBlock();
    }

    /// <summary>按锚点与当前光标画列块高亮；列块退化（单点）时不画。</summary>
    void PaintBlock()
    {
        try
        {
            if (!_rich || _blockAnchor is not { } a) return;
            var c = PosLC(SelPos);
            var lines = RawText.Split('\n');
            var ranges = BlockEditEngine.CoveredRanges(lines, a, c);
            if (ranges.Count == 0) { ClearBlockHi(); return; }

            ClearBlockHi(silent: true);
            var fill = Windows.UI.Color.FromArgb(60, 84, 118, 168);
            if (_re.Document is not { } doc) return;
            foreach (var (r, s, e2) in ranges)
            {
                var (ls, _) = LineSpan(r + 1);
                int start = ls + s, len = e2 - s;
                if (len <= 0) continue;
                // GetRange 两参是"起点, 终点"：区间终点 = 起点 + 长度
                doc.GetRange(start, start + len).CharacterFormat.BackgroundColor = fill;
                _blockHi.Add((start, len, fill));
            }
            _blockOn = true;
        }
        catch { /* 高亮失败不影响编辑 */ }
    }

    /// <summary>Ctrl+Shift+L：高亮选中文本/光标词的全部出现位置（全字匹配）。</summary>
    void HighlightAllOccurrences()
    {
        try
        {
            if (!_rich) return;
            if (_blockOn) { ExitBlockMode(); return; }     // 再按一次取消
            var t = RawText;
            string word = SelLen > 0 ? SelTextRaw : CurrentWord();
            if (word.Trim().Length == 0) return;
            var hits = SearchEngine.FindAll(t, word, new FindOpts(WholeWord: true), 2000);
            if (hits.Count == 0) return;

            if (_re.Document is not { } doc) return;
            var fill = Windows.UI.Color.FromArgb(70, 190, 138, 50);   // 琥珀淡底
            foreach (var (start, len) in hits)
            {
                if (len <= 0) continue;
                // GetRange 两参是"起点, 终点"：同 PaintBlock
                doc.GetRange(start, start + len).CharacterFormat.BackgroundColor = fill;
                _blockHi.Add((start, len, fill));
            }
            _blockOn = true;
        }
        catch { /* 高亮失败不影响编辑 */ }
    }

    string CurrentWord()
    {
        var t = RawText;
        int p = Math.Min(SelPos, t.Length);
        int i = p;
        while (i > 0 && (char.IsLetterOrDigit(t[i - 1]) || t[i - 1] == '_')) i--;
        int j = p;
        while (j < t.Length && (char.IsLetterOrDigit(t[j]) || t[j] == '_')) j++;
        return i < j ? t[i..j] : "";
    }

    /// <summary>清除自管高亮并按分词恢复原色（silent 时不重置锚点）。</summary>
    void ClearBlockHi(bool silent = false)
    {
        try
        {
            if (_re.Document is not { } doc) { _blockHi.Clear(); return; }
            foreach (var (start, len, _) in _blockHi)
            {
                for (int p = start; p < start + len; p++)
                {
                    var f = doc.GetRange(p, p + 1).CharacterFormat;
                    f.BackgroundColor = _baseBg;
                    f.ForegroundColor = TokenColor(TokenAt(p));
                }
            }
        }
        catch { }
        _blockHi.Clear();
        if (!silent) { _blockOn = false; _blockAnchor = null; }
    }

    /// <summary>退出列块/词高亮模式（光标移动、Esc、文本变化时调用）。</summary>
    void ExitBlockMode()
    {
        if (!_blockOn && _blockAnchor is null) return;
        ClearBlockHi();
        _blockAnchor = null;
        _blockOn = false;
    }

    void HighlightSelection()
    {
        for (int i = 0; i < _listPanel.Children.Count; i++)
            if (_listPanel.Children[i] is TextBlock tb)
            {
                bool sel = i == _sel;
                tb.Foreground = new SolidColorBrush(sel
                    ? Windows.UI.Color.FromArgb(255, 0, 102, 204)
                    : Windows.UI.Color.FromArgb(255, 38, 38, 38));
                tb.FontWeight = sel ? Microsoft.UI.Text.FontWeights.Bold : Microsoft.UI.Text.FontWeights.Normal;
            }
    }

    /// <summary>Tab 展开代码片段：光标前是片段缩写时替换为模板正文，光标落到 $0 位置。</summary>
    bool TryExpandSnippet()
    {
        try
        {
            if (SelLen > 0) return false;
            var t = RawText;
            int caret = Math.Min(SelPos, t.Length);
            HideHint();
            int i = caret;
            while (i > 0 && (char.IsLetterOrDigit(t[i - 1]) || t[i - 1] == '_')) i--;
            if (i == caret) return false;
            string word = t[i..caret];
            var sn = Snippets.For(_lang.Id).FirstOrDefault(s => s.Key == word);
            if (sn is null) return false;

            int lineStart = t.LastIndexOf('\n', Math.Max(0, caret - 1)) + 1;
            string indent = (t[lineStart..i]).All(char.IsWhiteSpace) ? t[lineStart..i] : "";
            var (text, off) = Snippets.Expand(sn, indent);

            _accepting = true;
            _syncing = true;
            try { Sel(i, caret - i); SelTextRaw = text; }
            finally { _syncing = false; _accepting = false; }
            _lastRaw = RawText;
            Sel(i + off, 0);
            ScheduleRecolor();
            RedrawGutter();
            Modified?.Invoke(this, EventArgs.Empty);
            StatusChanged?.Invoke(this, EventArgs.Empty);
            return true;
        }
        catch { return false; }
    }

    /// <summary>Shift+Tab 反缩进：删除当前行行首最多 4 个空格。</summary>
    public void Unindent()
    {
        var t = RawText;
        var (l0, _) = CaretLC();
        var (s, _) = LineSpan(l0 + 1);
        int i = s, n = 0;
        while (i < t.Length && t[i] == ' ' && n < 4) { i++; n++; }
        if (n == 0) return;
        _accepting = true;
        _syncing = true;
        try { Sel(s, n); SelTextRaw = ""; }
        finally { _syncing = false; _accepting = false; }
        _lastRaw = RawText;
        ScheduleRecolor();
        RedrawGutter();
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    void HidePopup()
    {
        if (_popup.IsOpen) _popup.IsOpen = false;
        _items.Clear();
        _listKey = "";
    }

    /// <summary>Tab 缩进：在光标处插入 4 个空格（补全弹层打开时优先接受补全），
    /// 插入后把光标明确落到缩进之后，保证接着输入的位置在制表位右侧。</summary>
    void InsertIndent()
    {
        int caret = Math.Min(SelPos, RawText.Length);
        _accepting = true;
        _syncing = true;
        try { SelTextRaw = "    "; }
        finally { _syncing = false; _accepting = false; }
        Sel(caret + 4, 0);
        _lastRaw = RawText;
        ScheduleRecolor();
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>括号自动配对：返回 true 表示已处理（e.Handled 由调用方使用）。
    /// 括号虚拟键没有具名成员（184-194 为空），直接用虚拟键码：0xDB=[{/[
    /// 0xDD=]})，9/0 配 Shift 得 ( )。纯文本与 Markdown 不做配对。</summary>
    bool TryAutoPair(KeyRoutedEventArgs e)
    {
        if (_ctrlDown || e.KeyStatus.IsMenuKeyDown || _lang.Id is "plain" or "markdown")
            return false;

        string? open = null, close;
        switch (e.Key)
        {
            case Windows.System.VirtualKey.Number9 when _shiftDown:
                open = "("; close = ")"; break;
            case (Windows.System.VirtualKey)0xDB:
                open = _shiftDown ? "{" : "["; close = _shiftDown ? "}" : "]"; break;
            case Windows.System.VirtualKey.Number0 when _shiftDown:
                close = ")"; break;
            case (Windows.System.VirtualKey)0xDD:
                close = _shiftDown ? "}" : "]"; break;
            default: return false;
        }

        var t = RawText;
        int caret = Math.Min(SelPos, t.Length);
        char next = caret < t.Length ? t[caret] : '\0';

        // 只敲了右括号：光标后正是同款就跳过去，不重复插入；否则交内核正常输入
        if (open is null)
        {
            if (next == close[0])
            {
                Sel(caret + 1, 0);
                e.Handled = true;
                _echo = close[0]; _echoAt = SelPos;   // 防内核重放（见 OnTextChanged）
                return true;
            }
            return false;
        }

        _accepting = true;
        _syncing = true;
        try
        {
            if (SelLen > 0)
            {
                string inner = SelTextRaw;                    // 有选区：包裹选区
                SelTextRaw = open + inner + close;
                Sel(caret + 1 + inner.Length, 0);
            }
            else
            {
                SelTextRaw = open + close;                    // 光标停在配对中间
                Sel(caret + 1, 0);
            }
        }
        finally { _syncing = false; _accepting = false; }
        _lastRaw = RawText;
        e.Handled = true;
        _echo = open[0]; _echoAt = SelPos;    // 防内核重放：原生若再补一个左括号，TextChanged 里会删掉
        ScheduleRecolor();
        RedrawGutter();
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
        return true;
    }

    /// <summary>回车自动缩进：新行继承当前行行首空白；前一字符是 { 时多缩一层，
    /// 夹在 {} 之间回车则展开成三行、光标落在中间缩进行。</summary>
    void EnterAutoIndent()
    {
        var t = RawText;
        int caret = Math.Min(SelPos, t.Length);
        int lineStart = t.LastIndexOf('\n', Math.Max(0, caret - 1)) + 1;
        int i = lineStart;
        while (i < caret && (t[i] == ' ' || t[i] == '\t')) i++;
        string indent = t[lineStart..i];

        char prev = caret > 0 ? t[caret - 1] : '\0';
        char next = caret < t.Length ? t[caret] : '\0';

        _accepting = true;
        _syncing = true;
        try
        {
            if (prev == '{' && next == '}')
            {
                SelTextRaw = "\n" + indent + "    " + "\n" + indent;
                Sel(caret + 1 + indent.Length + 4, 0);
            }
            else
            {
                string extra = prev == '{' ? "    " : "";
                SelTextRaw = "\n" + indent + extra;
                Sel(caret + 1 + indent.Length + extra.Length, 0);
            }
        }
        finally { _syncing = false; _accepting = false; }
        _lastRaw = RawText;
        ScheduleRecolor();
        RedrawGutter();
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
        _echo = '\n'; _echoAt = SelPos;   // 回车是字符键：防内核重放换行打乱刚排好的格式
    }

    void OnKeyDown(object sender, KeyRoutedEventArgs e)
    {
        // 新按键作废上一键的内核重放预期（若真被重放，TextChanged 早已修复）
        _echo = '\0'; _echoAt = -1;

        // 折叠保护：会改文本的按键先自动展开，再正常处理（折叠期间不允许盲改）
        FoldGuardKeyDown(e);

        // 修饰键状态跟踪（Shift 用于 Tab/Shift+Tab）
        if (e.Key == Windows.System.VirtualKey.Shift) _shiftDown = true;

        // VS 风格两段式快捷键：Ctrl+K, Ctrl+D 格式化文档；Ctrl+K, Ctrl+F 格式化选区
        if (e.Key == Windows.System.VirtualKey.Control) _ctrlDown = true;
        if (_ctrlDown && e.Key == Windows.System.VirtualKey.K)
        {
            _chordK = true;
            _chordAt = DateTime.UtcNow;
            e.Handled = true;
            return;
        }
        if (_chordK)
        {
            // 修饰键放行：Ctrl+K 后松开再重按 Ctrl（Ctrl+K, Ctrl+U 的自然按法），
            // 该次 Ctrl 的 KeyDown 绝不能把 _chordK 当场作废；Shift/Alt 同理。
            // 原缺陷：任何非目标键（含修饰键）都清 _chordK，第二段永远到不了
            if (e.Key is Windows.System.VirtualKey.Control or Windows.System.VirtualKey.Shift
                or Windows.System.VirtualKey.Menu
                or Windows.System.VirtualKey.LeftControl or Windows.System.VirtualKey.RightControl
                or Windows.System.VirtualKey.LeftShift or Windows.System.VirtualKey.RightShift
                or Windows.System.VirtualKey.LeftMenu or Windows.System.VirtualKey.RightMenu)
            {
                return;      // 不置 e.Handled、不清 _chordK，等第二段字母键
            }
            bool chordAlive = _ctrlDown && DateTime.UtcNow - _chordAt < TimeSpan.FromSeconds(2);
            _chordK = false;
            if (chordAlive && e.Key == Windows.System.VirtualKey.D)
            {
                FormatDocument();
                e.Handled = true;
                return;
            }
            if (chordAlive && e.Key == Windows.System.VirtualKey.F)
            {
                FormatSelection();
                e.Handled = true;
                return;
            }
            // VS 语义：第二段键带不带 Ctrl 都认（Ctrl+K, Ctrl+C 与 Ctrl+K, C 等价）
            bool vsAlive = DateTime.UtcNow - _chordAt < TimeSpan.FromSeconds(2);
            if (vsAlive && e.Key == Windows.System.VirtualKey.C)
            {
                CommentSelection();
                e.Handled = true;
                return;
            }
            if (vsAlive && e.Key == Windows.System.VirtualKey.U)
            {
                UncommentSelection();
                e.Handled = true;
                return;
            }
        }

        // Ctrl+D 复制当前行；Alt+↑/↓ 上下移动当前行（与"编辑→行操作"菜单同款）
        if (_ctrlDown && e.Key == Windows.System.VirtualKey.D)
        {
            e.Handled = true;
            DuplicateLine();
            return;
        }

        // Ctrl+Shift+U 转大写 / Ctrl+U 转小写（VS 同款；置于 chord 之后，
        // chord 第二段 Ctrl+K, U 优先匹配，不受此影响）
        if (_ctrlDown && e.Key == Windows.System.VirtualKey.U)
        {
            e.Handled = true;
            TransformSelection(_shiftDown
                ? static s => s.ToUpperInvariant()
                : static s => s.ToLowerInvariant());
            return;
        }
        if (e.KeyStatus.IsMenuKeyDown)
        {
            if (e.Key == Windows.System.VirtualKey.Up) { e.Handled = true; MoveLine(-1); return; }
            if (e.Key == Windows.System.VirtualKey.Down) { e.Handled = true; MoveLine(1); return; }
        }

        // Ctrl+\ 跳到配对括号
        if (_ctrlDown && e.Key == (Windows.System.VirtualKey)0xDC)
        {
            e.Handled = true;
            GotoMatchingBracket();
            return;
        }

        // 括号自动配对：左括号补右括号（有选区时包裹选区），光标停在配对中间；
        // 输入右括号且光标后正是同款时跳过一格，避免重复
        if (TryAutoPair(e)) return;

        // 回车自动缩进：新行继承当前行行首空白；{ 后回车再多缩一层，
        // 夹在 {} 之间回车则三行展开（补全弹层打开时不抢 Enter）
        if (e.Key == Windows.System.VirtualKey.Enter && !_ctrlDown && !e.KeyStatus.IsMenuKeyDown
            && !_popup.IsOpen && _lang.Id is not ("plain" or "markdown"))
        {
            e.Handled = true;
            EnterAutoIndent();
            return;
        }

        // 书签：Ctrl+F2 打/取消，F2 下一个，Shift+F2 上一个
        if (e.Key == Windows.System.VirtualKey.F2)
        {
            e.Handled = true;
            if (_ctrlDown) ToggleBookmark();
            else if (_shiftDown) PrevBookmark();
            else NextBookmark();
            return;
        }

        // Alt+Shift+方向键：列块选区扩展（视觉高亮，编辑算法见 BlockEditEngine）
        if (e.KeyStatus.IsMenuKeyDown && _shiftDown)
        {
            if (e.Key is Windows.System.VirtualKey.Up or Windows.System.VirtualKey.Down
                or Windows.System.VirtualKey.Left or Windows.System.VirtualKey.Right)
            {
                BlockExtend();       // 不拦截：让内核正常移动光标，40ms 后重画列块
            }
        }

        // Ctrl+Shift+L：删除当前行（VS 同款，与"编辑→行操作"菜单同款）
        if (_ctrlDown && _shiftDown && e.Key == Windows.System.VirtualKey.L)
        {
            e.Handled = true;
            DeleteLine();
            return;
        }

        // Ctrl+Alt+H：高亮词的全部出现位置（原 Ctrl+Shift+L 让位给删除当前行）
        if (_ctrlDown && e.KeyStatus.IsMenuKeyDown && e.Key == Windows.System.VirtualKey.H)
        {
            e.Handled = true;
            HighlightAllOccurrences();
            return;
        }

        // Esc 退出列块/词高亮
        if (e.Key == Windows.System.VirtualKey.Escape && _blockOn)
        {
            ExitBlockMode();
            return;
        }

        if (!_popup.IsOpen || _items.Count == 0)
        {
            // Tab/Shift+Tab 在编辑区内就是缩进/反缩进，绝不能把焦点丢到顶部菜单
            if (e.Key == Windows.System.VirtualKey.Tab)
            {
                e.Handled = true;
                // 光标前正好是片段缩写时，Tab 优先展开片段，否则缩进/反缩进
                if (!(!_shiftDown && TryExpandSnippet()))
                {
                    if (_shiftDown) Unindent(); else InsertIndent();
                }
            }
            return;
        }
        switch (e.Key)
        {
            case Windows.System.VirtualKey.Down:
                _sel = (_sel + 1) % _items.Count;
                HighlightSelection();
                e.Handled = true;
                break;
            case Windows.System.VirtualKey.Up:
                _sel = (_sel - 1 + _items.Count) % _items.Count;
                HighlightSelection();
                e.Handled = true;
                break;
            case Windows.System.VirtualKey.Enter:
                AcceptCompletion();
                e.Handled = true;
                _echo = '\n'; _echoAt = SelPos;   // Enter 是字符键：防内核重放换行
                break;
            case Windows.System.VirtualKey.Tab:
                AcceptCompletion();
                e.Handled = true;
                break;
            case Windows.System.VirtualKey.Escape:
                HidePopup();
                HideHint();
                e.Handled = true;
                break;
        }
        // 焦点在弹窗层时按了其它键：把焦点交还编辑框，避免键盘"失联"
        if (!e.Handled && sender is FrameworkElement snd && !ReferenceEquals(snd, ActiveCore()))
            FocusEd();
    }

    FrameworkElement ActiveCore() => _rich ? _re : _tb;

    void AcceptCompletion()
    {
        if (_sel >= _items.Count || _items.Count == 0) return;
        var word = _items[_sel];
        int caret = SelPos;
        int start = Math.Max(0, caret - _prefix.Length);

        // 全程屏蔽事件重入：替换过程不得触发收起/重弹，完成后手动同步
        _accepting = true;
        _syncing = true;
        try
        {
            Sel(start, _prefix.Length);
            SelTextRaw = word;
            Sel(start + word.Length, 0);
        }
        finally { _syncing = false; _accepting = false; }

        HidePopup();
        FocusEd();
        ScheduleRecolor();
        Modified?.Invoke(this, EventArgs.Empty);
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }
}
