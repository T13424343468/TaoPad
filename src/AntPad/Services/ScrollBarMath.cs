namespace AntPad.Services;

/// <summary>
/// VSCode 风格滚动条的纯几何（2026-11-03，全文件常驻右侧滑动区）。
/// 滑条长度与位置只由轨道长、内容长、视口长、滚动偏移决定——不依赖任何
/// UI 对象，入万链做生成式测试；不溢出或参数非法时返回 (0,0)，由调用方隐藏。
/// </summary>
public static class ScrollBarMath
{
    /// <summary>滑条最小长度（px）：内容再长滑条也不小于它，可点可拖。</summary>
    public const double MinThumb = 24;

    /// <summary>计算滑条长度与顶端位置。</summary>
    public static (double ThumbLen, double ThumbPos) Compute(
        double trackLen, double contentLen, double viewLen, double offset)
    {
        if (double.IsNaN(trackLen) || double.IsInfinity(trackLen) || trackLen <= 0) return (0, 0);
        if (double.IsNaN(contentLen) || double.IsInfinity(contentLen) || contentLen <= 0) return (0, 0);
        if (double.IsNaN(viewLen) || double.IsInfinity(viewLen) || viewLen <= 0) return (0, 0);
        if (double.IsNaN(offset) || double.IsInfinity(offset)) return (0, 0);
        if (contentLen <= viewLen) return (0, 0);   // 不溢出：无滑条
        if (viewLen >= contentLen) return (0, 0);

        // 滑条长 ∝ 视口/内容，夹进 [MinThumb, trackLen]
        double thumb = trackLen * viewLen / contentLen;
        thumb = Math.Max(MinThumb, Math.Min(trackLen, thumb));

        // 位置 = 偏移比例 × 可滑行程，偏移夹进 [0, maxOff]
        double maxOff = contentLen - viewLen;
        double off = Math.Max(0, Math.Min(maxOff, offset));
        double pos = off / maxOff * (trackLen - thumb);
        return (thumb, pos);
    }
}
