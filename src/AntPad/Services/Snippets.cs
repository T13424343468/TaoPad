//using AntPad.Syntax;

namespace AntPad.Services;

/// <summary>代码片段：输入缩写后按 Tab 展开，$0 为展开后光标位置。</summary>
public sealed record Snippet(string Key, string Body)
{
    public string Label => Key + " → " + Body.Split('\n')[0].Replace("$0", "").Trim() + "…";
}

/// <summary>按语言分组的片段表（LangDef.Id → 片段列表）。</summary>
public static class Snippets
{
    static readonly Dictionary<string, List<Snippet>> ByLang = new()
    {
        ["ccpp"] = new()
        {
            new("for", "for (int i = 0; i < len; i++)\n{\n    $0\n}"),
            new("while", "while (condition)\n{\n    $0\n}"),
            new("if", "if (condition)\n{\n    $0\n}"),
            new("ifelse", "if (condition)\n{\n    $0\n}\nelse\n{\n    \n}"),
            new("main", "int main(int argc, char* argv[])\n{\n    $0\n    return 0;\n}"),
            new("struct", "struct Name\n{\n    $0\n};"),
            new("try", "try\n{\n    $0\n}\ncatch (const std::exception& ex)\n{\n    \n}"),
        },
        ["java"] = new()
        {
            new("for", "for (int i = 0; i < len; i++)\n{\n    $0\n}"),
            new("foreach", "for (var item : collection)\n{\n    $0\n}"),
            new("if", "if (condition)\n{\n    $0\n}"),
            new("ifelse", "if (condition)\n{\n    $0\n}\nelse\n{\n    \n}"),
            new("main", "public static void main(String[] args)\n{\n    $0\n}"),
            new("sysout", "System.out.println($0);"),
            new("class", "public class Name\n{\n    $0\n}"),
            new("try", "try\n{\n    $0\n}\ncatch (Exception ex)\n{\n    \n}"),
        },
        ["js"] = new()
        {
            new("for", "for (let i = 0; i < len; i++)\n{\n    $0\n}"),
            new("forof", "for (const item of items)\n{\n    $0\n}"),
            new("fun", "function name(args)\n{\n    $0\n}"),
            new("arrow", "const name = (args) =>\n{\n    $0\n};"),
            new("if", "if (condition)\n{\n    $0\n}"),
            new("log", "console.log($0);"),
            new("try", "try\n{\n    $0\n}\ncatch (err)\n{\n    \n}"),
            new("class", "class Name\n{\n    constructor()\n    {\n        $0\n    }\n}"),
        },
        ["go"] = new()
        {
            new("func", "func name(args)\n{\n    $0\n}"),
            new("main", "func main()\n{\n    $0\n}"),
            new("iferr", "if err != nil\n{\n    return $0\n}"),
            new("forrange", "for i, v := range items\n{\n    $0\n}"),
            new("struct", "type Name struct\n{\n    $0\n}"),
        },
        ["rust"] = new()
        {
            new("fn", "fn name(args)\n{\n    $0\n}"),
            new("main", "fn main()\n{\n    $0\n}"),
            new("match", "match value\n{\n    pat => $0,\n    _ => {},\n}"),
            new("impl", "impl Name\n{\n    pub fn new() -> Self\n    {\n        $0\n    }\n}"),
            new("test", "#[test]\nfn it_works()\n{\n    $0\n}"),
        },
        ["clike"] = new()
        {
            new("for", "for (var i = 0; i < len; i++)\n{\n    $0\n}"),
            new("if", "if (condition)\n{\n    $0\n}"),
            new("class", "class Name\n{\n    public $0\n}"),
        },
        ["python"] = new()
        {
            new("def", "def function(arg):\n    $0"),
            new("class", "class Name:\n    def __init__(self):\n        $0"),
            new("for", "for item in items:\n    $0"),
            new("while", "while condition:\n    $0"),
            new("ifmain", "if __name__ == \"__main__\":\n    $0"),
            new("with", "with open(path) as f:\n    $0"),
        },
        ["csharp"] = new()
        {
            new("for", "for (int i = 0; i < len; i++)\n{\n    $0\n}"),
            new("foreach", "foreach (var item in collection)\n{\n    $0\n}"),
            new("while", "while (condition)\n{\n    $0\n}"),
            new("if", "if (condition)\n{\n    $0\n}"),
            new("ifelse", "if (condition)\n{\n    $0\n}\nelse\n{\n    \n}"),
            new("class", "class Name\n{\n    public $0\n}"),
            new("try", "try\n{\n    $0\n}\ncatch (Exception ex)\n{\n    \n}"),
            new("prop", "public int Name { get; set; }$0"),
            new("cw", "Console.WriteLine($0);"),
            new("usingns", "using System;\nusing System.Collections.Generic;\nusing System.Linq;\n\n$0"),
            new("method", "public void Name()\n{\n    $0\n}"),
        },
        ["sql"] = new()
        {
            new("sel", "SELECT *\nFROM table\nWHERE condition;$0"),
            new("join", "SELECT *\nFROM a\nJOIN b ON a.id = b.a_id;$0"),
            new("upd", "UPDATE table\nSET col = value\nWHERE condition;$0"),
            new("del", "DELETE FROM table\nWHERE condition;$0"),
        },
        ["markdown"] = new()
        {
            new("table", "| 列一 | 列二 |\n| --- | --- |\n|  $0 |  |"),
            new("code", "```lang\n$0\n```"),
        },
        ["json"] = new()
        {
            new("obj", "{\n    \"key\": $0\n}"),
            new("arr", "[\n    $0\n]"),
        },
    };

    /// <summary>取指定语言的片段；未知语言返回空表。</summary>
    public static IReadOnlyList<Snippet> For(string langId) =>
        ByLang.TryGetValue(langId, out var list) ? list : Array.Empty<Snippet>();

    /// <summary>片段展开：把正文按当前行缩进重排，返回 (展开文本, 光标相对偏移)。</summary>
    public static (string Text, int CaretOffset) Expand(Snippet sn, string indent)
    {
        var sb = new System.Text.StringBuilder();
        int caret = 0;
        var lines = sn.Body.Split('\n');
        for (int i = 0; i < lines.Length; i++)
        {
            if (i > 0) sb.Append('\n').Append(indent);
            var line = lines[i];
            int p = line.IndexOf("$0", StringComparison.Ordinal);
            if (p >= 0)
            {
                caret = sb.Length + p;
                sb.Append(line.Remove(p, 2));
            }
            else sb.Append(line);
        }
        if (caret == 0) caret = sb.Length;
        return (sb.ToString(), caret);
    }
}
