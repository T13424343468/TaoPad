using Microsoft.UI.Xaml.Media;

namespace AntPad.Services;

/// <summary>
/// 主题直涂接口（2026-11-01 全系铁律：主题字典必须被真实消费）。
/// 关键大面（窗底、内容层）不依赖 ThemeResource 重估——构造完成后与每次
/// Apply 字典交换后，都由窗口从当前主题字典取笔刷直接涂色；
/// ThemeResource 只留给控件细节色。
/// </summary>
public interface IThemePaintable
{
    /// <summary>从当前主题字典取笔刷直涂大面；取不到键时保持现状不抛异常。</summary>
    void ApplyThemeBrushes();
}
