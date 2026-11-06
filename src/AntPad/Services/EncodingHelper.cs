using System.Text;

namespace AntPad.Services;

public static class EncodingHelper
{
    /// <summary>探测字节流的编码与 BOM。</summary>
    public static (Encoding Enc, bool Bom) Detect(byte[] data)
    {
        if (data.Length >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF)
            return (new UTF8Encoding(true), true);
        if (data.Length >= 2 && data[0] == 0xFF && data[1] == 0xFE)
            return (new UnicodeEncoding(bigEndian: false, byteOrderMark: true), true);
        if (data.Length >= 2 && data[0] == 0xFE && data[1] == 0xFF)
            return (new UnicodeEncoding(bigEndian: true, byteOrderMark: true), true);

        // 无 BOM：先按严格 UTF-8 解码，失败则回退 GBK（中文环境常见）
        try
        {
            var strict = new UTF8Encoding(false, throwOnInvalidBytes: true);
            _ = strict.GetString(data);
            return (new UTF8Encoding(false), false);
        }
        catch
        {
            try { return (Encoding.GetEncoding("GBK"), false); }
            catch { return (Encoding.GetEncoding(0) ?? Encoding.Default, false); }
        }
    }

    /// <summary>编码菜单项：名称 / 编码 / 是否写 BOM。</summary>
    public static readonly (string Name, Encoding Enc, bool Bom)[] Options =
    {
        ("UTF-8",      new UTF8Encoding(false), false),
        ("UTF-8 BOM",  new UTF8Encoding(true),  true),
        ("UTF-16 LE",  new UnicodeEncoding(false, true), true),
        ("GBK",        Safe("GBK"),   false),
        ("Big5",       Safe("Big5"),  false),
    };

    public static string NameOf(Encoding enc, bool bom)
    {
        foreach (var o in Options)
            if (Equals(o.Enc.WebName, enc.WebName) && o.Bom == bom)
                return o.Name;
        return enc.WebName.ToUpperInvariant() + (bom ? " BOM" : "");
    }

    static Encoding Safe(string name)
    {
        try { return Encoding.GetEncoding(name); }
        catch { return Encoding.UTF8; }
    }
}
