using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace AntPad.Services;

/// <summary>
/// 崩溃日志：把启动/UI 线程的未处理异常写入本地日志并弹系统对话框，
/// 保证"程序打不开"时用户能看到原因，而不是无声无息。
/// 日志位置：数据根（TaoPaths，默认 D:\TaoPadData\TaoPad）\crash.log
/// </summary>
public static class CrashLog
{
    public static string Dir => TaoPaths.Root;

    static string LogPath => Path.Combine(Dir, "crash.log");

    /// <summary>最近一次错误的简短摘要（用于弹窗展示）。</summary>
    public static string LastSummary { get; private set; } = "";

    public static void Report(Exception? ex, string where)
    {
        var sb = new StringBuilder();
        sb.Append("==== ").Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")).Append(" [").Append(where).AppendLine("]");
        for (var e = ex; e is not null; e = e.InnerException)
        {
            sb.Append(e.GetType().FullName).Append(": ").AppendLine(e.Message);
            sb.AppendLine(e.StackTrace);
        }
        LastSummary = $"{ex?.GetType().Name}: {ex?.Message}";
        Write(sb.ToString());
    }

    public static void Report(string what, string where)
    {
        LastSummary = what;
        Write($"==== {DateTime.Now:yyyy-MM-dd HH:mm:ss} [{where}]\r\n{what}\r\n");
    }

    static void Write(string text)
    {
        try
        {
            Directory.CreateDirectory(Dir);
            File.AppendAllText(LogPath, text);
        }
        catch { /* 日志写不进去也不能再抛 */ }
    }

    /// <summary>弹系统级对话框（不依赖任何 XAML 窗口，启动早期也能弹出来）。</summary>
    public static void ShowBox(string title = "TaoPad 遇到错误")
    {
        var text = string.IsNullOrEmpty(LastSummary)
            ? "发生未知错误。"
            : LastSummary + $"\r\n\r\n详细日志：\r\n{LogPath}";
        try { _ = MessageBoxW(IntPtr.Zero, text, title, 0x40); }
        catch { /* 无窗口会话等场景弹不出就算了 */ }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);
}
