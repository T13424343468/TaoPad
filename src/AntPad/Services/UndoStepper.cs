namespace AntPad.Services;

/// <summary>
/// 撤销/重做步进计划（纯逻辑件，1.1.1 审查修复配套）。
/// 富文本内核里，着色/彩虹括号等格式批也进撤销流——原生一步只退一批
/// 格式、文字不动，用户感知就是"Ctrl+Z 没反应"。步进器连续执行底层
/// Undo/Redo（由调用方以委托注入），直到文字真正变化或步进耗尽。
/// </summary>
public static class UndoStepper
{
    /// <summary>连续步进直到文字变化。steps=实际执行步数；changed=文字是否真变。</summary>
    /// <param name="maxSteps">单次快捷键允许的最大步数（防格式批遗漏时无限步进）。</param>
    /// <param name="before">步进前的规范文本。</param>
    /// <param name="current">取当前文本（每步后比较）。</param>
    /// <param name="step">执行一次底层 Undo/Redo。</param>
    /// <param name="canStep">底层还能否继续步进。</param>
    public static (int steps, bool changed) Run(
        int maxSteps, string before, Func<string> current, Action step, Func<bool> canStep)
    {
        for (int i = 0; i < maxSteps; i++)
        {
            if (!canStep()) return (i, current() != before);
            step();
            if (current() != before) return (i + 1, true);
        }
        return (maxSteps, current() != before);
    }
}
