using System;

namespace AntPad.Services;

/// <summary>应用主题三象：水墨（宣纸白底、墨分五色）、天青（天青釉底、青瓷点缀，2026-11-06 全系 PC 天青统一）、墨夜（暖炭底、宣纸白字）。枚举随决策同源。</summary>
public enum AppTheme { Ink, Sky, Night }

/// <summary>
/// 主题决策纯函数与三套语法定色板：无 WinUI 依赖，可全组合单测。
/// 道法三象：万物负阴抱阳——天青主昼（浅），墨夜主夜（深），水墨居中为体（默认）。
/// 只此三套，不再多设；深色不用系统原生生黑，墨夜循 TaoZip v53 母本暖炭调。
/// </summary>
public static class ThemeRule
{
    /// <summary>决策唯一来源：主题 → (深色基调, 字典文件名)。</summary>
    public static (bool Dark, string Dict) Resolve(AppTheme t)
        => t switch
        {
            AppTheme.Night => (true, "Ant.Night"),
            AppTheme.Sky => (false, "Ant.Sky"),
            _ => (false, "Ant.Ink"),
        };

    /// <summary>水墨语法定色板（与 Ant.Ink.xaml 同值同步，O2/S5 测试把关一致性）。
    /// 2026-11-01 用户定：水墨底近白化后，浅底系（水墨/天青）语法字同色号统一——
    /// 关键字深藏蓝与正文墨青以色相拉开（纯黑对深灰亮度区分已到顶）；
    /// 墨夜黑底不可用深色字，按同色相亮版另行适配（亮度阶梯定律）。</summary>
    public static readonly (string Key, byte R, byte G, byte B)[] InkTokens =
    {
        ("Ant.TokKeyword",    0x0F, 0x4C, 0x9E),   // 深藏蓝（与天青同号）
        ("Ant.TokType",       0x0B, 0x3D, 0x6B),   // 深青（与天青同号）
        ("Ant.TokHeading",    0x1C, 0x24, 0x2C),
        ("Ant.TokControl",    0x2C, 0x3E, 0x50),
        ("Ant.TokTag",        0x14, 0x50, 0x8A),
        ("Ant.EdText",        0x1C, 0x24, 0x2C),   // 正文深墨青（与天青同号）
        ("Ant.TokString",     0x7A, 0x4A, 0x00),   // 深赭（与天青同号）
        ("Ant.TokNumber",     0x5C, 0x4A, 0x00),
        ("Ant.TokAttr",       0x34, 0x50, 0x6B),
        ("Ant.TokPreproc",    0x46, 0x52, 0x5C),
        ("Ant.TokDocComment", 0x3E, 0x48, 0x52),
        ("Ant.TokComment",    0x4E, 0x58, 0x62),   // 青灰（与天青同号）
    };

    /// <summary>天青语法定色板（与 Ant.Sky.xaml 同值同步）：天青釉浅底（#EDF2EF，G>B>R）上
    /// 全套深色系——深藏蓝关键字、深青类型、深赭字符串、青灰注释；
    /// 天青居亮度阶梯浅带（L>0.85 且小于水墨），浅底语法字仍可辨；12 键与水墨同号（S5）。</summary>
    public static readonly (string Key, byte R, byte G, byte B)[] SkyTokens =
    {
        ("Ant.TokKeyword",    0x0F, 0x4C, 0x9E),   // 深藏蓝（呼应点缀）
        ("Ant.TokType",       0x0B, 0x3D, 0x6B),   // 深青
        ("Ant.TokHeading",    0x1C, 0x24, 0x2C),
        ("Ant.TokControl",    0x2C, 0x3E, 0x50),
        ("Ant.TokTag",        0x14, 0x50, 0x8A),
        ("Ant.EdText",        0x1C, 0x24, 0x2C),   // 正文深墨青
        ("Ant.TokString",     0x7A, 0x4A, 0x00),   // 深赭
        ("Ant.TokNumber",     0x5C, 0x4A, 0x00),
        ("Ant.TokAttr",       0x34, 0x50, 0x6B),
        ("Ant.TokPreproc",    0x46, 0x52, 0x5C),
        ("Ant.TokDocComment", 0x3E, 0x48, 0x52),
        ("Ant.TokComment",    0x4E, 0x58, 0x62),   // 青灰
    };

    /// <summary>墨夜语法定色板（与 Ant.Night.xaml 同值同步）：暖炭底上的宣纸白正文，
    /// 亮黛青关键字、青玉类型、暖沙字符串；全部暖调克制，点缀用黛青不刺目。</summary>
    public static readonly (string Key, byte R, byte G, byte B)[] NightTokens =
    {
        ("Ant.TokKeyword",    0x7F, 0xB0, 0xCC),   // 亮黛青（最亮）
        ("Ant.TokType",       0x8F, 0xB8, 0xA8),   // 青玉
        ("Ant.TokHeading",    0xD8, 0xD3, 0xC5),
        ("Ant.TokControl",    0xA8, 0xB8, 0xC4),
        ("Ant.TokTag",        0x9C, 0xB4, 0xC0),
        ("Ant.EdText",        0xE8, 0xE3, 0xD5),   // 宣纸白正文
        ("Ant.TokString",     0xC9, 0xA9, 0x8A),   // 暖沙
        ("Ant.TokNumber",     0xB8, 0xAE, 0x8E),
        ("Ant.TokAttr",       0x9C, 0xB0, 0xB8),
        ("Ant.TokPreproc",    0x9A, 0x90, 0x80),
        ("Ant.TokDocComment", 0x8A, 0x84, 0x74),
        ("Ant.TokComment",    0x7A, 0x74, 0x66),   // 暖灰（最暗）
    };

    /// <summary>感知亮度（0–255）：层次断言用。</summary>
    public static double Luma(byte r, byte g, byte b) => 0.299 * r + 0.587 * g + 0.114 * b;
}
