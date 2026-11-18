using AntPad.Controls;
using AntPad.Models;
using AntPad.Services;
using AntPad.Syntax;
using AntPad.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.Windows.AppLifecycle;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Windows.ApplicationModel.Activation;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;
using System.Linq;
using System.Net.Http;
using WinRT.Interop;

namespace AntPad;

public sealed partial class MainWindow : Window, Services.IThemePaintable
{
    sealed class Doc
    {
        public required CodeEditor Editor;
        public required TabViewItem Tab;
        public string? FilePath;
        public Encoding Enc = new UTF8Encoding(false);
        public bool Bom;
        public string Eol = "\r\n";
        public bool Dirty;
        public bool ReadOnly;
        public string Title => FilePath is null ? "无标题" : System.IO.Path.GetFileName(FilePath);
    }

    readonly List<Doc> _docs = new();
    List<string> _recent = new();

    // 写作模式（1.1.0）：预览/大纲面板与每日目标，仅文章语言（Markdown/Fountain）可用
    ArticlePreview? _preview;
    OutlinePanel? _outline;
    bool _previewOn;
    bool _outlineOn;
    int _wordGoal = WritingDoc.DefaultGoal;
    Microsoft.UI.Dispatching.DispatcherQueueTimer? _refreshTimer;
    Doc? Active
    {
        get
        {
            foreach (var d in _docs)
                if (ReferenceEquals(Tabs.SelectedItem, d.Tab)) return d;
            return null;
        }
    }

    // Tao 系列存储规范：最近文件清单也放数据根（默认 D:\TaoPadData\TaoPad）
    static string RecentFile => Path.Combine(Services.TaoPaths.Root, "recent.json");

    public MainWindow()
    {
        InitializeComponent();
        ExposeMenuToUia();
        Title = "TaoPad";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        App.TrackWindow(this);
        Closed += (_, _) => App.UntrackWindow(this);
        BuildLangMenu();
        HookMenuTracing();  // v35：全量菜单项 Click 追踪，供云测定谳 app/脚本侧
        ApplyThemeBrushes();   // 构造后直涂大面（IThemePaintable：构造后涂）

        // 【真凶修复】此前这里给"设置"菜单项挂了编号 188（Ctrl+OEM 逗号）的快捷键。
        // 该键值在框架里没有合法的显示名：点开"工具"菜单、弹出层构建快捷键
        // 文本时，框架当场原生崩溃（同老版 XamlParseException "VirtualKey 188"），
        // 且不经过任何 .NET 异常处理。XAML 具名/数字写法与代码数值写法全部
        // 不合法——OEM 逗号键不适合做菜单快捷键，直接移除。
        // "设置"仍可从 工具→设置… 进入，功能不受影响。

        InitBanner();

        LoadRecent();
        WireFindPanel();
        ThemeService.ThemeApplied += OnThemeApplied;

        Root.DragOver += OnDragOver;
        Root.Drop += OnDrop;

        // 编辑器宿主顶边随标签栏实际高度走
        Tabs.SizeChanged += (_, _) => UpdateEditorHost();

        NewDoc();
        _wordGoal = WritingDoc.LoadGoal();
        ThemeService.Apply(ThemeService.LoadChoice());   // 启动恢复上次主题，默认水墨
        UpdateRecentMenu();
        UpdateTitle();

        // 测试钩子（2026-11-17 老板令）：仅 --testhook 启动时激活，普通
        // 运行零副作用；给云端自动测试一条不依赖 UIA 读层的正文自报通道
        Services.TestHook.Start(DispatcherQueue, SnapshotForTest);
        Services.TestHook.CommandDispatcher = ExecuteTestCommand;
    }

    /// <summary>
    /// 命令下行（1.1.1）：云端 runner 对菜单直呼与键盘通道整段失效已三轮
    /// 实锤，同路连堵按防耗死令换路——测试钩子从「只读自报」升级为
    /// 「可下达命令」。菜单与键盘仍是主路，这里只是 UI 传输失效时的
    /// 兜底，回执字符串随快照返回；仅 --testhook 会话可达，普通用户
    /// 零影响。命令执行发生在 UI 线程（TestHook 保证）。
    /// </summary>
    string ExecuteTestCommand(string command, string? arg)
    {
        switch (command)
        {
            case "snapshot_now":
                DoSnapshotNow();
                return "ok:snapshot";
            case "close_panels":
                if (_previewOn) { PreviewToggle.IsChecked = false; OnPreviewToggle(this, new RoutedEventArgs()); }
                if (_outlineOn) { OutlineToggle.IsChecked = false; OnOutlineToggle(this, new RoutedEventArgs()); }
                return $"closed:preview={!_previewOn},outline={!_outlineOn}";
            case "set_language":
                if (Active is not { } doc) return "ERR no-doc";
                LangDef? lang = null;
                foreach (var l in LangDef.All)
                    if (l.Name == arg) { lang = l; break; }
                if (lang is null) return "ERR lang-not-found:" + arg;
                doc.Editor.SyntaxLanguage = lang;
                UpdateLangChecks();
                UpdateStatus();
                return "ok:" + lang.Name;
            case "paste_clipboard":
                Ed?.Paste();
                return "ok:paste";
            case "type":
                if (Active is not { } docTyped) return "ERR no-doc";
                docTyped.Editor.TypeAtEnd(arg ?? "");
                UpdateStatus();
                return "ok:typed";
            case "trim_tail":
                if (Active is not { } docTrim) return "ERR no-doc";
                return $"ok:trimmed={docTrim.Editor.TrimTailWhitespace()}";
            case "trim_and_items":
                // v46d：清尾+触发+读候选一次成型（原子）。幽灵键流实锤
                // （44257837793）：清尾后下一波重放立即塞回，分步轮询永远
                // 赶不上污染速度；原子化后只要 UI 线程空出一拍就能拿全候选
                if (Active is not { } docTI) return "ERR no-doc";
                docTI.Editor.TrimTailWhitespace();
                return "ok:items=[" + string.Join(",", docTI.Editor.PopupItems) + "]";
            case "hint_probe":
                if (Active is not { } docProbe) return "ERR no-doc";
                return docProbe.Editor.HintProbe();
            case "popup_items":
                // v46k：候选轮询通道。csharp 词表空时弹层走 Roslyn 异步合并
                //（CodeEditor.MaybeShowPopup → EnrichWithRoslynAsync），回调
                // 后才 ShowPopup；测试同步瞬读永远早于回执（44310940578
                // X07 实锤 items=[]）。让测试反复读直到 Roslyn 回执落地
                if (Active is not { } docPI) return "ERR no-doc";
                return "ok:items=[" + string.Join(",", docPI.Editor.PopupItems) + "]";
            default:
                return "ERR unknown-command:" + command;
        }
    }

    void FitEditors()
    {
        UpdateEditorHost();
    }

    static FrameworkElement? FindNamed(DependencyObject root, string name)
    {
        int n = Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChildrenCount(root);
        for (int i = 0; i < n; i++)
        {
            var c = Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChild(root, i);
            if (c is FrameworkElement fe && fe.Name == name) return fe;
            var r = FindNamed(c, name);
            if (r is not null) return r;
        }
        return null;
    }

    // ================= 标签与文档 =================

    Doc NewDoc(string? path = null)
    {
        var editor = new CodeEditor { Visibility = Visibility.Collapsed };
        EditorHost.Children.Add(editor);
        // 标签只做页签，编辑器统一放在 EditorHost 铺满内容区
        var tab = new TabViewItem { Header = "无标题", IsClosable = true };
        Tabs.TabItems.Add(tab);
        Tabs.SelectedItem = tab;

        var doc = new Doc { Editor = editor, Tab = tab };
        _docs.Add(doc);
        ShowActiveEditor();

        editor.Modified += (_, _) => SetDirty(doc, true);
        editor.Modified += (_, _) => { UpdateStatus(); ScheduleArticleRefresh(); };
        editor.StatusChanged += (_, _) => UpdateStatus();

        if (path is not null)
        {
            // 异步加载：失败自动收回标签，不阻塞界面也不闪退
            _ = LoadFileAsync(doc, path);
        }
        UpdateTitle();
        UpdateEditorHost();
        return doc;
    }

    /// <summary>只显示当前选中标签对应的编辑器。</summary>
    void ShowActiveEditor()
    {
        var act = Active;
        foreach (var d in _docs)
            d.Editor.Visibility = ReferenceEquals(d, act)
                ? Visibility.Visible : Visibility.Collapsed;
    }

    /// <summary>编辑器宿主顶部留出标签栏高度，其余铺满；写作面板打开时编辑器给面板让位。</summary>
    void UpdateEditorHost()
    {
        double strip = 44;
        if (FindNamed(Tabs, "TabListView") is { } lv && lv.ActualHeight > 10) strip = lv.ActualHeight + 2;
        // 只有当前文档是文章语言时才让位：面板隐藏（如切到纯文本）时同步收让位（1.1.0 审查）
        bool article = Active is { } a && IsArticle(a.Editor.SyntaxLanguage);
        double left = _outlineOn && article ? OutlinePanelWidth : 0;
        double right = _previewOn && article ? PreviewPanelWidth : 0;
        foreach (var d in _docs)
            d.Editor.Margin = new Thickness(left, strip, right, 0);
    }

    const double PreviewPanelWidth = 420;
    const double OutlinePanelWidth = 260;

    static bool IsArticle(LangDef lang) => lang.Id is "markdown" or "fountain";

    /// <summary>内容变化后的延迟刷新：400ms 内连续击键只渲染一次，避免大文档每键全量重排。</summary>
    void ScheduleArticleRefresh()
    {
        if (!_previewOn && !_outlineOn) return;
        if (_refreshTimer is null)
        {
            _refreshTimer = DispatcherQueue.CreateTimer();
            _refreshTimer.Tick += RefreshTick;   // 只订阅一次，重挂会累积回呼
        }
        _refreshTimer.Interval = TimeSpan.FromMilliseconds(400);
        _refreshTimer.Stop();
        _refreshTimer.Start();
    }

    void RefreshTick(Microsoft.UI.Dispatching.DispatcherQueueTimer? sender, object args)
    {
        _refreshTimer?.Stop();
        RefreshArticlePanels();
    }

    /// <summary>把当前文档正文渲染进打开的预览/大纲面板；面板关闭时不动。</summary>
    void RefreshArticlePanels()
    {
        if (Active is not { } doc) return;
        string id = doc.Editor.SyntaxLanguage.Id;
        if (_preview is { } p && p.Visibility == Visibility.Visible)
            p.Render(doc.Editor.Text, id);
        if (_outline is { } o && o.Visibility == Visibility.Visible)
            o.Refresh(id switch
            {
                "fountain" => WritingDoc.FountainOutline(doc.Editor.Text),
                "markdown" => WritingDoc.MarkdownOutline(doc.Editor.Text),
                _ => new(),
            });
    }

    void SetDirty(Doc doc, bool dirty)
    {
        if (doc.Dirty == dirty) return;
        doc.Dirty = dirty;
        doc.Tab.Header = dirty ? "● " + doc.Title : doc.Title;
        UpdateTitle();
    }

    async Task CloseDocAsync(Doc doc)
    {
        if (doc.Dirty)
        {
            var dlg = new ContentDialog
            {
                Title = "保存更改？",
                Content = $"“{doc.Title}”有未保存的更改。",
                PrimaryButtonText = "保存",
                SecondaryButtonText = "不保存",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Primary,
                XamlRoot = Content.XamlRoot,
            };
            var r = await ShowDialogSafe(dlg);
            if (r is null) return;   // 弹窗被占用/失败：当作取消，不关标签
            if (r == ContentDialogResult.Primary) { if (!await SaveDocAsync(doc, false)) return; }
            else if (r == ContentDialogResult.None) return;
        }
        Tabs.TabItems.Remove(doc.Tab);
        EditorHost.Children.Remove(doc.Editor);
        _docs.Remove(doc);
        ShowActiveEditor();
        if (_docs.Count == 0) NewDoc();
        UpdateTitle();
    }

    // ================= 文件操作 =================

    /// <summary>冷启动：解析进程命令行中的文件路径（双击关联文件时系统传入）。</summary>
    public static List<string> ArgsFromCommandLine()
    {
        var list = new List<string>();
        var a = Environment.GetCommandLineArgs();
        for (int i = 1; i < a.Length; i++)
            if (File.Exists(a[i])) list.Add(Path.GetFullPath(a[i]));
        return list;
    }

    /// <summary>运行中再激活：从激活参数里提取文件路径。</summary>
    public static List<string> PathsFromActivation(AppActivationArguments? a)
    {
        var list = new List<string>();
        if (a?.Data is ICommandLineActivatedEventArgs cli &&
            cli.Operation?.Arguments is { Length: > 0 } line)
        {
            foreach (Match m in Regex.Matches(line, "\"([^\"]+)\"|(\\S+)"))
            {
                string raw = m.Groups[1].Success ? m.Groups[1].Value : m.Groups[2].Value;
                string full = Path.IsPathRooted(raw) ? raw : Path.GetFullPath(raw);
                if (File.Exists(full)) list.Add(full);
            }
        }
        return list;
    }

    /// <summary>打开一批文件：已开过的切到对应标签；首个空文档会被复用替换。</summary>
    public void OpenPaths(IEnumerable<string> paths)
    {
        bool opened = false;
        foreach (var p in paths)
        {
            var exist = _docs.FirstOrDefault(d =>
                string.Equals(d.FilePath, p, StringComparison.OrdinalIgnoreCase));
            if (exist is not null)
            {
                Tabs.SelectedItem = exist.Tab;
                opened = true;
                continue;
            }

            // 只剩一个未改动的空文档时，直接替换掉它
            if (_docs.Count == 1 && _docs[0] is { } only &&
                !only.Dirty && only.FilePath is null && only.Editor.Text.Length == 0)
            {
                Tabs.TabItems.Remove(only.Tab);
                _docs.Remove(only);
            }

            NewDoc(p);
            opened = true;
        }
        if (opened)
        {
            UpdateTitle();
            Activate();
        }
    }

    async Task LoadFileAsync(Doc doc, string path)
    {
        try
        {
            var fi = new FileInfo(path);
            if (!fi.Exists) { ShowMessage("无法打开文件", $"文件不存在：{path}"); RemoveFailedDoc(doc); return; }
            // 超大文件走只读快看通道（v39.3 老板拍板的分治方案）：
            // 编辑器管 ≤50MB 可编辑；超限不拒开，弹独立快看窗按屏解码
            if (fi.Length > 50_000_000)
            {
                RemoveFailedDoc(doc);   // 先收掉空标签，避免快看窗背后留空白页
                new Views.HugeFileViewer(path).Activate();
                return;
            }
            // 读取放后台线程，几 MB 的文件也不占用界面
            byte[] bytes = await Task.Run(() => File.ReadAllBytes(path));
            var (enc, bom) = EncodingHelper.Detect(bytes);
            string text = enc.GetString(bytes) ?? "";
            // 去 BOM 字符
            if (text.Length > 0 && text[0] == '\uFEFF') text = text[1..];

            doc.FilePath = path;
            doc.Enc = enc;
            doc.Bom = bom;
            doc.Editor.Text = text;
            // v46j（老板令「快点落地能用」2026-11-18）：超大档案不做全量着色——
            // X15 四班实锤：30MB 着色档案的着色批次把界面线程拖到分钟级，快照
            // 回不来=界面冻死。阈值以上按纯文本开，先回来能用；着色只服务小档案。
            doc.Editor.SyntaxLanguage = text.Length > 2_000_000 ? null : LangDef.FromFileName(path);
            doc.Eol = DetectEol(text);
            // v39.2（老板令）：撤 2MB 只读护栏——大文件可编辑可保存；
            // 50MB 打开硬上限保留（渲染内存安全线）。
            // v39.4（老板拍板 2026-11-18）：带只读属性的档案打开即挡编辑、
            // 状态栏标（只读）——防「改半天保存才炸」；确要改动走另存为。
            doc.ReadOnly = fi.IsReadOnly;
            doc.Editor.IsReadOnly = fi.IsReadOnly;
            SetDirty(doc, false);
            doc.Tab.Header = doc.Title;
            PushRecent(path);
            UpdateStatus();
            UpdateEncChecks();
            UpdateEolChecks();
            UpdateLangChecks();
            SetupWatcher(doc);
        }
        catch (Exception ex)
        {
            // 文件被占用/无权限/编码异常等一律不闪退：关掉空标签并说明原因
            RemoveFailedDoc(doc);
            ShowMessage("无法打开文件", $"{System.IO.Path.GetFileName(path)}：{ex.Message}");
        }
    }

    /// <summary>打开失败时移除刚建的空标签，不留困惑用户的空白页。</summary>
    void RemoveFailedDoc(Doc doc)
    {
        try
        {
            Tabs.TabItems.Remove(doc.Tab);
            EditorHost.Children.Remove(doc.Editor);
            _docs.Remove(doc);
            ShowActiveEditor();
            if (_docs.Count == 0) NewDoc();
        }
        catch { /* 清理失败不影响主界面 */ }
    }

    // ================= 文件监视（外部修改提醒） =================

    FileSystemWatcher? _watcher;
    string? _watchPath;
    bool _suppressWatch;

    void SetupWatcher(Doc doc)
    {
        _watcher?.Dispose();
        _watcher = null;
        _watchPath = doc.FilePath;
        if (_watchPath is null || !File.Exists(_watchPath)) return;
        try
        {
            var w = new FileSystemWatcher
            {
                Path = System.IO.Path.GetDirectoryName(_watchPath)!,
                Filter = System.IO.Path.GetFileName(_watchPath),
                EnableRaisingEvents = true,
                NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.Size,
            };
            w.Changed += OnWatchedFileChanged;
            _watcher = w;
        }
        catch { /* 监视失败不影响编辑 */ }
    }

    void OnWatchedFileChanged(object sender, FileSystemEventArgs e)
    {
        if (_suppressWatch) return;
        // FileSystemWatcher 回调走线程池：直接摸 Tabs.SelectedItem 是跨线程 XAML
        // 访问，必炸 COMException（云测 crash.log 实锤：0xE0434352 原生崩溃，
        // 退出链被掐断→进程永驻；外部修改对话框被吞→X17 挂账）。整段改投 UI 线程。
        DispatcherQueue.TryEnqueue(() =>
        {
            if (_suppressWatch) return;
            var doc = Active;
            if (doc is null || doc.FilePath is null || !_watchPath!.Equals(doc.FilePath, StringComparison.OrdinalIgnoreCase)) return;
            TraceLog.Write($"外部修改：检测到 {doc.Title}");
            _ = HandleExternalChangeAsync(doc);
        });
    }

    async Task HandleExternalChangeAsync(Doc doc)
    {
        if (Active != doc || doc.FilePath is null) return;
        if (doc.Dirty)
        {
            doc.Tab.Header = doc.Title + "（外部已修改）";
            TraceLog.Write($"外部修改：未保存仅提醒 {doc.Title}");
            return;   // 有未保存改动不打断，仅提醒
        }
        var dlg = new ContentDialog
        {
            Title = "文件已在外部修改",
            Content = "「" + doc.Title + "」在磁盘上被其他程序修改过。重新加载将丢弃当前编辑器内容。",
            PrimaryButtonText = "重新加载",
            CloseButtonText = "暂不",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = Content.XamlRoot,
        };
        var choice = await ShowDialogSafe(dlg);
        TraceLog.Write($"外部修改：对话框已确认 choice={choice}");
        if (choice == ContentDialogResult.Primary)
        {
            _suppressWatch = true;
            try { await LoadFileAsync(doc, doc.FilePath); }
            finally { _suppressWatch = false; }
        }
    }

    // ================= 设置页 / 导出 / 更新检查 =================

    /// <summary>菜单打开追踪：记录点开的菜单名，崩溃前的最后一条即案发现场。</summary>
    void OnMenuTapped(object sender, Microsoft.UI.Xaml.Input.TappedRoutedEventArgs e)
    {
        var name = sender is Microsoft.UI.Xaml.Controls.MenuBarItem m ? m.Title : "?";
        TraceLog.Write($"点开菜单：{name}");
    }

    /// <summary>菜单按下追踪：比 Tapped 更早触发，弹出过程崩溃前也能留下记录。</summary>
    void OnMenuPressed(object sender, Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e)
    {
        var name = sender is Microsoft.UI.Xaml.Controls.MenuBarItem m ? m.Title : "?";
        TraceLog.Write($"按下菜单：{name}");
    }

    // v35 菜单项点击追踪：区分"脚本没点到"与"点到了但 app 没响应"的定谳依据。
    readonly HashSet<Microsoft.UI.Xaml.Controls.MenuFlyoutItemBase> _menuTraceHooked = new();

    /// <summary>挂接全部菜单项的 Click 记录：含子菜单，任何一次真实激活都会留下 trace。</summary>
    void HookMenuTracing()
    {
        try { HookMenuItems(); }
        catch (Exception ex) { TraceLog.Write($"菜单追踪挂接失败：{ex.Message}"); }
    }

    void HookMenuItems()
    {
        foreach (var mb in MenuBarRoot.Items.OfType<Microsoft.UI.Xaml.Controls.MenuBarItem>())
            foreach (var it in mb.Items) HookFlyout(it);
    }

    void HookFlyout(Microsoft.UI.Xaml.Controls.MenuFlyoutItemBase item)
    {
        if (item == null || !_menuTraceHooked.Add(item)) return;
        if (item is Microsoft.UI.Xaml.Controls.MenuFlyoutSubItem sub)
        {
            foreach (var c in sub.Items) HookFlyout(c);
        }
        else if (item is Microsoft.UI.Xaml.Controls.MenuFlyoutItem mi)
        {
            mi.Click += (s, e) => TraceLog.Write($"菜单项：{mi.Text}");
        }
    }

    async void OnSettings(object sender, RoutedEventArgs e)
    {
        TraceLog.Write("设置：入口（主窗口内弹窗模式）");
        try
        {
        TraceLog.Write("设置：开始创建控件");
        var wrap = new ToggleSwitch { OnContent = "开", OffContent = "关", IsOn = Ed?.WordWrap == true };
        var lineNo = new ToggleSwitch { OnContent = "开", OffContent = "关", IsOn = Ed?.ShowLineNumbers != false };
        var theme = new ComboBox { MinWidth = 160 };
        foreach (var n in new[] { "水墨", "天青", "墨夜" })
            theme.Items.Add(n);
        theme.SelectedIndex = ThemeService.Current switch
        {
            AppTheme.Sky => 1, AppTheme.Night => 2, _ => 0,
        };
        var root = new StackPanel { Spacing = 12, Children =
        {
            new TextBlock { Text = "编辑" },
            wrap,
            lineNo,
            new TextBlock { Text = "主题" },
            theme,
            // 数据位置展示（1.0.10）：真机用户可直接核验 D 盘落地情况；
            // 文字可选中，拖选即可复制路径
            new TextBlock { Text = "数据位置（配置与日志保存在此目录下）" },
            new TextBlock
            {
                Text = TaoPaths.Root,
                TextWrapping = TextWrapping.Wrap,
                IsTextSelectionEnabled = true,
                FontSize = 12,
                Opacity = 0.8,
            },
        } };
        wrap.Header = "自动换行";
        lineNo.Header = "显示行号";

        var dlg = new ContentDialog
        {
            Title = $"设置（当前版本 v{AppVersion}）",
            Content = root,
            PrimaryButtonText = "应用",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = Content.XamlRoot,
        };
        TraceLog.Write("设置：控件创建完成，准备弹出对话框");
        if (await ShowDialogSafe(dlg) != ContentDialogResult.Primary) return;
        TraceLog.Write("设置：对话框已确认");

        if (Ed is { } ed)
        {
            ed.WordWrap = wrap.IsOn;
            ed.ShowLineNumbers = lineNo.IsOn;
        }
        WrapToggle.IsChecked = wrap.IsOn;
        LineNoToggle.IsChecked = lineNo.IsOn;
        switch (theme.SelectedIndex)
        {
            case 0: ThemeService.Apply(AppTheme.Ink); ThemeService.SaveChoice(AppTheme.Ink); break;
            case 1: ThemeService.Apply(AppTheme.Sky); ThemeService.SaveChoice(AppTheme.Sky); break;
            case 2: ThemeService.Apply(AppTheme.Night); ThemeService.SaveChoice(AppTheme.Night); break;
        }
        UpdateThemeChecks();
        }
        catch (Exception ex)
        {
            // 菜单入口兜底：任何异常只提示+落日志，绝不闪退
            CrashLog.Report(ex, "菜单「设置」");
            InfoTip($"设置打开出错，已拦截：{ex.Message}");
        }
    }

    async void OnExportPrintableHtml(object sender, RoutedEventArgs e)
    {
        try { await ExportPrintableHtmlCore(); }
        catch (Exception ex) { CrashLog.Report(ex, "导出可打印HTML"); InfoTip("导出失败，已记录日志。"); }
    }

    async Task ExportPrintableHtmlCore()
    {
        var doc = Active;
        if (doc is null) return;
        var picker = new FileSavePicker();
        InitializeWithWindow.Initialize(picker, Hwnd);
        picker.SuggestedFileName = System.IO.Path.GetFileNameWithoutExtension(doc.Title) + "-可打印";
        picker.FileTypeChoices.Add("HTML", new List<string> { ".html" });
        var file = await picker.PickSaveFileAsync();
        if (file is null) return;

        var sb = new StringBuilder(@"<!DOCTYPE html>
<html lang=""zh""><head><meta charset=""utf-8""><title>");
        sb.Append(System.Security.SecurityElement.Escape(doc.Title));
        sb.Append(@"</title><style>
  body { font-family: Consolas, 'Courier New', monospace; font-size: 10pt; margin: 2cm; }
  pre { white-space: pre-wrap; word-break: break-all; line-height: 1.35; margin: 0; }
  .ln { color: #999; display: inline-block; width: 3.2em; user-select: none; }
  @page { margin: 2cm; }
  @media print { .no-print { display: none; } }
</style></head><body>
<p class=""no-print"">提示：用浏览器「打印 → 另存为 PDF」即可生成 PDF。</p>
<pre>");
        int line = 0;
        foreach (var raw in doc.Editor.Text.Split('\n'))
        {
            line++;
            sb.Append("<span class=\"ln\">").Append(line).Append("</span>");
            sb.Append(System.Security.SecurityElement.Escape(raw.TrimEnd('\r'))).Append('\n');
        }
        sb.Append("</pre></body></html>");

        try
        {
            File.WriteAllText(file.Path, sb.ToString(), new UTF8Encoding(true));
            InfoTip("已导出可打印 HTML——用浏览器打开后「打印 → 另存为 PDF」。");
        }
        catch (Exception ex)
        {
            // 磁盘满/只读位置/文件被占用都不闪退，说明原因即可
            ShowMessage("导出失败", $"{System.IO.Path.GetFileName(file.Path)}：{ex.Message}");
        }
    }

    Microsoft.UI.Xaml.Controls.Border? _banner;
    Microsoft.UI.Xaml.Controls.TextBlock? _bannerText;
    Microsoft.UI.Xaml.DispatcherTimer? _bannerHide;

    /// <summary>非模态横幅提示：替代 ContentDialog 弹窗。对话框在部分机器上
    /// 有原生层崩溃风险，横幅是纯普通控件，最保守最稳的提示方式。</summary>
    void InfoTip(string msg)
    {
        TraceLog.Write($"提示：{msg}");
        try
        {
            if (_banner is null || _bannerText is null) return;
            _bannerText.Text = msg;
            _banner.Visibility = Visibility.Visible;
            _bannerHide?.Stop();
            _bannerHide?.Start();
        }
        catch { /* 提示失败不影响运行 */ }
    }

    /// <summary>在主界面顶部叠一条提示横幅（跟随主题底色的普通控件）。</summary>
    void InitBanner()
    {
        _bannerText = new Microsoft.UI.Xaml.Controls.TextBlock
        {
            TextWrapping = Microsoft.UI.Xaml.TextWrapping.Wrap,
            Foreground = new Microsoft.UI.Xaml.Media.SolidColorBrush(Microsoft.UI.Colors.White),
        };
        _banner = new Microsoft.UI.Xaml.Controls.Border
        {
            Child = _bannerText,
            Padding = new Thickness(16, 9, 16, 9),
            Background = new Microsoft.UI.Xaml.Media.SolidColorBrush(Windows.UI.Color.FromArgb(235, 0x33, 0x33, 0x33)),
            Visibility = Visibility.Collapsed,
            VerticalAlignment = VerticalAlignment.Top,
        };
        Root.Children.Add(_banner);
        Microsoft.UI.Xaml.Controls.Grid.SetRow(_banner, 2);

        _bannerHide = new Microsoft.UI.Xaml.DispatcherTimer { Interval = TimeSpan.FromSeconds(5) };
        _bannerHide.Tick += (_, _) =>
        {
            _bannerHide?.Stop();
            if (_banner is not null) _banner.Visibility = Visibility.Collapsed;
        };
    }

    /// <summary>非致命异常提示（供 App 全局兜底调用）：落日志+温和提示，程序继续运行。</summary>
    public void NotifyNonFatal(Exception ex, string where)
    {
        CrashLog.Report(ex, where);
        InfoTip("出现一个错误，已拦截并记录，程序继续运行。");
    }

    static string DetectEol(string text)
    {
        int crlf = text.IndexOf("\r\n", StringComparison.Ordinal) >= 0 ? 1 : 0;
        int lf = 0, cr = 0;
        for (int i = 0; i < text.Length; i++)
        {
            if (text[i] == '\n') lf++;
            else if (text[i] == '\r') cr++;
        }
        if (crlf > 0 && crlf * 2 >= lf) return "\r\n";
        if (lf > cr) return "\n";
        if (cr > lf) return "\r";
        return "\r\n";
    }

    async Task<bool> SaveDocAsync(Doc doc, bool saveAs)
    {
        string? path = doc.FilePath;
        if (saveAs || path is null)
        {
            path = await PickSaveFileAsync(doc.Title);
            if (path is null) return false;
            doc.FilePath = path;
        }
        try
        {
            // 先写临时文件再替换：任何中断（断电/崩溃）都不会损坏原文件内容
            var tmp = path + ".taopad.tmp";
            using (var f = new FileStream(tmp, FileMode.Create, FileAccess.Write))
            {
                if (doc.Bom)
                {
                    var bom = doc.Enc.GetPreamble();
                    if (bom.Length > 0) f.Write(bom);
                }
                byte[] body = doc.Enc.GetBytes(doc.Editor.Text);
                f.Write(body);
            }
            File.Move(tmp, path, true);
            doc.FilePath = path;
            doc.Tab.Header = doc.Title;
            // 另存为后按新文件属性重估只读：只读档另存新路径即恢复可编辑
            try { doc.ReadOnly = new FileInfo(path).IsReadOnly; }
            catch { /* 属性读不到按可编辑处理，不拦保存 */ }
            doc.Editor.IsReadOnly = doc.ReadOnly;
            // 按新扩展名自动切换着色语言：另存为 .sql 后立即按 SQL 着色，
            // 不再沿用打开时的旧语言（修 test.sql 显示 C# 一类问题）
            // v46j 同源护栏：超大档案保存后不重做着色批次（会把界面拖死），
            // 与打开侧阈值一致。
            var langByExt = AntPad.Syntax.LangDef.FromFileName(path);
            if (doc.Editor.Text.Length > 2_000_000)
            {
                doc.Editor.SyntaxLanguage = null;
            }
            else if (!ReferenceEquals(doc.Editor.SyntaxLanguage, langByExt))
            {
                doc.Editor.SyntaxLanguage = langByExt;
                UpdateLangChecks();
            }
            SetDirty(doc, false);
            PushRecent(path);
            UpdateRecentMenu();
            UpdateTitle();
            UpdateStatus();
            // 写作模式自动快照：文章语言保存成功即留底，保留最近 20 份
            if (IsArticle(doc.Editor.SyntaxLanguage))
            {
                try
                {
                    WritingDoc.SaveSnapshot(doc.FilePath, doc.Editor.Text, DateTimeOffset.Now);
                    WritingDoc.TrimSnapshots(doc.FilePath, WritingDoc.SnapshotKeep);
                }
                catch (Exception snapEx) { CrashLog.Report(snapEx, "保存自动快照"); }
            }
            return true;
        }
        catch (Exception ex)
        {
            ShowMessage("保存失败", ex.Message);
            return false;
        }
    }

    void OpenPath(string path)
    {
        foreach (var d in _docs)
        {
            if (string.Equals(d.FilePath, path, StringComparison.OrdinalIgnoreCase))
            {
                Tabs.SelectedItem = d.Tab;
                return;
            }
        }
        NewDoc(path);
    }

    // ================= 文件选择器 =================

    IntPtr Hwnd => WindowNative.GetWindowHandle(this);

    async Task<string?> PickOpenFileAsync()
    {
        try
        {
            var picker = new FileOpenPicker();
            InitializeWithWindow.Initialize(picker, Hwnd);
            picker.ViewMode = PickerViewMode.List;
            picker.FileTypeFilter.Add("*");
            // 同保存框：必须 await，阻塞等待会卡死界面
            var file = await picker.PickSingleFileAsync();
            return file?.Path;
        }
        catch (Exception ex)
        {
            // 打开框失败（如系统选择器被策略禁用）不能带崩主程序
            CrashLog.Report(ex, "文件打开选择器");
            InfoTip("打不开文件选择窗口，请改用拖放文件到窗口的方式打开。");
            return null;
        }
    }

    async Task<string?> PickSaveFileAsync(string suggestedName)
    {
        var picker = new FileSavePicker();
        InitializeWithWindow.Initialize(picker, Hwnd);
        picker.SuggestedFileName = suggestedName;
        // 不能用阻塞 GetResult() 等选择器：会卡死界面消息循环导致闪退，必须 await
        picker.FileTypeChoices.Add("所有文件", new List<string> { "." });
        picker.FileTypeChoices.Add("文本文件", new List<string> { ".txt" });
        try
        {
            var file = await picker.PickSaveFileAsync();
            return file?.Path;
        }
        catch (Exception ex)
        {
            ShowMessage("无法打开保存窗口", ex.Message);
            return null;
        }
    }

    // ================= 最近文件 =================

    void LoadRecent()
    {
        try
        {
            if (File.Exists(RecentFile))
                _recent = JsonSerializer.Deserialize<List<string>>(File.ReadAllText(RecentFile)) ?? new();
        }
        catch { _recent = new(); }
    }

    void PushRecent(string path)
    {
        _recent.RemoveAll(p => string.Equals(p, path, StringComparison.OrdinalIgnoreCase));
        _recent.Insert(0, path);
        if (_recent.Count > 10) _recent.RemoveRange(10, _recent.Count - 10);
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(RecentFile)!);
            File.WriteAllText(RecentFile, JsonSerializer.Serialize(_recent));
        }
        catch { }
        UpdateRecentMenu();
    }

    void UpdateRecentMenu()
    {
        RecentMenu.Items.Clear();
        if (_recent.Count == 0)
        {
            RecentMenu.Items.Add(new MenuFlyoutItem { Text = "（空）", IsEnabled = false });
            return;
        }
        foreach (var p in _recent)
        {
            var item = new MenuFlyoutItem { Text = Path.GetFileName(p) };
            string path = p;
            item.Click += (_, _) => OpenPath(path);
            RecentMenu.Items.Add(item);
        }
    }

    // ================= 查找替换 =================

    void WireFindPanel()
    {
        FindPanel.FindNextRequested += () => DoFind(false);
        FindPanel.FindPrevRequested += () => DoFind(true);
        FindPanel.ReplaceRequested += () => DoReplace();
        FindPanel.ReplaceAllRequested += () => DoReplaceAll();
        FindPanel.CloseRequested += () => { FindPanel.Hide(); Active?.Editor.ClearSearch(); };
    }

    FindReplacePanel? Panel => FindPanel;
    void DoFind(bool backwards)
    {
        var doc = Active;
        if (doc is null || FindPanel.Pattern.Length == 0) return;
        if (FindPanel.Options.Regex && !SearchEngine.IsValidRegex(FindPanel.Pattern))
        {
            FindPanel.SetResult("正则表达式无效");
            return;
        }
        bool ok = doc.Editor.FindNext(FindPanel.Pattern, FindPanel.Options, backwards);
        FindPanel.SetResult(ok ? "已找到匹配" : "未找到匹配");
    }

    void DoReplace()
    {
        var doc = Active;
        if (doc is null) return;
        bool replaced = doc.Editor.ReplaceCurrent(FindPanel.Pattern, FindPanel.Replacement, FindPanel.Options);
        if (!replaced) doc.Editor.FindNext(FindPanel.Pattern, FindPanel.Options, false);
        FindPanel.SetResult(replaced ? "已替换 1 处" : "未找到匹配");
        int count = doc.Editor.CountMatches(FindPanel.Pattern, FindPanel.Options);
        FindPanel.SetResult($"共 {count} 处匹配");
    }

    void DoReplaceAll()
    {
        var doc = Active;
        if (doc is null) return;
        int count = doc.Editor.ReplaceAll(FindPanel.Pattern, FindPanel.Replacement, FindPanel.Options);
        int remain = doc.Editor.CountMatches(FindPanel.Pattern, FindPanel.Options);
        FindPanel.SetResult($"已替换 {count} 处，剩余 {remain} 处");
    }

    // ================= 在文件中查找 =================

    sealed class FindHit
    {
        public string Path = "";
        public int Line;
        public string Display = "";
        public override string ToString() => Display;
    }

    async void OnFindInFiles(object sender, RoutedEventArgs e)
    {
        try
        {
        var dirBox = new TextBox { PlaceholderText = "文件夹（默认当前文件所在目录）" };
        var patBox = new TextBox { PlaceholderText = "查找内容（勾选正则时按正则解释）" };
        var reCheck = new CheckBox { Content = "正则", MinWidth = 0 };
        var caseCheck = new CheckBox { Content = "区分大小写", MinWidth = 0 };
        var status = new TextBlock { Opacity = 0.75, TextWrapping = TextWrapping.Wrap };
        var results = new ListView { Height = 300, SelectionMode = ListViewSelectionMode.Single, IsItemClickEnabled = true };
        var optsRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 16, Children = { reCheck, caseCheck } };
        var root = new StackPanel { Spacing = 10, MinWidth = 560, Children = { dirBox, patBox, optsRow, status, results } };

        dirBox.Text = System.IO.Path.GetDirectoryName(Active?.FilePath ?? "") ?? "";

        var dlg = new ContentDialog
        {
            Title = "在文件中查找",
            Content = root,
            CloseButtonText = "关闭",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = Content.XamlRoot,
        };

        async void RunScan()
        {
            string pat = patBox.Text;
            string dir = dirBox.Text.Trim();
            if (pat.Length == 0 || dir.Length == 0 || !System.IO.Directory.Exists(dir))
            {
                status.Text = "请填写有效的文件夹和查找内容";
                return;
            }
            bool useRe = reCheck.IsChecked == true;
            if (useRe && !SearchEngine.IsValidRegex(pat)) { status.Text = "正则表达式无效"; return; }

            status.Text = "查找中…";
            results.Items.Clear();
            var o = new FindOpts(useRe, caseCheck.IsChecked == true, false);
            try
            {
                var hits = await Task.Run(() => ScanFiles(dir, pat, o));
                foreach (var h in hits) results.Items.Add(h);
                status.Text = hits.Count == 0 ? "未找到匹配"
                    : $"共 {hits.Count} 处匹配——单击结果直接打开文件对应行";
            }
            catch (Exception ex) { status.Text = "查找失败：" + ex.Message; }
        }

        void OpenHit(FindHit h)
        {
            dlg.Hide();
            OpenPaths(new[] { h.Path });
            try { Ed?.GoToLine(h.Line); } catch { /* 跳转失败不致命 */ }
        }

        patBox.KeyDown += (_, ke) => { if (ke.Key == Windows.System.VirtualKey.Enter) RunScan(); };
        results.ItemClick += (_, ie) => { if (ie.ClickedItem is FindHit h) OpenHit(h); };

        await ShowDialogSafe(dlg);
        }
        catch (Exception ex)
        {
            // 菜单入口兜底：任何异常只提示+落日志，绝不闪退
            CrashLog.Report(ex, "菜单「在文件中查找」");
            InfoTip($"在文件中查找出错，已拦截：{ex.Message}");
        }
    }

    /// <summary>扫描目录下文本文件；跳过构建目录与超大文件，最多返回 300 条命中。</summary>
    static List<FindHit> ScanFiles(string dir, string pat, FindOpts o)
    {
        var exts = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            ".txt", ".md", ".markdown", ".json", ".xml", ".html", ".htm", ".css", ".js", ".ts",
            ".jsx", ".tsx", ".cs", ".c", ".h", ".cpp", ".hpp", ".py", ".sql", ".java", ".go",
            ".rs", ".php", ".rb", ".log", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml",
            ".csv", ".xaml", ".bat", ".ps1", ".sh",
        };
        var skip = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        { "bin", "obj", ".git", ".vs", "node_modules", ".idea", "out", "packages" };
        var cmp = o.CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        Regex? re = o.Regex ? new Regex(pat, o.CaseSensitive ? RegexOptions.None : RegexOptions.IgnoreCase) : null;

        var list = new List<FindHit>();
        int files = 0;
        // 逐目录手动遍历：单个目录无权限只跳过该目录，
        // 不会像 AllDirectories 那样一个异常毁掉整次查找
        var pending = new Stack<string>();
        pending.Push(dir);
        while (pending.Count > 0 && list.Count < 300 && files < 3000)
        {
            string cur;
            try { cur = pending.Pop(); }
            catch { break; }

            IEnumerable<string> subFiles, subDirs;
            try
            {
                subFiles = Directory.EnumerateFiles(cur, "*");
                subDirs = Directory.EnumerateDirectories(cur);
            }
            catch (UnauthorizedAccessException) { continue; }   // 无权限：跳过
            catch (IOException) { continue; }                   // 路径失效：跳过

            foreach (var d in subDirs) pending.Push(d);

            foreach (var f in subFiles)
            {
                if (list.Count >= 300 || files >= 3000) break;
                var segs = f.Split(System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar);
                bool skipIt = false;
                foreach (var s in segs) if (skip.Contains(s)) { skipIt = true; break; }
                if (skipIt) continue;
                if (!exts.Contains(System.IO.Path.GetExtension(f))) continue;
                var fi = new FileInfo(f);
                if (fi.Length > 2_000_000) continue;

                string text;
                try { text = new UTF8Encoding(false, true).GetString(File.ReadAllBytes(f)); }
                catch
                {
                    try { text = Encoding.GetEncoding("GBK").GetString(File.ReadAllBytes(f)); }
                    catch { continue; }
                }
                files++;

                int lineNo = 0;
                foreach (var line in text.Split('\n'))
                {
                    lineNo++;
                    bool hit = re is not null ? re.IsMatch(line) : line.IndexOf(pat, cmp) >= 0;
                    if (!hit) continue;
                    list.Add(new FindHit
                    {
                        Path = f,
                        Line = lineNo,
                        Display = System.IO.Path.GetFileName(f) + "  " + lineNo + ":  " + line.Trim(),
                    });
                    if (list.Count >= 300) break;
                }
            }
        }
        return list;
    }

    // ================= UI 刷新 =================

    void UpdateTitle()
    {
        var doc = Active;
        string name = doc is null ? "" : (doc.Dirty ? "● " : "") + doc.Title + " - ";
        // 版本号上屏：一眼可辨当前跑的是哪个版，避免"新包装了没重建还在跑旧版"误判
        TitleText.Text = name + "TaoPad " + AppVersion;
        Title = name + "TaoPad " + AppVersion;
    }

    /// <summary>界面展示用版本号；与安装包文件名保持一致。</summary>
    public const string AppVersion = "1.1.1";

    /// <summary>
    /// 测试钩子快照（2026-11-17 老板令）：把当前全部标签的正文与状态
    /// 一次带走，供 --testhook 会话的文件握手导出。只在测试班触发，
    /// 普通运行永不进入本方法。
    /// </summary>
    TestHook.Snapshot SnapshotForTest()
    {
        var s = new TestHook.Snapshot { Version = AppVersion, Active = Active is { } act ? _docs.IndexOf(act) : -1 };
        foreach (var d in _docs)
        {
            s.Docs.Add(new TestHook.DocInfo
            {
                Title = d.Title,
                Path = d.FilePath,
                Dirty = d.Dirty,
                ReadOnly = d.ReadOnly,
                Text = d.Editor.Text,
                CaretLine = d.Editor.CaretLine,
                CaretColumn = d.Editor.CaretColumn,
                SelectionLength = d.Editor.SelectionLength,
                Lang = d.Editor.SyntaxLanguage.Name,
            });
            try { s.Docs[^1].StatusText = StatusLineFor(d); }
            catch { /* 状态行自报失败不挡正文快照 */ }
            try { s.Docs[^1].BracketColors = d.Editor.RenderedBracketColors(); }
            catch { /* 颜色通道失败不挡正文快照 */ }
            try { s.Docs[^1].CompletionItems = d.Editor.PopupItems; }
            catch { /* 弹层通道失败不挡正文快照 */ }
            try { s.Docs[^1].CompletionDebug = d.Editor.PopupDebug; }
            catch { /* 诊断通道失败不挡正文快照 */ }
            try { s.Docs[^1].HintDebug = d.Editor.HintDebug; }
            catch { /* 提示通道失败不挡正文快照 */ }
            try { s.Docs[^1].BookmarkLines = d.Editor.BookmarkLines; }
            catch { /* 书签通道失败不挡正文快照 */ }
            try { s.Docs[^1].PanelsDebug = $"preview={_previewOn},outline={_outlineOn}"; }
            catch { /* 面板通道失败不挡正文快照 */ }
        }
        return s;
    }

    /// <summary>状态栏文字的确定性自报（与 UpdateStatus 的各栏内容一致，
    /// 拼成一行；专供 --testhook 会话，绕开 UIA 读层空返）。</summary>
    string StatusLineFor(Doc doc)
    {
        var e = doc.Editor;
        var line = $"行 {e.CaretLine}，列 {e.CaretColumn}" + (doc.ReadOnly ? "（只读）" : "") +
            $" 选中 {e.SelectionLength} 字符 {e.CharCount} 行数 {e.LineCount} " +
            $"{(int)Math.Round(e.ZoomLevel * 100)}% {EncodingHelper.NameOf(doc.Enc, doc.Bom)} " +
            (doc.Eol switch { "\r\n" => "CRLF", "\n" => "LF", _ => "CR" }) +
            $" {e.SyntaxLanguage.Name}";
        if (IsArticle(e.SyntaxLanguage))
        {
            var st = WritingDoc.CountWords(e.Text);
            line += $" 字数 {st.Words} / 目标 {_wordGoal}" + (st.Words >= _wordGoal ? " ✔" : "");
        }
        return line;
    }

    /// <summary>
    /// UIA 供给修复（2026-11-14 定谳班：云端 UIA 对菜单/状态栏空返）。
    /// WinUI3 的 MenuFlyoutItem 文本不总是传播到自动化 Name，菜单项在
    /// 控制视图中偶发空名导致枚举 MISS；显式补 AutomationProperties.Name
    /// 与 Content 视图，保证外部 UIA 客户端（含测试 harness）稳定枚举。
    /// 不改变任何交互行为，零功能影响。
    /// </summary>
    void ExposeMenuToUia()
    {
        try
        {
            foreach (var bar in MenuBarRoot.Items)
            {
                AutomationProperties.SetName(bar, bar.Title);
                ExposeFlyoutItems(bar.Items);
            }
        }
        catch { /* 供给修复失败不阻断启动，保持原行为 */ }
    }

    void ExposeFlyoutItems(IList<MenuFlyoutItemBase> items)
    {
        foreach (var item in items)
        {
            switch (item)
            {
                // MenuFlyoutSubItem/ToggleMenuFlyoutItem 均继承自 MenuFlyoutItem，
                // 必须先判子类，否则后面的 case 不可达（CS8120）
                case MenuFlyoutSubItem sub:
                    AutomationProperties.SetName(sub, sub.Text);
                    ExposeFlyoutItems(sub.Items);
                    break;
                case ToggleMenuFlyoutItem tmi:
                    AutomationProperties.SetName(tmi, tmi.Text);
                    break;
                case MenuFlyoutItem mfi:
                    AutomationProperties.SetName(mfi, mfi.Text);
                    break;
            }
        }
    }

    void UpdateStatus()
    {
        var doc = Active;
        if (doc is null) return;
        var e = doc.Editor;
        PosText.Text = $"行 {e.CaretLine}，列 {e.CaretColumn}" + (doc.ReadOnly ? "（只读）" : "");
        SelText.Text = $"选中 {e.SelectionLength}";
        LenText.Text = $"字符 {e.CharCount}";
        LinesText.Text = $"行数 {e.LineCount}";
        ZoomText.Text = $"{(int)Math.Round(e.ZoomLevel * 100)}%";
        EncText.Text = EncodingHelper.NameOf(doc.Enc, doc.Bom);
        EolText.Text = doc.Eol switch { "\r\n" => "CRLF", "\n" => "LF", _ => "CR" };
        LangText.Text = doc.Editor.SyntaxLanguage.Name;
        UpdateArticleUI(doc);
    }

    /// <summary>写作面板与字数显示联动：仅文章语言显示；面板可见性/勾选状态在这里归一。</summary>
    void UpdateArticleUI(Doc doc)
    {
        bool article = IsArticle(doc.Editor.SyntaxLanguage);
        PreviewToggle.Visibility = article ? Visibility.Visible : Visibility.Collapsed;
        OutlineToggle.Visibility = article ? Visibility.Visible : Visibility.Collapsed;
        if (article)
        {
            var st = WritingDoc.CountWords(doc.Editor.Text);
            WordText.Text = $"字数 {st.Words} / 目标 {_wordGoal}" + (st.Words >= _wordGoal ? " ✔" : "");
            WordText.Visibility = Visibility.Visible;
        }
        else WordText.Visibility = Visibility.Collapsed;

        if (_preview is { } p)
            p.Visibility = article && _previewOn ? Visibility.Visible : Visibility.Collapsed;
        if (_outline is { } o)
            o.Visibility = article && _outlineOn ? Visibility.Visible : Visibility.Collapsed;
        // 让位边距与面板可见性同步：非文章语言/面板隐藏时收回让位（1.1.0 审查）
        UpdateEditorHost();
    }

    // ================= 写作模式：预览 / 大纲 / 目标 =================

    void OnPreviewToggle(object sender, RoutedEventArgs e)
    {
        _previewOn = PreviewToggle.IsChecked == true;
        if (_previewOn && _preview is null)
        {
            _preview = new ArticlePreview
            {
                Visibility = Visibility.Collapsed,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Stretch,
                Width = PreviewPanelWidth,
            };
            EditorHost.Children.Add(_preview);
        }
        UpdateEditorHost();
        RefreshArticlePanels();
    }

    void OnOutlineToggle(object sender, RoutedEventArgs e)
    {
        _outlineOn = OutlineToggle.IsChecked == true;
        if (_outlineOn && _outline is null)
        {
            _outline = new OutlinePanel
            {
                Visibility = Visibility.Collapsed,
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Stretch,
                Width = OutlinePanelWidth,
            };
            _outline.ItemClicked += line => { try { Ed?.GoToLine(line); } catch { } };
            EditorHost.Children.Add(_outline);
        }
        UpdateEditorHost();
        RefreshArticlePanels();
    }

    /// <summary>点状态栏字数：设置每日目标。</summary>
    async void OnWordGoalTap(object sender, Microsoft.UI.Xaml.Input.TappedRoutedEventArgs e)
    {
        if (Active is null || !IsArticle(Active.Editor.SyntaxLanguage)) return;
        var box = new NumberBox { Value = _wordGoal, Minimum = 1, SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Compact };
        var dlg = new ContentDialog
        {
            Title = "每日字数目标",
            Content = new StackPanel
            {
                Spacing = 8,
                Children = { new TextBlock { Text = "达标后状态栏会打勾；目标只影响显示，不改动正文。" }, box },
            },
            PrimaryButtonText = "保存",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = Content.XamlRoot,
        };
        if (await ShowDialogSafe(dlg) == ContentDialogResult.Primary)
        {
            if (double.IsFinite(box.Value))
            {
                int goal = (int)Math.Round(box.Value);
                if (goal >= 1)
                {
                    _wordGoal = goal;
                    WritingDoc.SaveGoal(goal);
                    UpdateStatus();
                }
            }
        }
    }

    // ================= 快照留底 =================

    /// <summary>立即给当前文档拍一份快照（旁路副本，不改正文）。</summary>
    void OnSnapshotSave(object sender, RoutedEventArgs e) => DoSnapshotNow();

    /// <summary>留底命令本体（1.1.1）：菜单与测试命令共用同一实现，
    /// 保证「用户点的」和「测试兜底的」永远是同一份行为。</summary>
    void DoSnapshotNow()
    {
        if (Active is not { } doc) return;
        try
        {
            string path = WritingDoc.SaveSnapshot(doc.FilePath, doc.Editor.Text, DateTimeOffset.Now);
            WritingDoc.TrimSnapshots(doc.FilePath, WritingDoc.SnapshotKeep);
            InfoTip("已留底：" + System.IO.Path.GetFileName(path));
        }
        catch (Exception ex)
        {
            CrashLog.Report(ex, "快照留底");
            InfoTip("快照保存失败，已记录日志。");
        }
    }

    /// <summary>查看当前文档的快照列表：选中即预览，只读。</summary>
    async void OnSnapshotView(object sender, RoutedEventArgs e)
    {
        if (Active is not { } doc) return;
        var dlg = new ContentDialog
        {
            Title = "快照留底",
            CloseButtonText = "关闭",
            XamlRoot = Content.XamlRoot,
        };
        var list = new ListBox { Height = 200, SelectionMode = SelectionMode.Single };
        var body = new TextBox { Height = 200, Margin = new Thickness(0, 8, 0, 0), IsReadOnly = true, TextWrapping = Microsoft.UI.Xaml.TextWrapping.Wrap, AcceptsReturn = true };
        Microsoft.UI.Xaml.Controls.ScrollViewer.SetVerticalScrollBarVisibility(body, ScrollBarVisibility.Auto);
        dlg.Content = new StackPanel
        {
            MinWidth = 480,
            Children = { list, body },
        };
        try
        {
            var snaps = WritingDoc.ListSnapshots(doc.FilePath);
            if (snaps.Count == 0)
            {
                list.Items.Add(new ListBoxItem { Content = "（还没有快照——保存或手动留底会自动生成）", IsEnabled = false });
            }
            else
            {
                foreach (var s in snaps)
                {
                    var info = s;
                    list.Items.Add(new ListBoxItem { Content = $"{info.When:yyyy-MM-dd HH:mm:ss}  {info.Size:N0} 字节", Tag = info.Path });
                }
                list.SelectionChanged += (_, _) =>
                {
                    if (list.SelectedItem is ListBoxItem it && it.Tag is string p)
                        body.Text = WritingDoc.ReadSnapshot(p) ?? "（快照读不到，可能已被清理）";
                };
            }
        }
        catch (Exception ex)
        {
            CrashLog.Report(ex, "快照查看");
            body.Text = "快照清单读取失败：" + ex.Message;
        }
        await ShowDialogSafe(dlg);
    }

    void UpdateEncChecks()
    {
        var doc = Active;
        if (doc is null) return;
        string name = EncodingHelper.NameOf(doc.Enc, doc.Bom);
        EncUtf8.IsChecked = name == "UTF-8";
        EncUtf8Bom.IsChecked = name == "UTF-8 BOM";
        EncUtf16.IsChecked = name == "UTF-16 LE";
        EncGbk.IsChecked = name == "GBK";
        EncBig5.IsChecked = name == "Big5";
    }

    void UpdateEolChecks()
    {
        var doc = Active;
        if (doc is null) return;
        EolCrLf.IsChecked = doc.Eol == "\r\n";
        EolLf.IsChecked = doc.Eol == "\n";
        EolCr.IsChecked = doc.Eol == "\r";
    }

    void UpdateLangChecks()
    {
        var doc = Active;
        if (doc is null) return;
        string id = doc.Editor.SyntaxLanguage.Id;
        foreach (var item in LangMenu.Items.OfType<ToggleMenuFlyoutItem>())
            item.IsChecked = item.Tag is LangDef lang && lang.Id == id;
    }

    void UpdateWrapChecks()
    {
        var doc = Active;
        WrapToggle.IsChecked = doc?.Editor.WordWrap == true;
    }

    // ================= 菜单事件：文件 =================

    void OnNew(object sender, RoutedEventArgs e) => NewDoc();
    async void OnOpen(object sender, RoutedEventArgs e)
    {
        try
        {
            string? path = await PickOpenFileAsync();
            if (path is not null) OpenPath(path);
        }
        catch (Exception ex)
        {
            CrashLog.Report(ex, "打开文件");
            InfoTip("打开文件失败，已记录日志。");
        }
    }
    async void OnSave(object sender, RoutedEventArgs e) { if (Active is { } d) await SaveDocAsync(d, false); }
    async void OnSaveAs(object sender, RoutedEventArgs e) { if (Active is { } d) await SaveDocAsync(d, true); }
    async void OnSaveAll(object sender, RoutedEventArgs e) { foreach (var d in _docs.ToList()) if (d.Dirty) await SaveDocAsync(d, false); }
    void OnCloseTab(object sender, RoutedEventArgs e) { if (Active is { } d) _ = CloseDocAsync(d); }
    void OnExit(object sender, RoutedEventArgs e)
    {
        try { Services.TraceLog.Write("菜单「退出」项被点击——本次退出为用户/自动化主动触发"); } catch { }
        Close();
    }

    void OnAddTab(object sender, object e) => NewDoc();
    void OnTabClose(TabView sender, TabViewTabCloseRequestedEventArgs args)
    {
        var doc = _docs.FirstOrDefault(d => ReferenceEquals(d.Tab, args.Tab));
        if (doc is not null) _ = CloseDocAsync(doc);
    }
    void OnTabSelChanged(object sender, SelectionChangedEventArgs e)
    {
        ShowActiveEditor();
        UpdateTitle();
        UpdateStatus();
        UpdateEncChecks();
        UpdateEolChecks();
        UpdateLangChecks();
        UpdateWrapChecks();
    }

    // ================= 菜单事件：编辑 =================

    CodeEditor? Ed => Active?.Editor;

    void OnUndo(object sender, RoutedEventArgs e) => Ed?.Undo();
    void OnRedo(object sender, RoutedEventArgs e) => Ed?.Redo();
    void OnCut(object sender, RoutedEventArgs e) => Ed?.Cut();
    void OnCopy(object sender, RoutedEventArgs e) => Ed?.Copy();
    void OnPaste(object sender, RoutedEventArgs e) => Ed?.Paste();
    void OnSelectAll(object sender, RoutedEventArgs e) => Ed?.SelectAll();
    void OnInsertTime(object sender, RoutedEventArgs e) => Ed?.Insert(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
    void OnDeleteLine(object sender, RoutedEventArgs e) => Ed?.DeleteLine();
    void OnDuplicateLine(object sender, RoutedEventArgs e) => Ed?.DuplicateLine();
    void OnMoveLineUp(object sender, RoutedEventArgs e) => Ed?.MoveLine(-1);
    void OnMoveLineDown(object sender, RoutedEventArgs e) => Ed?.MoveLine(1);
    void OnToUpper(object sender, RoutedEventArgs e) => Ed?.TransformSelection(s => s.ToUpperInvariant());

    void OnFormat(object sender, RoutedEventArgs e) => Ed?.FormatDocument();

    // 注释/取消注释：各语言按自己的标记（C 系 //、Python #、SQL --、XML 包裹式）
    void OnCommentSelection(object sender, RoutedEventArgs e) { try { Ed?.CommentSelection(); } catch (Exception ex) { CrashLog.Report(ex, "注释选区"); } }
    void OnUncommentSelection(object sender, RoutedEventArgs e) { try { Ed?.UncommentSelection(); } catch (Exception ex) { CrashLog.Report(ex, "取消注释选区"); } }
    void OnToLower(object sender, RoutedEventArgs e) => Ed?.TransformSelection(s => s.ToLowerInvariant());

    // ================= 菜单事件：搜索 =================

    void OnFind(object sender, RoutedEventArgs e) { if (Ed is not null) FindPanel.Show(withReplace: false); }
    void OnReplace(object sender, RoutedEventArgs e) { if (Ed is not null) FindPanel.Show(withReplace: true); }
    void OnFindNext(object sender, RoutedEventArgs e) => DoFind(false);
    void OnFindPrev(object sender, RoutedEventArgs e) => DoFind(true);

    async void OnGoto(object sender, RoutedEventArgs e)
    {
        if (Ed is null) return;
        var box = new TextBox { PlaceholderText = "行号" };
        var dlg = new ContentDialog
        {
            Title = "转到行",
            Content = new StackPanel { Spacing = 8, Children = { box } },
            PrimaryButtonText = "转到",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = Content.XamlRoot,
        };
        var r = await ShowDialogSafe(dlg);
        if (r == ContentDialogResult.Primary && int.TryParse(box.Text, out int line))
            Ed.GoToLine(line);
    }

    // ================= 菜单事件：查看 =================

    void OnWrapToggle(object sender, RoutedEventArgs e) { if (Ed is { } ed) ed.WordWrap = WrapToggle.IsChecked == true; }
    void OnLineNoToggle(object sender, RoutedEventArgs e) { if (Ed is { } ed) ed.ShowLineNumbers = LineNoToggle.IsChecked == true; }
    void OnZoomIn(object sender, RoutedEventArgs e) => Ed?.ZoomIn();
    void OnZoomOut(object sender, RoutedEventArgs e) => Ed?.ZoomOut();
    void OnZoomReset(object sender, RoutedEventArgs e) => Ed?.ZoomReset();

    // ================= 菜单事件：语言 / 编码 / 换行 / 主题 =================

    /// <summary>语言菜单动态生成：项、文案、勾选目标全部来自 LangDef.All 唯一清单。
    /// 此前 XAML 里硬编码 13 项、代码里再用控件名映射一遍——同一事实抄了两处，
    /// 新增语言要改三处且容易漏。现在只改 LangDef 一处，菜单自动跟上。</summary>
    void BuildLangMenu()
    {
        foreach (var lang in LangDef.All)
        {
            var item = new ToggleMenuFlyoutItem
            {
                Text = lang.Name,
                Tag = lang,
            };
            item.Click += OnLangClick;
            LangMenu.Items.Add(item);
        }
    }

    void OnLangClick(object sender, RoutedEventArgs e)
    {
        if (Active is not { } doc) return;
        // 菜单项的 Tag 就是语言定义本身，不再需要控件名→语言的映射表
        if ((sender as FrameworkElement)?.Tag is LangDef lang)
            doc.Editor.SyntaxLanguage = lang;
        UpdateLangChecks();
        UpdateStatus();
    }

    void OnEncClick(object sender, RoutedEventArgs e)
    {
        if (Active is not { } doc) return;
        (doc.Enc, doc.Bom) = (sender as FrameworkElement)?.Name switch
        {
            nameof(EncUtf8) => (new UTF8Encoding(false), false),
            nameof(EncUtf8Bom) => (new UTF8Encoding(true), true),
            nameof(EncUtf16) => (new UnicodeEncoding(false, true), true),
            nameof(EncGbk) => (SafeEnc("GBK"), false),
            nameof(EncBig5) => (SafeEnc("Big5"), false),
            _ => (doc.Enc, doc.Bom),
        };
        UpdateEncChecks();
        UpdateStatus();
    }

    static Encoding SafeEnc(string name) { try { return Encoding.GetEncoding(name); } catch { return Encoding.UTF8; } }

    void OnEolClick(object sender, RoutedEventArgs e)
    {
        if (Active is not { } doc) return;
        string eol = (sender as FrameworkElement)?.Name switch
        {
            nameof(EolCrLf) => "\r\n",
            nameof(EolLf) => "\n",
            nameof(EolCr) => "\r",
            _ => doc.Eol,
        };
        doc.Eol = eol;
        // v32 修 C02：落盘字节由 Editor 的 OutputEol 决定（SaveDocAsync 走
        // Text getter），只写 doc.Eol 只改状态栏显示。菜单选择必须同步进去。
        doc.Editor.SetEol(eol);
        UpdateEolChecks();
        UpdateStatus();
    }

    void OnThemeClick(object sender, RoutedEventArgs e)
    {
        AppTheme t = (sender as FrameworkElement)?.Name switch
        {
            nameof(ThemeSky) => AppTheme.Sky,
            nameof(ThemeNight) => AppTheme.Night,
            _ => AppTheme.Ink,
        };
        ThemeService.Apply(t);
        ThemeService.SaveChoice(t);   // 主题选择本机记住
        UpdateThemeChecks();
    }

    void UpdateThemeChecks()
    {
        ThemeSky.IsChecked = ThemeService.Current == AppTheme.Sky;
        ThemeNight.IsChecked = ThemeService.Current == AppTheme.Night;
        ThemeInk.IsChecked = ThemeService.Current == AppTheme.Ink;
    }

    // ================= 主题应用后的界面着色 =================

    void OnThemeApplied()
    {
        try
        {
            UpdateThemeChecks();
            // 关键大面直涂（IThemePaintable：每次 Apply 字典交换后涂）
            ApplyThemeBrushes();
            // 标签容器模板缓存各自基调：窗口级归零重估够不到已生成的容器，
            // 来回切换主题后选中标签会卡在旧主题色（表现为"标签不会切换了"）。
            // 对标签栏与每个标签同样"归零再落"，强制其内部模板按新基调重取色。
            var baseTheme = ThemeService.BaseElementTheme;
            ForceThemeRefresh(Tabs, baseTheme);
            // 查找面板直涂随主题 + 元素级基调重估（与标签同法，杜绝换肤残留）
            FindPanel.ApplyTheme();
            ForceThemeRefresh(FindPanel, baseTheme);
            foreach (var t in Tabs.TabItems)
                if (t is Microsoft.UI.Xaml.FrameworkElement fe) ForceThemeRefresh(fe, baseTheme);
            InvalidateVisual();
        }
        catch { // 主题回调任何异常都不得中断调用链，否则编辑器收不到后续复位
        }
        // 切主题刚点过菜单，键盘焦点常滞留在菜单栏——还回编辑器，
        // 否则接着打字没反应、智能提示看起来"失效"
        try { Active?.Editor.RestoreFocus(); } catch { }
    }

    /// <summary>元素级基调重估：先归默认再落目标，与窗口级同款（v63 手法），
    /// 强制该元素内部模板的 ThemeResource 全量重取。</summary>
    static void ForceThemeRefresh(Microsoft.UI.Xaml.FrameworkElement fe, Microsoft.UI.Xaml.ElementTheme target)
    {
        try
        {
            fe.RequestedTheme = Microsoft.UI.Xaml.ElementTheme.Default;
            fe.RequestedTheme = target;
        }
        catch { /* 单个元素重估失败不影响整体 */ }
    }

    /// <summary>
    /// 关键大面直涂（IThemePaintable，2026-11-01 全系铁律：主题字典必须被真实消费）。
    /// 构造完成后与每次 Apply 字典交换后各调一次：窗底、标题栏、状态栏取
    /// Ant.Bg / Ant.Surface，内容层取 LayerFillColorDefaultBrush——不依赖
    /// ThemeResource 重估，杜绝“换肤不生效”的根因；取不到键时保持现状。
    /// </summary>
    public void ApplyThemeBrushes()
    {
        var res = Application.Current.Resources;
        // 1.0.8 换肤加固：逐面隔离——以前整段套一个 try，任何一环异常都会让排在
        // 后面的大面拿不到新主题笔刷（真机表现：窗底换成了墨夜、状态栏停在首主题
        // 白）。现在每面独立接住并记入崩溃日志，单面失败不影响其余面。
        try
        {
            if (res.TryGetValue("Ant.Bg", out var bg) && bg is Brush bgBrush)
            {
                Root.Background = bgBrush;
                AppTitleBar.Background = bgBrush;
            }
        }
        catch (Exception ex) { CrashLog.Report(ex, "主题直涂-窗底"); }
        try
        {
            if (res.TryGetValue("Ant.Surface", out var surface) && surface is Brush surfaceBrush)
                StatusBar.Background = surfaceBrush;
        }
        catch (Exception ex) { CrashLog.Report(ex, "主题直涂-状态栏"); }
        try
        {
            // 层色底定律：内容区必带 LayerFillColorDefaultBrush
            if (res.TryGetValue("LayerFillColorDefaultBrush", out var layer) && layer is Brush layerBrush)
                ContentLayer.Background = layerBrush;
        }
        catch (Exception ex) { CrashLog.Report(ex, "主题直涂-内容层"); }
        // v1.0.1 同型修复（TaoZip 真机定案 2026-11-02）：ExtendsContentIntoTitleBar 下
        // 系统窗控按钮不吃 XAML 主题笔刷，墨夜近黑底上默认按钮色整体隐身。
        // 按当象 Ant.Bg / Ant.Text 直涂 AppWindow.TitleBar（八属性为 TaoZip 已验证集合，不外猜）。
        try
        {
            if (res["Ant.Bg"] is Microsoft.UI.Xaml.Media.SolidColorBrush capBg &&
                res["Ant.Text"] is Microsoft.UI.Xaml.Media.SolidColorBrush capFg &&
                AppWindow?.TitleBar is { } tb)
            {
                var capB = capBg.Color; var capC = capFg.Color;
                tb.BackgroundColor = capB; tb.ForegroundColor = capC;
                tb.ButtonBackgroundColor = capB; tb.ButtonForegroundColor = capC;
                // v1.0.2 真机反馈（TaoZip 同型 2026-11-02）：悬停/按下原样钉常态色，墨夜下
                // 肉眼不可辨。改向前景色调和：悬停 12% 轻提亮，按下 20% 更明显，三象自适应。
                tb.ButtonHoverBackgroundColor = Blend(capB, capC, 0.12f); tb.ButtonHoverForegroundColor = capC;
                tb.ButtonPressedBackgroundColor = Blend(capB, capC, 0.20f); tb.ButtonPressedForegroundColor = capC;
            }
        }
        catch (Exception ex) { CrashLog.Report(ex, "主题直涂-窗控"); }
    }

    /// <summary>颜色按比例向目标调和（t=0 取 a，t=1 取 b），供窗控悬停/按下态生成可辨底色。</summary>
    internal static Windows.UI.Color Blend(Windows.UI.Color a, Windows.UI.Color b, float t) =>
        Windows.UI.Color.FromArgb(a.A,
            (byte)(a.R + (b.R - a.R) * t),
            (byte)(a.G + (b.G - a.G) * t),
            (byte)(a.B + (b.B - a.B) * t));

    void InvalidateVisual()
    {
        foreach (var d in _docs)
        {
            // 触发编辑器重绘
            d.Editor.SyntaxLanguage = d.Editor.SyntaxLanguage;
        }
    }

    // ================= 拖放打开 =================

    void OnDragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = e.DataView.Contains(StandardDataFormats.StorageItems)
            ? DataPackageOperation.Copy
            : DataPackageOperation.None;
        e.Handled = true;
    }

    async void OnDrop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        try
        {
            var items = await e.DataView.GetStorageItemsAsync();
            var paths = items.OfType<StorageFile>().Select(i => i.Path).ToList();
            // 拖进来的文件按用户习惯开进全新窗口，不打扰当前窗口的标签
            if (paths.Count > 0) OpenInNewWindow(paths);
        }
        catch { }
    }

    /// <summary>开一个全新窗口并载入一批文件（拖放文件进软件时使用）。</summary>
    public static void OpenInNewWindow(IReadOnlyList<string> paths)
    {
        var w = new MainWindow();
        w.Activate();
        w.OpenPaths(paths);
    }

    // ================= 消息框 =================

    /// <summary>当前已打开的弹窗；ContentDialog 同时只允许一个，叠着弹第二个会直接抛异常闪退。</summary>
    ContentDialog? _activeDialog;

    /// <summary>安全弹窗：已有弹窗时新弹窗直接放弃（返回 null），弹窗自身失败也不往外抛，绝不因弹窗闪退。</summary>
    async Task<ContentDialogResult?> ShowDialogSafe(ContentDialog dlg)
    {
        if (_activeDialog is not null)
        {
            TraceLog.Write("弹窗互斥：已有弹窗未关，新弹窗放弃");
            return null;
        }
        try { dlg.XamlRoot ??= Content.XamlRoot; } catch { return null; }
        if (dlg.XamlRoot is null) return null;
        // 弹窗不归窗口内容树管，基调要显式对齐当前主题，否则深浅色弹窗会与主界面脱节
        try { dlg.RequestedTheme = ThemeService.BaseElementTheme; } catch { }
        _activeDialog = dlg;
        try { return await dlg.ShowAsync(); }
        catch { return null; }
        finally { if (ReferenceEquals(_activeDialog, dlg)) _activeDialog = null; }
    }

    async void ShowMessage(string title, string content)
    {
        await ShowDialogSafe(new ContentDialog
        {
            Title = title,
            Content = content,
            CloseButtonText = "确定",
            XamlRoot = Content.XamlRoot,
        });
    }
}
