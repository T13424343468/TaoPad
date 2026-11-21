using System;

namespace AntPad.Services;

/// <summary>
/// 统一安全包装（全量审查台账 R2 处置）：防御性 try/catch 收敛到一处，
/// 失败统一落 TraceLog 留痕，不再静默空吞。
/// 豁免口径（台账定）：TraceLog 自身（日志通道不能再依赖日志）、
/// App 进程退出兜底（退出路径不能再抛）。
/// </summary>
public static class Safe
{
    /// <summary>执行 action，任何异常落 TraceLog 后继续。</summary>
    public static void Run(Action action, string tag)
    {
        try { action(); }
        catch (Exception ex) { Swallowed(tag, ex); }
    }

    /// <summary>执行 func，任何异常落 TraceLog 后返回 fallback。</summary>
    public static T Run<T>(Func<T> func, T fallback, string tag)
    {
        try { return func(); }
        catch (Exception ex) { Swallowed(tag, ex); return fallback; }
    }

    /// <summary>catch 块内统一落痕入口：不能整段包装时（体内含 return/await）用这个。</summary>
    public static void Swallowed(string tag, Exception ex)
        => TraceLog.Write($"Safe[{tag}] 吞掉异常：{ex.GetType().Name}：{ex.Message}");
}
