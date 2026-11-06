using System.Text;
using System.Text.RegularExpressions;

namespace AntPad.Syntax;

public enum TokKind { Text, Keyword, Control, String, Comment, DocComment, Number, Type, Preproc, Tag, Attr, Heading, Member, Bracket }

public readonly record struct TokenSpan(int Start, int Length, TokKind Kind);

public struct HlState { public bool BlockComment; public bool DocBlock; public bool XmlTag; }

/// <summary>语言定义：关键字表 + 模式开关。</summary>
public sealed class LangDef
{
    public string Id = "plain";
    public string Name = "纯文本";
    public string[] LineComments = Array.Empty<string>();
    public (string Open, string Close)? BlockComment;
    /// <summary>文档注释行标记（VS 语义：C 系 ///，Rust ///），null 表示该语言没有。</summary>
    public string? DocLineComment;
    /// <summary>文档注释块起点（VS 语义：C 系 /** ... *&#47;），null 表示没有。</summary>
    public string? DocBlockOpen;
    public string[] Keywords = Array.Empty<string>();
    public string[] ControlWords = Array.Empty<string>();
    public string[] Types = Array.Empty<string>();
    public bool Strings = true, Chars = true, Numbers = true;
    public bool XmlMode, JsonMode, MarkdownMode, SqlMode;

    // 纯文本不做任何语法着色：引号、数字、成员都保持正文色
    public static readonly LangDef Plain = new() { Strings = false, Chars = false, Numbers = false };
    public static readonly LangDef CCpp = CCpp_();
    public static readonly LangDef CSharp = CSharp_();
    public static readonly LangDef Java = Java_();
    public static readonly LangDef Js = Js_();
    public static readonly LangDef Go = Go_();
    public static readonly LangDef Rust = Rust_();
    public static readonly LangDef Clike = Clike_();
    public static readonly LangDef Python = Python_();
    public static readonly LangDef Json = Json_();
    public static readonly LangDef Xml = Xml_();
    public static readonly LangDef Markdown = Markdown_();
    public static readonly LangDef Sql = Sql_();

    public static readonly LangDef[] All = { Plain, CCpp, CSharp, Java, Js, Go, Rust, Clike, Python, Json, Xml, Markdown, Sql };

    /// <summary>大家族判断：C 风格花括号语言（共用折叠/参数提示/格式化行为）。</summary>
    public static bool IsCLike(string langId) =>
        langId is "clike" or "ccpp" or "csharp" or "java" or "js" or "go" or "rust";

    static LangDef CCpp_()
    {
        var d = new LangDef
        {
            Id = "ccpp",
            Name = "C / C++",
            LineComments = new[] { "//" },
            BlockComment = ("/*", "*/"),
            DocLineComment = "///",
            DocBlockOpen = "/**",
            PreprocSupport = true,
        };
        d.ControlWords = new[] { "if","else","for","while","do","switch","case","default",
            "break","continue","return","goto","throw","try","catch","finally","using",
            "new","delete","sizeof","typeof","this","in" };
        d.Keywords = new[] { "abstract","class","const","constexpr","enum","explicit","extern",
            "friend","inline","namespace","operator","override","private","protected","public",
            "struct","template","typedef","union","virtual","volatile","nullptr","final",
            "mutable","noexcept","decltype","static","true","false" };
        d.Types = new[] { "bool","char","double","float","int","long","short","void","auto",
            "size_t","string","wchar_t","int8_t","int16_t","int32_t","int64_t",
            "uint8_t","uint16_t","uint32_t","uint64_t" };
        return d;
    }

    static LangDef Java_()
    {
        var d = new LangDef
        {
            Id = "java",
            Name = "Java",
            LineComments = new[] { "//" },
            BlockComment = ("/*", "*/"),
            DocLineComment = "///",
            DocBlockOpen = "/**",
        };
        d.ControlWords = new[] { "if","else","for","while","do","switch","case","default",
            "break","continue","return","throw","try","catch","finally","new","instanceof",
            "this","super","assert","extends","implements","import","package","in" };
        d.Keywords = new[] { "abstract","class","interface","enum","final","native","private",
            "protected","public","static","strictfp","synchronized","transient","volatile",
            "record","sealed","permits","void","true","false","null" };
        d.Types = new[] { "boolean","byte","char","double","float","int","long","short","String","var" };
        return d;
    }

    static LangDef Js_()
    {
        var d = new LangDef
        {
            Id = "js",
            Name = "JavaScript / TypeScript",
            LineComments = new[] { "//" },
            BlockComment = ("/*", "*/"),
            DocLineComment = "///",
            DocBlockOpen = "/**",
        };
        d.ControlWords = new[] { "if","else","for","while","do","switch","case","default",
            "break","continue","return","throw","try","catch","finally","new","delete",
            "typeof","instanceof","in","of","this","super","yield","await","import",
            "export","from","as","void" };
        d.Keywords = new[] { "function","class","const","let","var","async","static","get","set",
            "extends","implements","interface","enum","type","namespace","declare","public",
            "private","protected","readonly","abstract","keyof","infer","satisfies",
            "undefined","null","true","false" };
        d.Types = new[] { "number","string","boolean","any","unknown","never","object","symbol","bigint" };
        return d;
    }

    static LangDef Go_()
    {
        var d = new LangDef
        {
            Id = "go",
            Name = "Go",
            LineComments = new[] { "//" },
            BlockComment = ("/*", "*/"),
            DocLineComment = "///",
            DocBlockOpen = "/**",
        };
        d.ControlWords = new[] { "if","else","for","range","switch","case","default",
            "break","continue","return","goto","fallthrough","go","defer","select","chan",
            "map","type","func","package","import","var","const","struct","interface" };
        d.Keywords = new[] { "nil","true","false","iota","recover","panic","make","new",
            "len","cap","append","copy","delete" };
        d.Types = new[] { "bool","string","error","any","int","int8","int16","int32","int64",
            "uint","uint8","uint16","uint32","uint64","uintptr","byte","rune",
            "float32","float64","complex64","complex128" };
        return d;
    }

    static LangDef Rust_()
    {
        var d = new LangDef
        {
            Id = "rust",
            Name = "Rust",
            LineComments = new[] { "//" },
            BlockComment = ("/*", "*/"),
            DocLineComment = "///",
            DocBlockOpen = "/**",
        };
        d.ControlWords = new[] { "if","else","match","loop","while","for","in","break","continue",
            "return","fn","let","mut","const","static","use","mod","crate","self","super",
            "where","async","await","move","ref","as","dyn","impl","trait","type","pub",
            "enum","struct","unsafe" };
        d.Keywords = new[] { "true","false","Some","None","Ok","Err","macro_rules" };
        d.Types = new[] { "i8","i16","i32","i64","i128","isize","u8","u16","u32","u64","u128",
            "usize","f32","f64","bool","char","str","String","Vec","Option","Result","Box" };
        return d;
    }

    static LangDef Clike_()
    {
        var d = new LangDef
        {
            Id = "clike",
            Name = "C 风格其他 (Swift/Kotlin/PHP/Dart…)",
            LineComments = new[] { "//" },
            BlockComment = ("/*", "*/"),
            DocLineComment = "///",
            DocBlockOpen = "/**",
            PreprocSupport = true,
        };
        d.ControlWords = new[] { "if","else","for","foreach","while","do","switch","case","default",
            "break","continue","return","goto","throw","try","catch","finally","using","lock",
            "await","yield","in","new","delete","sizeof","typeof","nameof","is","as","base","this" };
        d.Keywords = new[] { "abstract","async","class","const","constexpr","delegate","enum","event",
            "explicit","extern","final","friend","impl","implements","inline","interface","internal",
            "let","mut","namespace","operator","out","override","package","params","partial","private",
            "protected","public","readonly","record","ref","sealed","static","struct","template",
            "throws","transient","virtual","void","volatile","var","val","func","fn","pub","crate",
            "unsafe","with","extends","super","import","from","export","def","end","nil","null","true","false" };
        d.Types = new[] { "bool","byte","char","double","float","int","long","short","sbyte","string",
            "uint","ulong","ushort","object","decimal","dynamic","str","i8","i16","i32","i64","u8","u16",
            "u32","u64","usize","isize","f32","f64","boolean","number","any","unknown","never","auto" };
        return d;
    }

    static LangDef CSharp_()
    {
        var d = new LangDef
        {
            Id = "csharp",
            Name = "C#",
            LineComments = new[] { "//" },
            BlockComment = ("/*", "*/"),
            DocLineComment = "///",
            DocBlockOpen = "/**",
            PreprocSupport = true,
        };
        d.ControlWords = new[] { "if","else","for","foreach","while","do","switch","case","default",
            "break","continue","return","goto","throw","try","catch","finally","using","lock",
            "await","yield","in","new","sizeof","typeof","nameof","is","as","base","this",
            "when","and","or","not","checked","unchecked","unsafe","fixed","stackalloc" };
        d.Keywords = new[] { "abstract","async","class","const","delegate","enum","event","explicit",
            "extern","interface","internal","operator","out","override","params","partial","private",
            "protected","public","readonly","record","ref","sealed","static","struct","virtual",
            "void","volatile","get","set","init","value","add","remove","where","select","from",
            "orderby","group","let","into","join","on","equals","namespace","global","file","scoped",
            "required","nullable","dynamic","extension","alias","null","true","false" };
        d.Types = new[] { "bool","byte","char","decimal","double","float","int","long","short","sbyte",
            "string","uint","ulong","ushort","object","nint","nuint","var" };
        return d;
    }

    static LangDef Python_()
    {
        var d = new LangDef { Id = "python", Name = "Python", LineComments = new[] { "#" } };
        d.ControlWords = new[] { "if","elif","else","for","while","break","continue","return","def",
            "lambda","pass","raise","try","except","finally","with","yield","in","is","not","and","or",
            "import","from","as","assert","match","case","global","nonlocal","del" };
        d.Keywords = new[] { "class","None","True","False","self","async","await" };
        d.Types = Array.Empty<string>();
        return d;
    }

    static LangDef Json_()
    {
        var d = new LangDef { Id = "json", Name = "JSON", JsonMode = true, Strings = true, Chars = false };
        d.Keywords = new[] { "true","false","null" };
        return d;
    }

    static LangDef Xml_()
    {
        var d = new LangDef { Id = "xml", Name = "XML / HTML", XmlMode = true, Strings = true, Chars = false };
        d.LineComments = Array.Empty<string>();
        return d;
    }

    static LangDef Markdown_()
    {
        var d = new LangDef { Id = "markdown", Name = "Markdown", MarkdownMode = true };
        return d;
    }

    static LangDef Sql_()
    {
        var d = new LangDef
        {
            Id = "sql", Name = "SQL", SqlMode = true,
            LineComments = new[] { "--" },
            BlockComment = ("/*", "*/"),
            Strings = true, Chars = false,
        };
        d.ControlWords = new[] { "SELECT","FROM","WHERE","INSERT","INTO","VALUES","UPDATE","SET","DELETE",
            "CREATE","DROP","ALTER","TABLE","INDEX","VIEW","JOIN","LEFT","RIGHT","INNER","OUTER","FULL",
            "ON","GROUP","BY","ORDER","HAVING","LIMIT","OFFSET","UNION","ALL","DISTINCT","AS","AND","OR",
            "NOT","NULL","IS","IN","BETWEEN","LIKE","EXISTS","CASE","WHEN","THEN","ELSE","END","COMMIT",
            "ROLLBACK","BEGIN","PRIMARY","KEY","FOREIGN","REFERENCES","DEFAULT","CONSTRAINT" };
        return d;
    }

    public static LangDef FromFileName(string path)
    {
        string ext = Path.GetExtension(path).ToLowerInvariant();
        return ext switch
        {
            ".cs" or ".csx" => CSharp,
            ".c" or ".cc" or ".cpp" or ".cxx" or ".h" or ".hpp" => CCpp,
            ".java" => Java,
            ".js" or ".jsx" or ".mjs" or ".ts" or ".tsx" => Js,
            ".go" => Go,
            ".rs" => Rust,
            ".swift" or ".kt" or ".php" or ".dart" or ".scala" or ".r" or ".m" => Clike,
            ".py" or ".pyw" => Python,
            ".json" or ".jsonc" => Json,
            ".xml" or ".html" or ".htm" or ".xaml" or ".xaml.cs" or ".svg" or ".csproj" or
            ".props" or ".targets" or ".config" or ".resx" => Xml,
            ".md" or ".markdown" => Markdown,
            ".sql" => Sql,
            _ => Plain,
        };
    }

    public bool PreprocSupport;
}

/// <summary>逐行词法着色，跨行维护块注释/XML标签状态。</summary>
public static class Tokenizer
{
    /// <summary>整篇分词入口：按行切分逐行分词（换行统一 \n），
    /// 行注释/未闭合字符串只作用于本行，块注释与文档块状态跨行传递。
    /// 产出的区间偏移已换算成整篇文档坐标。</summary>
    public static void TokenizeDocument(LangDef lang, string text, List<TokenSpan> output)
    {
        int n = text.Length;
        if (n == 0) return;
        var hst = new HlState();
        int start = 0;
        while (start < n)
        {
            int nl = text.IndexOf('\n', start);
            int end = nl < 0 ? n : nl;
            if (end > start)
            {
                var lineToks = new List<TokenSpan>();
                Tokenize(lang, text[start..end], ref hst, lineToks);
                foreach (var t in lineToks)
                    output.Add(new(t.Start + start, t.Length, t.Kind));
            }
            if (nl < 0) break;
            start = nl + 1;
        }
    }

    public static void Tokenize(LangDef lang, string text, ref HlState st, List<TokenSpan> output)
    {
        if (lang.MarkdownMode) { Markdown(lang, text, output); return; }
        if (lang.XmlMode) { XmlMode(lang, text, ref st, output); return; }

        int i = 0, n = text.Length;

        // 跨行文档注释块（/** ... */）
        if (st.DocBlock)
        {
            int close = text.IndexOf("*/", StringComparison.Ordinal);
            if (close < 0)
            {
                output.Add(new(0, n, TokKind.DocComment));
                return;
            }
            output.Add(new(0, close + 2, TokKind.DocComment));
            st.DocBlock = false;
            i = close + 2;
        }

        // 跨行块注释
        if (st.BlockComment)
        {
            int close = lang.BlockComment is { } bc ? text.IndexOf(bc.Close, StringComparison.Ordinal) : -1;
            if (close < 0)
            {
                output.Add(new(0, n, TokKind.Comment));
                return;
            }
            int end = close + (lang.BlockComment!.Value.Close.Length);
            output.Add(new(0, end, TokKind.Comment));
            st.BlockComment = false;
            i = end;
        }

        while (i < n)
        {
            char c = text[i];

            // 文档注释行（如 ///）：必须先于普通行注释判断（前缀更长）
            if (lang.DocLineComment is { } dl && dl.Length > 0 && i + dl.Length <= n &&
                text.AsSpan(i, dl.Length).SequenceEqual(dl))
            {
                output.Add(new(i, n - i, TokKind.DocComment));
                i = n;
                break;
            }

            // 行注释
            bool lineCmt = false;
            foreach (var lc in lang.LineComments)
            {
                if (lc.Length > 0 && i + lc.Length <= n && text.AsSpan(i, lc.Length).SequenceEqual(lc))
                {
                    output.Add(new(i, n - i, TokKind.Comment));
                    i = n;
                    lineCmt = true;
                    break;
                }
            }
            if (lineCmt) break;

            // 文档注释块（如 /**）：先于普通块注释判断
            if (lang.DocBlockOpen is { } dbo && i + dbo.Length <= n &&
                text.AsSpan(i, dbo.Length).SequenceEqual(dbo))
            {
                int close = text.IndexOf("*/", i + dbo.Length, StringComparison.Ordinal);
                if (close < 0)
                {
                    output.Add(new(i, n - i, TokKind.DocComment));
                    st.DocBlock = true;
                    return;
                }
                output.Add(new(i, close + 2 - i, TokKind.DocComment));
                i = close + 2;
                continue;
            }

            // 块注释
            if (lang.BlockComment is { } bc2 && i + bc2.Open.Length <= n &&
                text.AsSpan(i, bc2.Open.Length).SequenceEqual(bc2.Open))
            {
                int close = text.IndexOf(bc2.Close, i + bc2.Open.Length, StringComparison.Ordinal);
                if (close < 0)
                {
                    output.Add(new(i, n - i, TokKind.Comment));
                    st.BlockComment = true;
                    return;
                }
                int end = close + bc2.Close.Length;
                output.Add(new(i, end - i, TokKind.Comment));
                i = end;
                continue;
            }

            // 字符串
            if (lang.Strings && (c == '"' || c == '\''))
            {
                int j = i + 1;
                while (j < n)
                {
                    if (text[j] == '\\') { j += 2; continue; }
                    if (text[j] == c) { j++; break; }
                    j++;
                }
                output.Add(new(i, Math.Min(j, n) - i, TokKind.String));
                i = Math.Min(j, n);
                continue;
            }

            // 字符字面量
            if (lang.Chars && c == '\'')
            {
                int j = i + 1;
                while (j < n && text[j] != '\'') { if (text[j] == '\\') j++; j++; }
                output.Add(new(i, Math.Min(j + 1, n) - i, TokKind.String));
                i = Math.Min(j + 1, n);
                continue;
            }

            // 预处理行（#开头，C 系）
            if (lang.PreprocSupport && c == '#' && (i == 0 || char.IsWhiteSpace(text[i - 1])))
            {
                output.Add(new(i, n - i, TokKind.Preproc));
                i = n;
                continue;
            }

            // 数字
            if (lang.Numbers && char.IsDigit(c))
            {
                int j = i + 1;
                while (j < n && (char.IsLetterOrDigit(text[j]) || text[j] == '.' || text[j] == '_')) j++;
                output.Add(new(i, j - i, TokKind.Number));
                i = j;
                continue;
            }

            // 标识符 / 关键字
            if (char.IsLetter(c) || c == '_')
            {
                int j = i + 1;
                while (j < n && (char.IsLetterOrDigit(text[j]) || text[j] == '_')) j++;
                string word = text[i..j];
                TokKind k = Classify(lang, word);
                if (k == TokKind.Text && lang.Id != "plain")
                {
                    // 成员名：紧邻'.'之后（对象/成员着色）
                    int p = i - 1;
                    while (p >= 0 && text[p] == ' ') p--;
                    if (p >= 0 && text[p] == '.') k = TokKind.Member;
                    // 类型名：大写开头（C 系家族与 Python 的类名约定，全家族统一）
                    else if (char.IsUpper(word[0]) && (lang.Id == "python" || LangDef.IsCLike(lang.Id)))
                        k = TokKind.Type;
                }
                if (k != TokKind.Text) output.Add(new(i, j - i, k));
                i = j;
                continue;
            }

            i++;
        }
    }

    static TokKind Classify(LangDef lang, string word)
    {
        // SQL 关键字不分大小写，且统一用"关键字"色（蓝），不占用控制流色——
        // 品红控制流色是 C 系 if/else 的语义，全大写 SQL 用它显得杂乱
        if (lang.SqlMode)
        {
            if (lang.ControlWords.Contains(word, StringComparer.OrdinalIgnoreCase)) return TokKind.Keyword;
            if (lang.Keywords.Contains(word, StringComparer.OrdinalIgnoreCase)) return TokKind.Keyword;
            if (lang.Types.Contains(word, StringComparer.OrdinalIgnoreCase)) return TokKind.Type;
            return TokKind.Text;
        }
        if (lang.ControlWords.Contains(word, StringComparer.Ordinal)) return TokKind.Control;
        if (lang.Keywords.Contains(word, StringComparer.Ordinal)) return TokKind.Keyword;
        if (lang.Types.Contains(word, StringComparer.Ordinal)) return TokKind.Type;
        return TokKind.Text;
    }

    static void XmlMode(LangDef lang, string text, ref HlState st, List<TokenSpan> output)
    {
        int i = 0, n = text.Length;

        if (st.BlockComment)
        {
            int close = text.IndexOf("-->", StringComparison.Ordinal);
            if (close < 0) { output.Add(new(0, n, TokKind.Comment)); return; }
            output.Add(new(0, close + 3, TokKind.Comment));
            st.BlockComment = false;
            i = close + 3;
        }

        bool inTag = st.XmlTag;
        while (i < n)
        {
            if (inTag)
            {
                if (text[i] == '>') { inTag = false; i++; continue; }
                if (char.IsLetter(text[i]))
                {
                    int j = i + 1;
                    while (j < n && (char.IsLetterOrDigit(text[j]) || text[j] == '_' || text[j] == ':' || text[j] == '-')) j++;
                    output.Add(new(i, j - i, TokKind.Tag));
                    i = j;
                    continue;
                }
                if (text[i] == '"')
                {
                    int j = i + 1;
                    while (j < n && text[j] != '"') j++;
                    output.Add(new(i, Math.Min(j + 1, n) - i, TokKind.String));
                    i = Math.Min(j + 1, n);
                    continue;
                }
                i++;
            }
            else
            {
                int lt = text.IndexOf('<', i);
                if (lt < 0) break;
                // 标签起点处的注释统一在这里处理，注释区间包含 '<'
                if (text[lt..].StartsWith("<!--", StringComparison.Ordinal))
                {
                    int close = text.IndexOf("-->", lt, StringComparison.Ordinal);
                    if (close < 0)
                    {
                        output.Add(new(lt, n - lt, TokKind.Comment));
                        st.BlockComment = true;
                        st.XmlTag = false;
                        return;
                    }
                    output.Add(new(lt, close + 3 - lt, TokKind.Comment));
                    i = close + 3;
                    continue;
                }
                inTag = true;
                i = lt + 1;
            }
        }
        st.XmlTag = inTag;
    }

    static void Markdown(LangDef lang, string text, List<TokenSpan> output)
    {
        if (text.Length == 0) return;

        // 标题行
        int h = 0;
        while (h < text.Length && text[h] == '#') h++;
        if (h > 0 && h <= 6 && (h >= text.Length || text[h] == ' '))
        {
            output.Add(new(0, text.Length, TokKind.Heading));
            return;
        }

        // 行内：`code`、**粗体**
        int i = 0;
        while (i < text.Length)
        {
            if (text[i] == '`')
            {
                int close = text.IndexOf('`', i + 1);
                if (close > i)
                {
                    output.Add(new(i, close + 1 - i, TokKind.String));
                    i = close + 1;
                    continue;
                }
            }
            if (i + 1 < text.Length && text[i] == '*' && text[i + 1] == '*')
            {
                int close = text.IndexOf("**", i + 2, StringComparison.Ordinal);
                if (close > 0)
                {
                    output.Add(new(i, close + 2 - i, TokKind.Control));
                    i = close + 2;
                    continue;
                }
            }
            i++;
        }
    }
}
