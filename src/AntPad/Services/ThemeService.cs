using Microsoft.UI.Xaml;

namespace AntPad.Services;

/// <summary>
/// 主题服务：三象轮转——水墨（默认）/ 天青 / 墨夜，再无其他。
/// 通过替换合并字典 + 设置根元素 RequestedTheme 生效；决策唯一来源在 ThemeRule。
/// </summary>
public static class ThemeService
{
    static ResourceDictionary? _current;

    public static AppTheme Current { get; private set; } = AppTheme.Ink;

    /// <summary>当前基调（深/浅）：弹窗等不归窗口内容树管的元素用这个对齐观感。</summary>
    public static ElementTheme BaseElementTheme
        => ThemeRule.Resolve(Current).Dark ? ElementTheme.Dark : ElementTheme.Light;

    /// <summary>1.0.9 真机加固：Swap 合并进应用级的当前主题字典原对象。
    /// 代码取色在应用级合并链解析失灵时直连此字典兜底（行号栏/小地图真机白带修复）。</summary>
    public static ResourceDictionary? CurrentDictionary => _current;

    public static event Action? ThemeApplied;

    // 主题选择本机记住（数据根 theme.json，损坏/未知值安全回落水墨）
    static string ThemeFile => Path.Combine(TaoPaths.Root, "theme.json");

    public static void SaveChoice(AppTheme t)
    {
        try { File.WriteAllText(ThemeFile, t.ToString()); }
        catch { /* 存不进去不影响当前会话 */ }
    }

    public static AppTheme LoadChoice()
    {
        try
        {
            var s = File.ReadAllText(ThemeFile).Trim();
            if (Enum.TryParse<AppTheme>(s, out var t)) return t;
        }
        catch { }
        return AppTheme.Ink;
    }

    public static void Apply(AppTheme t)
    {
        Current = t;
        // 对所有已打开窗口生效。开机首进时主窗口变量可能还没接上
        // （构造函数未返回），只对 MainWnd 应用会漏掉 RequestedTheme。
        var targets = App.OpenWindows.ToList();
        foreach (var w in targets) ApplyToWindow(w);
        // 逐个隔离回调异常：单个订阅者出错不得中断主题应用链
        // （否则后面的编辑器收不到复位，出现配色失联/弹层失效）
        if (ThemeApplied is not null)
        {
            foreach (Action h in ThemeApplied.GetInvocationList())
            {
                try { h(); }
                catch (Exception ex) { CrashLog.Report(ex, "主题切换回调"); }
            }
        }
    }

    public static void ApplyToWindow(Window? w)
    {
        if (w?.Content is not FrameworkElement root) return;

        // 决策唯一来源：主题 → 基调与字典（ThemeRule 全组合可测）
        (bool dark, string dict) = ThemeRule.Resolve(Current);

        // 关键：ThemeResource 只在"生效基调变化"时才重新取色。水墨/天青
        // 共用浅色基调，来回切换时基调不变，已生成元素会抱着旧颜色不刷新
        // （表现为"有些元素切换成功有些不成功"）。先归到默认再落到目标值，
        // 同一 UI 帧内完成，中间状态不会上屏，但两次基调变化会触发全量重估。
        try
        {
            if (root.ActualTheme == (dark ? ElementTheme.Dark : ElementTheme.Light)
                || root.RequestedTheme == (dark ? ElementTheme.Dark : ElementTheme.Light))
            {
                root.RequestedTheme = ElementTheme.Default;
            }
        }
        catch { /* 归零失败不影响后续设置 */ }
        root.RequestedTheme = dark ? ElementTheme.Dark : ElementTheme.Light;
        var merged = Swap(dict);
        if (merged is not null) ApplyCeramic(merged);
        ApplyAccentOverrides();
        // 关键大面直涂（IThemePaintable：字典已交换，构造后与每次 Apply 都涂）
        if (w is IThemePaintable p) p.ApplyThemeBrushes();
    }

    /// <summary>
    /// 陶瓷质感（2026-11-06 全系 PC 天青统一）：卡片/输入面用竖向 LinearGradientBrush
    /// （0,0→0,1），GradientStops 0.0=主体色提亮（+15/通道，255 封顶）、0.55=主体色、
    /// 1.0=压暗（-12/通道，0 封底），三套主题统一生效；异常退回纯色不阻断换肤。
    /// 代码侧取色由 TryBrush 兼容渐变主体帧（0.55 停止点），语义不变。
    /// 作用域铁律（1.0.6 真机缺陷修复）：渐变只写进当前主题字典，随字典交换消亡；
    /// 绝不写应用级——应用级条目会跨主题残留并遮蔽新主题字典同名键
    /// （首主题之外换任何主题，Surface/EdBg/层色永远停留在首主题色，"墨夜换不回来"的根因）。
    /// </summary>
    static void ApplyCeramic(ResourceDictionary theme)
    {
        try
        {
            foreach (string key in new[] { "Ant.Surface", "Ant.EdBg", "LayerFillColorDefaultBrush" })
            {
                if (!theme.TryGetValue(key, out var val) || val is not Microsoft.UI.Xaml.Media.SolidColorBrush sc) continue;
                byte Clamp(int c) => (byte)Math.Clamp(c, 0, 255);
                var top = Windows.UI.Color.FromArgb(sc.Color.A, Clamp(sc.Color.R + 15), Clamp(sc.Color.G + 15), Clamp(sc.Color.B + 15));
                var body = sc.Color;
                var bottom = Windows.UI.Color.FromArgb(sc.Color.A, Clamp(sc.Color.R - 12), Clamp(sc.Color.G - 12), Clamp(sc.Color.B - 12));
                theme[key] = new Microsoft.UI.Xaml.Media.LinearGradientBrush
                {
                    StartPoint = new Windows.Foundation.Point(0, 0),
                    EndPoint = new Windows.Foundation.Point(0, 1),
                    GradientStops =
                    {
                        new Microsoft.UI.Xaml.Media.GradientStop { Color = top, Offset = 0.0 },
                        new Microsoft.UI.Xaml.Media.GradientStop { Color = body, Offset = 0.55 },
                        new Microsoft.UI.Xaml.Media.GradientStop { Color = bottom, Offset = 1.0 },
                    },
                };
            }
        }
        catch { /* 陶瓷化失败退回纯色，不阻断换肤 */ }
    }

    /// <summary>
    /// 系统强调色键改绑主题点缀色：ContentDialog 内的 ToggleSwitch / 主按钮 /
    /// ComboBox 等控件吃系统 accent 色，不覆盖就与三象主题脱节
    /// （真机反馈"设置弹窗开关/按钮没跟主题"的修复，A2 断言在链）。
    /// </summary>
    static void ApplyAccentOverrides()
    {
        try
        {
            var res = Application.Current.Resources;
            foreach (string key in new[]
            {
                "SystemAccentColor", "ToggleSwitchFillOn",
                "SystemControlHighlightAccentBrush", "SystemControlForegroundAccentBrush",
                "SystemControlBackgroundAccentBrush",
            })
            {
                if (res.TryGetValue("Ant.Accent", out var v)) res[key] = v;
            }
        }
        catch { /* 覆盖失败不影响主题其余部分 */ }
    }

    /// <returns>本次实际合并生效的主题字典（含回退）；加载失败且回退也失败时为 null。</returns>
    static ResourceDictionary? Swap(string file)
    {
        var res = Application.Current.Resources;
        // 主题字典加载失败绝不拖垮启动：回退水墨并记录原因
        ResourceDictionary? next = null;
        try { next = new ResourceDictionary { Source = new Uri($"ms-appx:///Themes/{file}.xaml") }; }
        catch (Exception ex) { CrashLog.Report(ex, $"加载主题 {file} 失败"); }
        if (next is null && file != "Ant.Ink")
        {
            try { next = new ResourceDictionary { Source = new Uri("ms-appx:///Themes/Ant.Ink.xaml") }; }
            catch { }
        }
        if (next is null) return null;
        // 1.0.8 换肤加固：App.xaml 静态合并的水墨字典永远留在合并链里，与运行时字典
        // 叠加后同一主题键在链上有多份，命中次序因解析路径而异，首主题残留由此而来
        // （真机 1.0.7：行号栏/小地图/状态栏停在首主题白）。链上只允许一份主题字典。
        for (int i = res.MergedDictionaries.Count - 1; i >= 0; i--)
        {
            var src = res.MergedDictionaries[i].Source?.OriginalString ?? "";
            if (src.Contains("/Themes/Ant."))
                res.MergedDictionaries.RemoveAt(i);
        }
        if (_current is not null)
            res.MergedDictionaries.Remove(_current);
        res.MergedDictionaries.Add(next);
        _current = next;
        return next;
    }
}
