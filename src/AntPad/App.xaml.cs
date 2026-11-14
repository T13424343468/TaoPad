using System.Text;
using AntPad.Services;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
using Windows.ApplicationModel.Activation;

namespace AntPad;

public partial class App : Application
{
    public static Window? MainWnd;

    /// <summary>所有存活窗口：拖放开新窗口后保引用防回收，关闭时移除。</summary>
    public static readonly List<Window> OpenWindows = new();

    public static void TrackWindow(Window w)
    {
        // 每个窗口都显式指定自己的图标：标题栏/任务栏小图标不靠默认猜测，
        // 也避免多项目共存时显示成别的程序或空白
        try { w.AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "TaoPad.ico")); }
        catch { /* 图标设置失败不影响运行 */ }
        // 新窗口直接套用当前主题基调，避免与已开窗口观感不一致
        Services.ThemeService.ApplyToWindow(w);
        if (!OpenWindows.Contains(w)) OpenWindows.Add(w);
    }
    public static void UntrackWindow(Window w)
    {
        OpenWindows.Remove(w);
        // 诊断留痕：云端五班 E07 进程"安静消失"（无崩溃/无 dump/WER/事件日志），
        // 唯一符合的退出链就是这里——最后一个窗口关闭触发 ExitAll。
        // 记录关闭源头调用栈，谁关的窗口一击必中。
        try
        {
            Services.TraceLog.Write($"窗口关闭，剩余={OpenWindows.Count}；关闭源头：\n{Environment.StackTrace}");
        }
        catch { /* 留痕失败不影响退出 */ }
        if (OpenWindows.Count == 0) ExitAll();
    }

    /// <summary>最后一个窗口关闭后彻底退出进程。自包含 WinUI 的进程可能被
    /// 框架消息循环/COM 引用吊住而不自然消亡（真机实测“退出后进程还在”），
    /// 因此显式退出，外加 1 秒兜底强杀——绝不留残留进程。</summary>
    public static void ExitAll()
    {
        try { Services.TraceLog.Write("ExitAll 触发：框架退出+1秒兜底强杀"); } catch { }
        try { Current.Exit(); } catch { /* 框架退出失败走兜底 */ }
        _ = System.Threading.Tasks.Task.Run(async () =>
        {
            try { await System.Threading.Tasks.Task.Delay(1000); } catch { }
            Environment.Exit(0);   // 兜底：框架退不干净就直接结束，防止进程残留
        });
    }

    public App()
    {
        InitializeComponent();
        // 支持GBK/Big5等代码页编码
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        // 全局兜底：任何未处理异常都落日志。运行期"拦截续命"——记录后程序
        // 继续运行，绝不因为单个未处理异常退掉整个进程（真机实测这类异常
        // 是"点工具闪退"的直接机制）。只有启动期没有主窗口时才退出。
        UnhandledException += (_, e) =>
        {
            e.Handled = true;
            Services.TraceLog.Write($"UI 线程异常（拦截续命）：{e.Exception.GetType().Name}：{e.Exception.Message}");
            CrashLog.Report(e.Exception, "UI 线程未处理异常（已拦截续命）");
            try
            {
                if (MainWnd is MainWindow mw)
                    mw.DispatcherQueue?.TryEnqueue(() =>
                    {
                        try { mw.NotifyNonFatal(e.Exception, "UI 线程未处理异常"); }
                        catch { /* 提示失败不影响续命 */ }
                    });
            }
            catch { }
        };
        // 后台线程兜底：UI 线程的 UnhandledException 管不到这里，
        // 只记日志不退出（进程继续运行，避免后台偶发错误带崩整个程序）
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            Services.TraceLog.Write($"后台线程异常，退出={e.IsTerminating}");
            if (e.ExceptionObject is Exception ex)
                CrashLog.Report(ex, $"后台线程未处理异常 (退出={e.IsTerminating})");
            else
                CrashLog.Report(new Exception(e.ExceptionObject?.ToString() ?? "非异常对象"), "后台线程未处理异常");
        };
        TaskScheduler.UnobservedTaskException += (_, e) =>
        {
            CrashLog.Report(e.Exception, "未观察的任务异常");
            e.SetObserved();   // 只记不崩
        };
        // 系统级最后一道钩子：抓 .NET 事件听不到的框架原生崩溃
        Services.NativeCrashDump.Install();
    }

    protected override void OnLaunched(Microsoft.UI.Xaml.LaunchActivatedEventArgs args)
    {
        try
        {
            Launch();
        }
        catch (Exception ex)
        {
            CrashLog.Report(ex, "启动");
            CrashLog.ShowBox();
            Environment.Exit(1);
        }
    }

    void Launch()
    {
        // Tao 系列存储规范：启动先迁移旧 C 盘数据到数据根（默认 D:\TaoPadData\TaoPad，
        // 同名不覆盖、失败不阻断），之后所有存储（recent/crash/trace/theme）都走数据根。
        var moved = Services.TaoPaths.MigrateLegacyFiles();
        if (moved.Count > 0)
            Services.TraceLog.Write($"旧数据迁移完成：{string.Join(",", moved)}");

        // 单实例 + 多窗口：程序已运行时，把文件路径转交给现有实例开新窗口，
        // 不再另起进程；转交走命名管道，结果确定（失败则自己正常启动）。
        if (!SingleInstance.TryAcquirePrimary())
        {
            var forward = MainWindow.ArgsFromCommandLine();
            bool sent = forward.Count == 0 || SingleInstance.ForwardPaths(forward);
            if (sent) Environment.Exit(0);
            // 转交失败（主实例刚好退出）：继续按主实例启动
            if (!SingleInstance.TryAcquirePrimary()) Environment.Exit(0);
        }

        SingleInstance.StartListening(paths => (MainWnd as MainWindow)?.OpenPaths(paths));

        MainWnd = new MainWindow();
        MainWnd.Activate();
        Services.TraceLog.Write("主窗口已激活，等待交互");

        // 冷启动：双击关联文件时系统带进来的命令行参数
        ((MainWindow)MainWnd).OpenPaths(MainWindow.ArgsFromCommandLine());
    }
}
