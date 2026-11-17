using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.UI.Dispatching;

namespace AntPad.Services;

/// <summary>
/// 云端自动测试的「正文自报」通道（2026-11-17 老板令）。
/// 为什么存在：UIA 文本管线对大文档会饿死（v39.5 定谳），自动测试
/// 一直读不到编辑区正文，断言只能靠截图和落盘旁证。本钩子给测试
/// 班一条不依赖 UIA 的直读路径。
/// 安全边界：只有命令行带 --testhook 启动才激活——普通用户运行
/// （无参数）时本类完全静止，不监听端口、不建线程、不碰磁盘。
/// 握手方式：测试班在 %LOCALAPPDATA%\TaoPad\testhook 放一个
/// request.json，本类把当前全部标签的正文与状态原子写到
/// response.json 并收走请求。导出路径固定不接受请求指定，杜绝
/// 被诱导覆写任意文件。
/// </summary>
public static class TestHook
{
    public sealed class DocInfo
    {
        [JsonPropertyName("title")] public string Title { get; set; } = "";
        [JsonPropertyName("path")] public string? Path { get; set; }
        [JsonPropertyName("dirty")] public bool Dirty { get; set; }
        [JsonPropertyName("readOnly")] public bool ReadOnly { get; set; }
        [JsonPropertyName("text")] public string Text { get; set; } = "";
        [JsonPropertyName("caretLine")] public int CaretLine { get; set; }
        [JsonPropertyName("caretColumn")] public int CaretColumn { get; set; }
        [JsonPropertyName("selectionLength")] public int SelectionLength { get; set; }
        // 彩虹括号硬通道（1.1.0）：前 64 个括号位的实测渲染色 "pos:R,G,B"，
        // 云测据此断言嵌套括号至少出现 2 种颜色（X04 用例）
        [JsonPropertyName("bracketColors")] public List<string> BracketColors { get; set; } = new();
        // 补全弹层硬通道（1.1.0）：弹层开着时导出候选词，X07 据此断言 C# 语义补全
        [JsonPropertyName("completionItems")] public List<string> CompletionItems { get; set; } = new();
    }

    public sealed class Snapshot
    {
        [JsonPropertyName("version")] public string Version { get; set; } = "";
        [JsonPropertyName("active")] public int Active { get; set; } = -1;
        [JsonPropertyName("docs")] public List<DocInfo> Docs { get; } = new();
    }

    static bool _started;
    static string HookDir => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "TaoPad", "testhook");

    /// <summary>在 UI 线程上调用一次；非 --testhook 启动立即返回，零副作用。</summary>
    public static void Start(DispatcherQueue queue, Func<Snapshot> provider)
    {
        if (_started) return;
        if (!Environment.GetCommandLineArgs().Contains("--testhook")) return;
        _started = true;
        _ = Task.Run(() => LoopAsync(queue, provider));
    }

    static async Task LoopAsync(DispatcherQueue queue, Func<Snapshot> provider)
    {
        while (true)
        {
            try
            {
                Directory.CreateDirectory(HookDir);
                string req = Path.Combine(HookDir, "request.json");
                if (File.Exists(req))
                {
                    var snap = await TakeSnapshotAsync(queue, provider);
                    string json = JsonSerializer.Serialize(snap);
                    string tmp = Path.Combine(HookDir, "response.json.tmp");
                    await File.WriteAllTextAsync(tmp, json);
                    File.Move(tmp, Path.Combine(HookDir, "response.json"), overwrite: true);
                    File.Delete(req);
                }
            }
            catch (Exception ex)
            {
                // 测试钩子任何异常都不能影响编辑器本体：留痕后继续轮询
                TraceLog.Write("测试钩子异常：" + ex.Message);
            }
            await Task.Delay(300);
        }
    }

    // provider 读编辑器文本必须回 UI 线程；快照成形后写盘仍在后台
    static Task<Snapshot> TakeSnapshotAsync(DispatcherQueue queue, Func<Snapshot> provider)
    {
        var tcs = new TaskCompletionSource<Snapshot>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!queue.TryEnqueue(() =>
        {
            try { tcs.SetResult(provider()); }
            catch (Exception ex) { tcs.SetException(ex); }
        }))
        {
            tcs.SetException(new InvalidOperationException("测试钩子：队列已不可用"));
        }
        return tcs.Task;
    }
}
