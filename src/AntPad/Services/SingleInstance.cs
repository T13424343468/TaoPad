using Microsoft.UI.Dispatching;
using System.IO;
using System.IO.Pipes;

namespace AntPad.Services;

/// <summary>
/// 单实例管理：双击文件时若程序已运行，把文件路径经命名管道转交给
/// 已运行的实例，在现有程序中开新窗口，而不是另起一个进程。
/// 管道方案不依赖系统激活链路，转交结果完全确定：转交成功则第二个进程
/// 立即退出；转交失败（主实例异常退出）则自己继续启动。
/// </summary>
public static class SingleInstance
{
    const string MutexName = @"Local\TaoPad.SingleInstance";
    const string PipeName = "TaoPad.InstancePipe";

    static Mutex? _mutex;

    /// <summary>尝试成为主实例。返回 false 表示已有实例在运行。</summary>
    public static bool TryAcquirePrimary()
    {
        _mutex = new Mutex(true, MutexName, out bool createdNew);
        return createdNew;
    }

    /// <summary>把文件路径转交给主实例（短超时，失败不抛出）。</summary>
    public static bool ForwardPaths(IEnumerable<string> paths)
    {
        try
        {
            using var client = new NamedPipeClientStream(".", PipeName, PipeDirection.Out);
            client.Connect(2000);
            using var writer = new StreamWriter(client) { AutoFlush = true };
            writer.Write(string.Join("\n", paths));
            return true;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>主实例开始监听转交，收到文件路径后回到 UI 线程打开。</summary>
    public static void StartListening(Action<IReadOnlyList<string>> onPaths)
    {
        var queue = DispatcherQueue.GetForCurrentThread();
        _ = Task.Run(async () =>
        {
            while (true)
            {
                try
                {
                    using var server = new NamedPipeServerStream(PipeName, PipeDirection.In);
                    await server.WaitForConnectionAsync();
                    string payload;
                    using (var reader = new StreamReader(server))
                        payload = await reader.ReadToEndAsync();
                    var paths = payload.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                    if (paths.Length > 0)
                        queue.TryEnqueue(() => onPaths(paths));
                }
                catch
                {
                    // 监听异常：短暂等待后重建管道，避免一次损坏导致永久失联
                    await Task.Delay(500);
                }
            }
        });
    }
}
