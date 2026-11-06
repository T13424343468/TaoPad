using System.Runtime.InteropServices;
using System.Text;

namespace AntPad.Services;

/// <summary>
/// 原生层崩溃捕获：WinUI/XAML 框架内部的崩溃不经过任何 .NET 异常事件
/// （UnhandledException / AppDomain 都听不到），进程直接被系统结束。
/// 这里挂系统最后一道钩子：进程消亡前把崩溃代码写入 native_crash.log，
/// 并保存一份小型转储（dump）供进一步定位。
/// 安装失败或钩子内部出错都静默，绝不影响正常运行。
/// </summary>
public static class NativeCrashDump
{
    delegate IntPtr FilterDelegate(IntPtr exceptionPointers);

    static FilterDelegate? _filter;   // 持引用防回收，回收=裸指针崩溃

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr SetUnhandledExceptionFilter(FilterDelegate lpTopLevelExceptionFilter);

    [DllImport("dbghelp.dll", SetLastError = true)]
    static extern bool MiniDumpWriteDump(IntPtr hProcess, uint processId, IntPtr hFile, uint dumpType,
        IntPtr exceptionParam, IntPtr userStreamParam, IntPtr callbackParam);

    [DllImport("kernel32.dll")]
    static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll")]
    static extern uint GetCurrentProcessId();

    static string Dir => TaoPaths.Root;

    public static void Install()
    {
        try
        {
            _filter = pointers =>
            {
                try
                {
                    uint code = 0;
                    long addr = 0;
                    if (pointers != IntPtr.Zero)
                    {
                        var rec = Marshal.ReadIntPtr(pointers);              // EXCEPTION_POINTERS.ExceptionRecord
                        if (rec != IntPtr.Zero)
                        {
                            code = (uint)Marshal.ReadInt32(rec);              // ExceptionCode 偏移 0
                            addr = Marshal.ReadIntPtr(rec, 16).ToInt64();     // ExceptionAddress 偏移 16（x64）
                        }
                    }
                    var stamp = DateTime.Now.ToString("HH:mm:ss.fff");
                    TraceLog.Write($"原生崩溃！代码=0x{code:X8} 地址=0x{addr:X}");

                    var sb = new StringBuilder();
                    sb.Append("==== ").Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff"))
                      .Append("] 原生崩溃（异常处理器抓不到的那类）\r\n");
                    sb.Append($"异常代码：0x{code:X8}\r\n出错地址：0x{addr:X}\r\n");
                    sb.Append("常见对照：0xC0000005=访问无效内存；0xC0000409=栈快速失败；0x80000003=断点。\r\n");
                    sb.Append($"详细现场：同目录 {DateTime.Now:HHmmss}.dmp 转储文件。\r\n");
                    Directory.CreateDirectory(Dir);
                    File.AppendAllText(Path.Combine(Dir, "native_crash.log"), sb.ToString());

                    // 小型转储：只含基础现场，几 MB 以内
                    try
                    {
                        var dumpPath = Path.Combine(Dir, $"{DateTime.Now:HHmmss}.dmp");
                        using var fs = new FileStream(dumpPath, FileMode.Create, FileAccess.Write, FileShare.None);
                        _ = MiniDumpWriteDump(GetCurrentProcess(), GetCurrentProcessId(),
                            fs.SafeFileHandle.DangerousGetHandle(), 0, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
                    }
                    catch { /* 转储失败有日志就够定位 */ }
                }
                catch { }
                return (IntPtr)1;   // EXCEPTION_EXECUTE_HANDLER：按系统默认结束
            };
            SetUnhandledExceptionFilter(_filter);
        }
        catch { /* 安装失败不影响运行 */ }
    }
}
