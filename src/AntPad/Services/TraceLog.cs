using System.Text;

namespace AntPad.Services;

/// <summary>
/// 轻量步骤追踪（行车记录仪）：把关键 UI 步骤按时间顺序写入本地日志。
/// 用途：定位"闪退但任何异常处理器都抓不到"的界面框架底层崩溃——
/// 崩溃前最后一条记录就是案发现场。
/// 文件位置：数据根（TaoPaths，默认 D:\TaoPadData\TaoPad）\trace.log，超过 200KB 自动清空重写。
/// </summary>
public static class TraceLog
{
    static string Dir => TaoPaths.Root;

    static string LogPath => Path.Combine(Dir, "trace.log");

    static readonly object _lock = new();

    public static void Write(string what)
    {
        try
        {
            lock (_lock)
            {
                Directory.CreateDirectory(Dir);
                if (File.Exists(LogPath) && new FileInfo(LogPath).Length > 200_000)
                    File.WriteAllText(LogPath, "");
                File.AppendAllText(LogPath, $"{DateTime.Now:HH:mm:ss.fff} {what}\r\n");
            }
        }
        catch { /* 追踪失败绝不影响运行 */ }
    }
}
