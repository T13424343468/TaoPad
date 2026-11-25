using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using Microsoft.Windows.ApplicationModel.DynamicDependency;

namespace AntPad.Services;

/// <summary>
/// 运行时自愈：Windows App SDK 运行时缺失时，应用侧接管检测、中文提示、
/// 带进度下载与一次提权静默安装，装完重试并重启自身。
/// 背景：v1.1.2 起界面框架运行时不打进安装包，改装时保障（全系安装器新标准）；
/// 安装器检测在部分真机上下文不可靠（run 44921060474 实锤三路探针全盲），
/// 真缺运行时时应用启动会弹英文错误框——本类把这道防线改成中文自愈。
/// 官方部署指南实锤：运行时由 Framework/Main/Singleton/DDLM 四类 MSIX 包组成，
/// Bootstrap.TryInitialize 失败即真缺，按最低版本 5001.214.1843.0 绑定。
/// </summary>
internal static class RuntimeSelfHeal
{
    // WindowsAppSDK-VersionInfo.cs 原文常量：1.5 最低版本 5001.214.1843.0
    private const ulong MinVersionRaw = 0x138900D607330000UL;
    private const uint MajorMinor = 0x00010005;
    private const string VersionTag = "";
    // 官方 1.5 运行时安装器（redist zip 里的 aka 链接无效，勿用）
    private const string InstallerUrl = "https://aka.ms/windowsappsdk/1.5/latest/windowsappruntimeinstall-x64.exe";

    [ModuleInitializer]
    internal static void Init()
    {
        try
        {
            EnsureRuntime();
        }
        catch (Exception ex)
        {
            // 自愈全程兜底：任何异常都不能挡住应用正常启动路径
            try { TraceLog.Write($"自愈兜底异常：{ex.GetType().Name}：{ex.Message}"); } catch { }
        }
    }

    private static void EnsureRuntime()
    {
        TraceLog.Write("自愈：初始化 Windows App SDK 运行时（Bootstrap）");
        if (TryInit(out int hr))
        {
            TraceLog.Write($"自愈：运行时在位 (hr={hr})");
            return;
        }
        TraceLog.Write($"自愈：运行时缺失或初始化失败 (hr=0x{hr:X8})");

        // 0) 包内兜底优先（2026-11-25 老板令「安装绝不依赖网络」同口径延伸到应用侧）：
        //    安装包 fallback\ 里自带官方安装器，离线直接装，不弹下载框、不碰网络。
        //    只有包内没有兜底（如源码直跑）或兜底装完仍失败时，才走在线下载线路。
        if (TryInstallFromBundled())
        {
            if (TryInit(out hr))
            {
                TraceLog.Write("自愈：兜底安装后运行时在位，重启自身");
                RestartSelf();
            }
            TraceLog.Write($"自愈：兜底安装后仍初始化失败 (hr=0x{hr:X8})，转在线线路");
        }

        var choice = MessageBox(
            "TaoPad 需要微软官方的「Windows App SDK 运行时」才能启动界面（约 64 MB，只需安装一次）。\n\n" +
            "点「是(Y)」自动下载并安装（会请求管理员权限）；点「否(N)」退出程序。",
            "TaoPad 运行时安装",
            MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND);
        TraceLog.Write($"自愈：用户选择 choice={choice}");
        if (choice != IDYES)
        {
            TraceLog.Write("自愈：用户选择不安装，退出");
            Environment.Exit(0);
        }

        // 1) 下载官方安装器（带进度窗）
        var exe = Path.Combine(Path.GetTempPath(), "WindowsAppRuntimeInstall-x64.exe");
        try
        {
            DownloadWithProgress(InstallerUrl, exe);
            TraceLog.Write($"自愈：下载完成 {exe} ({new FileInfo(exe).Length} 字节)");
        }
        catch (Exception ex)
        {
            TraceLog.Write($"自愈：下载失败 {ex.GetType().Name}：{ex.Message}");
            MessageBox(
                "运行时下载失败，请检查网络连接后重试。\n\n也可以手动下载安装微软官方运行时后重新打开 TaoPad：\n" + InstallerUrl,
                "TaoPad 运行时安装", MB_OK | MB_ICONWARNING | MB_SETFOREGROUND);
            Environment.Exit(1);
        }

        // 2) 一次提权静默安装（等待期显示「正在安装」进度窗）
        ShowBusy("正在安装 Windows App SDK 运行时，请稍候…", () =>
        {
            var psi = new ProcessStartInfo(exe, "--quiet --force")
            {
                Verb = "runas",              // 一次拿到管理员权限（全系安装器标准）
                UseShellExecute = true,
                CreateNoWindow = true        // 不弹命令窗，进度只走安装器内进度窗
            };
            using var p = Process.Start(psi)!;
            p.WaitForExit();
            TraceLog.Write($"自愈：官方安装器退出码 {p.ExitCode}");
        });

        // 3) 重试初始化
        if (TryInit(out hr))
        {
            TraceLog.Write("自愈：安装后运行时在位，重启自身");
            RestartSelf();
        }

        // 4) 仍失败：给手动指引
        TraceLog.Write($"自愈：安装后仍初始化失败 (hr=0x{hr:X8})");
        MessageBox(
            "运行时安装未能完成，请手动处理后重新打开 TaoPad：\n\n" +
            "1. 到微软官网下载「Windows App SDK 运行时 1.5」安装器；\n" +
            "2. 右键以管理员身份运行，装完后重新打开 TaoPad。\n\n" +
            "下载地址：" + InstallerUrl,
            "TaoPad 运行时安装", MB_OK | MB_ICONWARNING | MB_SETFOREGROUND);
        Environment.Exit(1);
    }

    /// <summary>
    /// 包内兜底安装：找安装包随包内置的官方运行时安装器（fallback\windowsappruntimeinstall-x64.exe），
    /// 提权静默安装。找到并跑完返回 true；包内没有（源码直跑）或用户拒绝提权返回 false，转在线线路。
    /// </summary>
    private static bool TryInstallFromBundled()
    {
        string? exeDir = Path.GetDirectoryName(Environment.ProcessPath);
        string[] candidates =
        {
            Path.Combine(AppContext.BaseDirectory, "fallback", "windowsappruntimeinstall-x64.exe"),
            Path.Combine(exeDir ?? string.Empty, "fallback", "windowsappruntimeinstall-x64.exe"),
            Path.Combine(exeDir ?? string.Empty, "windowsappruntimeinstall-x64.exe"),
        };
        string? bundled = candidates.FirstOrDefault(File.Exists);
        if (bundled == null)
        {
            TraceLog.Write("自愈：包内兜底安装器不存在（源码直跑或旧包），转在线线路");
            return false;
        }
        TraceLog.Write($"自愈：发现包内兜底安装器 {bundled}，离线安装（不弹下载框）");
        try
        {
            ShowBusy("正在安装 TaoPad 自带的运行时组件，请稍候…", () =>
            {
                var psi = new ProcessStartInfo(bundled, "--quiet --force")
                {
                    Verb = "runas",              // 一次拿到管理员权限（全系安装器标准）
                    UseShellExecute = true,
                    CreateNoWindow = true
                };
                using var p = Process.Start(psi)!;
                p.WaitForExit();
                TraceLog.Write($"自愈：兜底安装器退出码 {p.ExitCode}");
            });
            return true;
        }
        catch (Exception ex)
        {
            // 用户拒绝 UAC 或安装器启动失败：不拦启动路径，转在线线路
            TraceLog.Write($"自愈：兜底安装未完成 {ex.GetType().Name}：{ex.Message}");
            return false;
        }
    }

    private static void RestartSelf()
    {
        try
        {
            Process.Start(new ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            TraceLog.Write($"自愈：重启失败 {ex.GetType().Name}：{ex.Message}");
        }
        Environment.Exit(0);
    }

    private static bool TryInit(out int hr)
    {
        try
        {
            return Bootstrap.TryInitialize(MajorMinor, VersionTag, new PackageVersion(MinVersionRaw), Bootstrap.InitializeOptions.None, out hr);
        }
        catch (Exception ex)
        {
            try { TraceLog.Write($"自愈：Bootstrap 调用异常 {ex.GetType().Name}：{ex.Message}"); } catch { }
            hr = unchecked((int)0x80004005);
            return false;
        }
    }

    /// <summary>下载官方安装器，IProgressDialog 显示进度（不可取消、不最小化、自动耗时）。</summary>
    private static void DownloadWithProgress(string url, string dest)
    {
        var progress = (IProgressDialog)new ProgressDialogClass();
        progress.SetTitle("TaoPad 运行时安装");
        progress.SetText("正在下载微软官方运行时（约 64 MB）…");
        progress.StartProgressDialog(IntPtr.Zero, PROGDLG_NOCANCEL | PROGDLG_NOMINIMIZE | PROGDLG_AUTOTIME);
        try
        {
            using var http = new HttpClient();
            using var resp = http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult();
            resp.EnsureSuccessStatusCode();
            long total = resp.Content.Headers.ContentLength ?? -1;
            using var src = resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult();
            using var fs = new FileStream(dest, FileMode.Create, FileAccess.Write, FileShare.None, 81920);
            var buf = new byte[81920];
            long done = 0;
            int n;
            while ((n = src.Read(buf, 0, buf.Length)) > 0)
            {
                fs.Write(buf, 0, n);
                done += n;
                if (total > 0)
                {
                    try { progress.SetProgress64((ulong)done, (ulong)total); } catch { /* 进度刷新失败不影响下载 */ }
                }
            }
        }
        finally
        {
            try { progress.StopProgressDialog(); } catch { }
        }
    }

    /// <summary>忙等期进度窗：文案固定，动作跑完即收。</summary>
    private static void ShowBusy(string text, Action action)
    {
        var progress = (IProgressDialog)new ProgressDialogClass();
        progress.SetTitle("TaoPad 运行时安装");
        progress.SetText(text);
        progress.StartProgressDialog(IntPtr.Zero, PROGDLG_NOCANCEL | PROGDLG_NOMINIMIZE | PROGDLG_AUTOTIME);
        try { action(); }
        finally
        {
            try { progress.StopProgressDialog(); } catch { }
        }
    }

    // ---- Win32：启动期 WinUI 尚未初始化，弹窗走原生 MessageBox ----
    private const uint MB_OK = 0x0;
    private const uint MB_YESNO = 0x4;
    private const uint MB_ICONQUESTION = 0x20;
    private const uint MB_ICONWARNING = 0x30;
    private const uint MB_SETFOREGROUND = 0x10000;
    private const int IDYES = 6;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    private static int MessageBox(string text, string caption, uint type)
    {
        try { return MessageBoxW(IntPtr.Zero, text, caption, type); }
        catch (Exception ex)
        {
            try { TraceLog.Write($"自愈：弹窗失败 {ex.GetType().Name}：{ex.Message}"); } catch { }
            return 0;
        }
    }

    // ---- IProgressDialog COM 互操作（vtable 顺序按 shlobj_core.h 原文，不可增删） ----
    private const uint PROGDLG_NOCANCEL = 0x2;
    private const uint PROGDLG_NOMINIMIZE = 0x8;
    private const uint PROGDLG_AUTOTIME = 0x40;

    [ComImport]
    [Guid("C49A33EE-5A4D-4EFA-A1AA-25BC4D1C8E9E")]
    private class ProgressDialogClass
    {
    }

    [ComImport]
    [Guid("EB86D794-1E34-4FC6-88E7-3B1C9C8C6B9D")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IProgressDialog
    {
        void StartProgressDialog(IntPtr hwndOwner, uint flags);
        void StopProgressDialog();
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetText([MarshalAs(UnmanagedType.LPWStr)] string text);
        void SetCancelMsg([MarshalAs(UnmanagedType.LPWStr)] string message, IntPtr reserved);
        void Timer(uint action, uint delay);
        void SetProgress(uint completed, uint total);
        void SetLine(uint line, [MarshalAs(UnmanagedType.LPWStr)] string text, bool compactPath, IntPtr reserved);
        void SetLine64(uint line, [MarshalAs(UnmanagedType.LPWStr)] string text, bool compactPath, IntPtr reserved);
        void SetProgress64(ulong completed, ulong total);
        [PreserveSig]
        [return: MarshalAs(UnmanagedType.Bool)]
        bool HasUserCancelled();
        IntPtr GetHwnd();
    }
}
