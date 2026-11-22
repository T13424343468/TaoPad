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
        [JsonPropertyName("lang")] public string Lang { get; set; } = "";
        [JsonPropertyName("statusText")] public string StatusText { get; set; } = "";
        [JsonPropertyName("completionDebug")] public string CompletionDebug { get; set; } = "";
        // 彩虹括号硬通道（1.1.0）：前 64 个括号位的实测渲染色 "pos:R,G,B"，
        // 云测据此断言嵌套括号至少出现 2 种颜色（X04 用例）
        [JsonPropertyName("bracketColors")] public List<string> BracketColors { get; set; } = new();
        // 补全弹层硬通道（1.1.0）：弹层开着时导出候选词，X07 据此断言 C# 语义补全
        [JsonPropertyName("completionItems")] public List<string> CompletionItems { get; set; } = new();
        // 参数提示硬通道（1.1.1）：浮层开关 + 最近一次签名函数名（X12 用例）
        [JsonPropertyName("hintDebug")] public string HintDebug { get; set; } = "";
        // 书签硬通道（1.1.1）：当前书签行号（1 计，升序），X11 据此断言打点/取消
        [JsonPropertyName("bookmarkLines")] public List<int> BookmarkLines { get; set; } = new();
        // 面板硬通道（1.1.1）：预览/大纲面板开合自报，X05 收尾据此验证残留
        [JsonPropertyName("panelsDebug")] public string PanelsDebug { get; set; } = "";
    }

    public sealed class Snapshot
    {
        [JsonPropertyName("version")] public string Version { get; set; } = "";
        [JsonPropertyName("active")] public int Active { get; set; } = -1;
        [JsonPropertyName("docs")] public List<DocInfo> Docs { get; } = new();
        // 命令回执（1.1.1）：请求带 command 时由命令分发器返回的执行回执
        [JsonPropertyName("commandResult")] public string? CommandResult { get; set; }
    }

    static bool _started;

    /// <summary>
    /// 命令下行分发器（1.1.1）：主窗体在 --testhook 会话注入。请求 JSON 带
    /// command/arg 时在 UI 线程执行并回执；不带 command 保持纯快照语义不变。
    /// 为什么存在：云端 runner 对菜单直呼与键盘通道偶发整段失效（三轮
    /// 同路实测），凡依赖 UI 传输的断言连环误红；与 completionItems/
    /// hintDebug 同族——只经测试通道兜底，普通用户运行零影响。
    /// </summary>
    public static Func<string, string?, string>? CommandDispatcher { get; set; }
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
                    // 命令下行（1.1.1）：请求可带 {"command":..,"arg":..}；
                    // 纯空请求保持旧快照语义，命令分发失败不挡快照导出。
                    string? cmd = null, arg = null;
                    try
                    {
                        using var doc = JsonDocument.Parse(File.ReadAllText(req));
                        if (doc.RootElement.ValueKind == JsonValueKind.Object)
                        {
                            if (doc.RootElement.TryGetProperty("command", out var c) && c.ValueKind == JsonValueKind.String)
                                cmd = c.GetString();
                            if (doc.RootElement.TryGetProperty("arg", out var a) && a.ValueKind == JsonValueKind.String)
                                arg = a.GetString();
                        }
                    }
                    catch { /* 空文件或非 JSON：按旧语义纯快照 */ }
                    // X15 run 45038397842 实锤：解析后先删请求再办——旧序在
                    // 响应写盘后才删请求，处理期间到达的下一轮请求会被本轮
                    // 收尾的删除误吞，客户端白等到超时（偶发「快照回不来」）。
                    // 先删后办，新请求只会排进下一轮 300ms 轮询，不再丢。
                    File.Delete(req);
                    var sw = System.Diagnostics.Stopwatch.StartNew();
                    string? result = cmd is null ? null : await RunCommandAsync(queue, cmd, arg);
                    var snap = await TakeSnapshotAsync(queue, provider);
                    snap.CommandResult = result;
                    long uiMs = sw.ElapsedMilliseconds;
                    string json = JsonSerializer.Serialize(snap);
                    string tmp = Path.Combine(HookDir, "response.json.tmp");
                    await File.WriteAllTextAsync(tmp, json);
                    File.Move(tmp, Path.Combine(HookDir, "response.json"), overwrite: true);
                    // 快照周期计时留痕：界面线程段与序列化落盘段分开记，
                    // 再现「回不来」时日志直接定谳慢在哪一段
                    TraceLog.Write($"测试钩子：快照回执 docs={snap.Docs.Count} " +
                        $"界面线程={uiMs}ms 序列化落盘={sw.ElapsedMilliseconds - uiMs}ms" +
                        (cmd is null ? "" : $" 命令={cmd}"));
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

    // 命令同样要在 UI 线程执行（动的是 UI 状态）；异常折进回执字符串，
    // 不让测试命令把快照导出整个炸掉
    static Task<string> RunCommandAsync(DispatcherQueue queue, string cmd, string? arg)
    {
        var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!queue.TryEnqueue(() =>
        {
            try { tcs.SetResult(CommandDispatcher?.Invoke(cmd, arg) ?? "ERR no-dispatcher"); }
            catch (Exception ex) { tcs.SetResult("ERR " + ex.Message); }
        }))
        {
            tcs.SetException(new InvalidOperationException("测试钩子：队列已不可用"));
        }
        return tcs.Task;
    }
}
