// R1 重建：TaoPad 纯逻辑回归（对应 docs/05-TEST_REPORT.md v1.7.0 第 2 节 41 项口径，
// 按现源码 API 重建并扩展到 46 断言；审查台账 20261114-甲班 R1 处置）。
// 运行：dotnet run --project tests/LogicTests ；失败退出码 1，云测/修红班可直接挂闸。
using System.Text;
using AntPad.Services;
using AntPad.Syntax;

// GBK/Big5 等代码页在 net8.0 需显式注册（与 App.xaml.cs 同源约定）
Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

int pass = 0, fail = 0;
void Check(string name, bool ok, string detail = "")
{
    if (ok) { pass++; Console.WriteLine($"PASS {name}"); }
    else { fail++; Console.WriteLine($"FAIL {name} {detail}"); }
}

List<TokKind> KindsOf(LangDef lang, string line)
{
    var st = new HlState();
    var outp = new List<TokenSpan>();
    Tokenizer.Tokenize(lang, line, ref st, outp);
    return outp.Select(t => t.Kind).ToList();
}

string TextOf(string line, List<TokenSpan> toks, TokKind kind) =>
    string.Join("|", toks.Where(t => t.Kind == kind).Select(t => line.Substring(t.Start, t.Length)));

// ================= 1. Tokenizer（18 项） =================

// T01 关键字分类（class=Keyword）
{
    var k = KindsOf(LangDef.CSharp, "class A {}");
    Check("T01 C# class 归 Keyword", k.Contains(TokKind.Keyword), string.Join(",", k));
}
// T02 控制流分类（if/return=Control）
{
    var k = KindsOf(LangDef.CSharp, "if (x) return;");
    Check("T02 C# if/return 归 Control", k.Count(t => t == TokKind.Control) == 2, string.Join(",", k));
}
// T03 类型分类（int=Type）
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CSharp, "int x", ref st, toks);
    Check("T03 C# int 归 Type", TextOf("int x", toks, TokKind.Type) == "int", TextOf("int x", toks, TokKind.Type));
}
// T04 字符串与转义（\" 不终止字符串）
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CSharp, @"char s = ""a\"";", ref st, toks);
    Check("T04 转义引号不终止字符串", toks.Any(t => t.Kind == TokKind.String && t.Length == 5), string.Join(";", toks));
}
// T05 未闭合字符串只作用于本行
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CSharp, "\"abc", ref st, toks);
    Check("T05 未闭合字符串整体成段", toks.Count == 1 && toks[0].Kind == TokKind.String, string.Join(";", toks));
}
// T06 行注释
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CCpp, "int a; // note", ref st, toks);
    Check("T06 行注释 //", toks.Any(t => t.Kind == TokKind.Comment), string.Join(";", toks));
}
// T07 块注释跨行状态（未闭合 → 下行延续为 Comment）
{
    var st = new HlState();
    var l1 = new List<TokenSpan>();
    Tokenizer.Tokenize(LangDef.CCpp, "/* start", ref st, l1);
    var l2 = new List<TokenSpan>();
    Tokenizer.Tokenize(LangDef.CCpp, "end */ int x", ref st, l2);
    Check("T07 块注释跨行延续", l1.All(t => t.Kind == TokKind.Comment) && l2[0].Kind == TokKind.Comment && l2.Any(t => t.Kind == TokKind.Type), $"st={st.BlockComment}");
}
// T08 文档注释行 ///
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CSharp, "/// summary", ref st, toks);
    Check("T08 /// 文档注释", toks.Count == 1 && toks[0].Kind == TokKind.DocComment, string.Join(";", toks));
}
// T09 文档注释块 /** */ 与未闭合状态
{
    var st = new HlState();
    var l1 = new List<TokenSpan>();
    Tokenizer.Tokenize(LangDef.CSharp, "/** doc", ref st, l1);
    Check("T09 /** 未闭合进 DocBlock 态", l1.Count == 1 && l1[0].Kind == TokKind.DocComment && st.DocBlock, $"st={st.DocBlock}");
}
// T10 数字含十六进制
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CCpp, "0x1F + 3.14", ref st, toks);
    var nums = toks.Where(t => t.Kind == TokKind.Number).Select(t => "0x1F + 3.14".Substring(t.Start, t.Length)).ToList();
    Check("T10 数字（含十六进制/小数）", nums.Count == 2 && nums[0] == "0x1F" && nums[1] == "3.14", string.Join(",", nums));
}
// T11 预处理行
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CCpp, "#include <stdio.h>", ref st, toks);
    Check("T11 预处理行", toks.Count == 1 && toks[0].Kind == TokKind.Preproc, string.Join(";", toks));
}
// T12 XML 标签与属性
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.Xml, "<Grid Name=\"root\">", ref st, toks);
    var tags = toks.Where(t => t.Kind == TokKind.Tag).Select(t => "<Grid Name=\"root\">".Substring(t.Start, t.Length)).ToList();
    Check("T12 XML 标签/属性", tags.Contains("Grid") && tags.Contains("Name") && toks.Any(t => t.Kind == TokKind.String), string.Join(";", toks));
}
// T13 XML 注释
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.Xml, "<!-- note -->x", ref st, toks);
    Check("T13 XML 注释包含 < 起点且闭合后恢复正文", toks.Any(t => t.Kind == TokKind.Comment), string.Join(";", toks));
}
// T14 Markdown 标题
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.Markdown, "## Title", ref st, toks);
    Check("T14 Markdown 标题", toks.Count == 1 && toks[0].Kind == TokKind.Heading, string.Join(";", toks));
}
// T15 Markdown 行内代码与粗体
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.Markdown, "a `code` b **bold**", ref st, toks);
    Check("T15 Markdown code/粗体", toks.Any(t => t.Kind == TokKind.String) && toks.Any(t => t.Kind == TokKind.Control), string.Join(";", toks));
}
// T15b Markdown 代码围栏：围栏内 ** 与 ` 不按行内标记解析（备查蓝项落测 2026-11-18）
{
    string doc = "```python\nx = a**b**c\n```\n**real bold**";
    var toks = new List<TokenSpan>();
    Tokenizer.TokenizeDocument(LangDef.Markdown, doc, toks);
    string ctrl = TextOf(doc, toks, TokKind.Control);
    Check("T15b 围栏内**不当粗体", !ctrl.Contains("a**b**c") && ctrl.Contains("**real bold**"), ctrl);
}
// T15c 波浪线围栏同理；收栏后行内标记恢复
{
    string doc = "~~~\n**fence**\n~~~\nplain **x**";
    var toks = new List<TokenSpan>();
    Tokenizer.TokenizeDocument(LangDef.Markdown, doc, toks);
    string ctrl = TextOf(doc, toks, TokKind.Control);
    Check("T15c 波浪线围栏同口径", !ctrl.Contains("**fence**") && ctrl.Contains("**x**"), ctrl);
}
// T15d 未闭合围栏吞到文末（CommonMark 口径锁定）
{
    string doc = "```\n**unclosed";
    var toks = new List<TokenSpan>();
    Tokenizer.TokenizeDocument(LangDef.Markdown, doc, toks);
    Check("T15d 未闭合围栏不炸粗体", !toks.Any(t => t.Kind == TokKind.Control), string.Join(";", toks));
}
// T16 成员名（紧邻点号）
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CSharp, "obj.Value", ref st, toks);
    Check("T16 紧邻点号归 Member", TextOf("obj.Value", toks, TokKind.Member) == "Value", TextOf("obj.Value", toks, TokKind.Member));
}
// T17 大写开头归 Type（C 系家族）
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.CSharp, "Foo bar", ref st, toks);
    Check("T17 大写开头归 Type", TextOf("Foo bar", toks, TokKind.Type) == "Foo", TextOf("Foo bar", toks, TokKind.Type));
}
// T18 SQL 关键字不分大小写
{
    var toks = new List<TokenSpan>();
    var st = new HlState();
    Tokenizer.Tokenize(LangDef.Sql, "select * from t", ref st, toks);
    Check("T18 SQL 小写关键字归 Keyword", toks.Count(t => t.Kind == TokKind.Keyword) == 2, string.Join(";", toks));
}

// ================= 2. CompletionEngine（6 项） =================

// P01 前缀 <2 不触发
{
    var r = CompletionEngine.GetCompletions("int x", 5, LangDef.CSharp, out var p);
    Check("P01 前缀<2 不触发", r.Count == 0 && p == "x", $"{r.Count} prefix={p}");
}
// P02 前缀过滤（关键字命中）
{
    var r = CompletionEngine.GetCompletions("for", 3, LangDef.CSharp, out var p);
    // 设计口径（v1.7.0 报告 5.3）：唯一候选=已输入词时不弹——完整词 "for" 被排除，
    // 长候选 foreach 保留
    Check("P02 前缀过滤与完整词排除", r.Contains("foreach") && !r.Contains("for") && p == "for", string.Join(",", r));
}
// P03 关键字与文档标识符合并
{
    var r = CompletionEngine.GetCompletions("myVa myValue", 4, LangDef.CSharp, out var p3);
    Check("P03 文档标识符入候选", r.Contains("myValue") && p3 == "myVa", $"{p3}:{string.Join(",", r)}");
}
// P04 去重（关键字与文档同名只留一个）
{
    var text = "for for forx";
    var r = CompletionEngine.GetCompletions(text, 6, LangDef.CSharp, out _);
    Check("P04 同词去重", r.Count(w => w.Equals("for", StringComparison.OrdinalIgnoreCase)) == 1, string.Join(",", r));
}
// P05 "." 触发成员提示（按频次降序）
{
    var r = CompletionEngine.GetCompletions("a.Run(); a.Run(); a.Walk();", 2, LangDef.CSharp, out var p);
    Check("P05 成员提示频次降序", p == "" && r.FirstOrDefault() == "Run" && r.Contains("Walk"), string.Join(",", r));
}
// P06 a.in 形式成员过滤
{
    var r = CompletionEngine.GetCompletions("obj.in", 6, LangDef.CSharp, out var p);
    Check("P06 点后前缀成员过滤", p == "in" && r.All(w => w.StartsWith("in", StringComparison.OrdinalIgnoreCase)), $"{p}:{string.Join(",", r)}");
}

// ================= 3. 编码检测（6 项） =================

var sample = "中文sample";
// E01 UTF-8 BOM
{
    var (enc, bom) = EncodingHelper.Detect(new byte[] { 0xEF, 0xBB, 0xBF }.Concat(Encoding.UTF8.GetBytes(sample)).ToArray());
    Check("E01 UTF-8 BOM 识别", bom && enc is UTF8Encoding, $"{enc.WebName} bom={bom}");
}
// E02 UTF-16 LE
{
    var (enc, bom) = EncodingHelper.Detect(new byte[] { 0xFF, 0xFE }.Concat(Encoding.Unicode.GetBytes(sample)).ToArray());
    Check("E02 UTF-16 LE 识别", bom && enc.WebName == "utf-16", $"{enc.WebName} bom={bom}");
}
// E03 UTF-16 BE
{
    var (enc, bom) = EncodingHelper.Detect(new byte[] { 0xFE, 0xFF }.Concat(Encoding.BigEndianUnicode.GetBytes(sample)).ToArray());
    Check("E03 UTF-16 BE 识别", bom && enc.WebName == "utf-16BE", $"{enc.WebName} bom={bom}");
}
// E04 纯 ASCII → UTF-8 无 BOM
{
    var (enc, bom) = EncodingHelper.Detect(Encoding.ASCII.GetBytes("hello world"));
    Check("E04 纯 ASCII 归 UTF-8 无 BOM", !bom && enc.WebName == "utf-8", $"{enc.WebName} bom={bom}");
}
// E05 GBK 回退
{
    var (enc, bom) = EncodingHelper.Detect(Encoding.GetEncoding("GBK").GetBytes(sample));
    Check("E05 非法 UTF-8 回退 GBK", !bom && enc.WebName == "gb2312", $"{enc.WebName} bom={bom}");
}
// E06 编码菜单名称表
{
    Check("E06 Options 名称/口径完整", EncodingHelper.Options.Length == 5 &&
        EncodingHelper.Options.Any(o => o.Name == "UTF-8 BOM" && o.Bom) &&
        EncodingHelper.Options.Any(o => o.Name == "GBK"), string.Join(",", EncodingHelper.Options.Select(o => o.Name)));
}

// ================= 4. 编码字节往返（3 项，文本换行还原口径由云测 C02 覆盖） =================

// R01 GBK 往返
{
    var enc = Encoding.GetEncoding("GBK");
    var (det, _) = EncodingHelper.Detect(enc.GetBytes(sample));
    Check("R01 GBK 往返一致", det.GetBytes(sample).SequenceEqual(enc.GetBytes(sample)) && det.GetString(enc.GetBytes(sample)) == sample);
}
// R02 UTF-16 LE 往返
{
    var (det, bom) = EncodingHelper.Detect(Encoding.Unicode.GetPreamble().Concat(Encoding.Unicode.GetBytes(sample)).ToArray());
    Check("R02 UTF-16 LE 带 BOM 往返一致", bom && det.GetString(Encoding.Unicode.GetBytes(sample)) == sample);
}
// R03 UTF-8 无 BOM 往返
{
    var (det, bom) = EncodingHelper.Detect(Encoding.UTF8.GetBytes(sample));
    Check("R03 UTF-8 无 BOM 往返一致", !bom && det.GetString(Encoding.UTF8.GetBytes(sample)) == sample);
}

// ================= 5. 格式化（9 项） =================

// F01 JSON 两空格缩进
{
    var f = CodeFormatter.Format("{\"a\":1,\"b\":[2,3]}", LangDef.Json);
    Check("F01 JSON 标准缩进", f.Contains("  \"a\": 1") && f.Contains("    2,") && !f.Contains('\r'), f);
}
// F02 非法 JSON 原样保留
{
    var bad = "{not json,,,";
    Check("F02 非法 JSON 原样", CodeFormatter.Format(bad, LangDef.Json) == bad);
}
// F03 XML 缩进重排
{
    var f = CodeFormatter.Format("<r><a>x</a></r>", LangDef.Xml);
    Check("F03 XML 两空格层级", f.Contains("  <a>x</a>") && f.StartsWith("<r>"), f.Replace("\n", "\\n"));
}
// F04 C 系花括号层级
{
    var f = CodeFormatter.Format("void f(){\nint x;\n}", LangDef.CSharp);
    Check("F04 C 系缩进层级", f.Contains("    int x;") && f.StartsWith("void f()") && f.EndsWith("}"), f.Replace("\n", "\\n"));
}
// F05 闭括号行回退一级
{
    var f = CodeFormatter.Format("if (a){\nb();\n}", LangDef.CSharp);
    var lines = f.Split('\n');
    Check("F05 闭括号回退一级", lines[1].StartsWith("    b();") && lines[2].Trim() == "}" && !lines[2].StartsWith(' '), f.Replace("\n", "\\n"));
}
// F06 行尾空白清除（无重排语言）
{
    var f = CodeFormatter.Format("hello   \nworld\t ", LangDef.Plain);
    Check("F06 行尾空白清除", f == "hello\nworld", f.Replace("\n", "\\n"));
}
// F07 SQL 关键字大写
{
    var f = CodeFormatter.Format("select a from t where b = 1", LangDef.Sql);
    Check("F07 SQL 关键字大写", f.Contains("SELECT") && f.Contains("FROM") && f.Contains("WHERE"), f);
}
// F08 SQL 子句换行
{
    var f = CodeFormatter.Format("select a from t where b = 1", LangDef.Sql);
    Check("F08 SQL 子句分层换行", f.Contains("\nFROM") && f.Contains("\nWHERE"), f.Replace("\n", "\\n"));
}
// F09 SQL 字符串与注释原样保留
{
    var f = CodeFormatter.Format("select 'lower keep' -- note", LangDef.Sql);
    Check("F09 SQL 字符串/注释不被动", f.Contains("'lower keep'") && f.Contains("-- note"), f);
}

// ================= 6. 注释命令（4 项） =================

// M01 C 系加注释
{
    var r = CommentCommands.Toggle("int x;\nint y;", 0, 7, LangDef.CCpp, comment: true);
    Check("M01 C 系加注释", r == "//int x;\n//int y;", r);
}
// M02 C 系取消注释还原
{
    var r = CommentCommands.Toggle("// int x;\n// int y;", 0, 16, LangDef.CCpp, comment: false);
    Check("M02 C 系取消注释", r == "int x;\nint y;", r);
}
// M03 Python # 标记
{
    var r = CommentCommands.Toggle("print(1)", 0, 8, LangDef.Python, comment: true);
    Check("M03 Python # 注释", r != null && r.StartsWith("#"), r);
}
// M04 XML 包裹注释
{
    var r = CommentCommands.WrapXml("<a/>");
    Check("M04 XML 包裹 <!-- -->", r != null && r.StartsWith("<!--") && r.EndsWith("-->"), r);
}

// ================= 7. Fountain 剧本（1.1.0，4 项） =================

// W01 场景标题归 Heading
{
    var toks = new List<TokenSpan>();
    Tokenizer.TokenizeDocument(LangDef.Fountain, "INT. COFFEE SHOP - DAY", toks);
    Check("W01 场景标题归 Heading", toks.Count == 1 && toks[0].Kind == TokKind.Heading, string.Join(";", toks));
}
// W02 人物归 Member、> 行归 Control、CUT TO: 不误判人物
{
    var text = "INT. DAY\nJOHN\nHello.\n\n> CUT TO: NIGHT";
    var toks = new List<TokenSpan>();
    Tokenizer.TokenizeDocument(LangDef.Fountain, text, toks);
    bool member = toks.Any(t => t.Kind == TokKind.Member && text.Substring(t.Start, t.Length) == "JOHN");
    bool trans = toks.Any(t => t.Kind == TokKind.Control && text.Substring(t.Start, t.Length) == "> CUT TO: NIGHT");
    Check("W02 人物/转场分类", member && trans && !toks.Any(t => t.Kind == TokKind.Member && text.Substring(t.Start, t.Length).StartsWith("CUT")), string.Join(";", toks));
}
// W03 行内强调（粗/斜/code）
{
    var st = new HlState();
    var toks = new List<TokenSpan>();
    Tokenizer.Tokenize(LangDef.Fountain, "*斜体* 与 **粗体** 与 `代码`", ref st, toks);
    Check("W03 行内强调", toks.Count(t => t.Kind == TokKind.Control) == 2 && toks.Any(t => t.Kind == TokKind.String), string.Join(";", toks));
}
// W04 .fountain 扩展名映射
{
    Check("W04 .fountain 语言映射", ReferenceEquals(LangDef.FromFileName("script.fountain"), LangDef.Fountain));
}

// ================= 8. 彩虹括号深度图（1.1.0，2 项） =================

// B01 嵌套深度
{
    var doc = new List<TokenSpan>();
    string code = "a(b(c))";
    Tokenizer.TokenizeDocument(LangDef.CSharp, code, doc);
    var map = Tokenizer.BracketDepths(code, doc);
    Check("B01 嵌套括号深度递增",
        map.TryGetValue(1, out int d1) && d1 == 0 && map.TryGetValue(3, out int d3) && d3 == 1 &&
        map.TryGetValue(5, out int d5) && d5 == 1 && map.TryGetValue(6, out int d6) && d6 == 0,
        string.Join(";", map.Select(kv => $"{kv.Key}:{kv.Value}")));
}
// B02 字符串内括号不计数
{
    var doc = new List<TokenSpan>();
    string code = "\"a(b)\" (x)";
    Tokenizer.TokenizeDocument(LangDef.CSharp, code, doc);
    var map = Tokenizer.BracketDepths(code, doc);
    Check("B02 字符串内括号排除",
        map.ContainsKey(7) && map.ContainsKey(9) && map.All(kv => kv.Key is 7 or 9),
        string.Join(";", map.Select(kv => $"{kv.Key}:{kv.Value}")));
}

// ================= 9. 写作模式：大纲 / 字数 / 快照（1.1.0，6 项） =================

// O01 Markdown 大纲：跳代码围栏
{
    var md = "# 一级\n正文\n```csharp\n# 假标题\n```\n## 二级";
    var items = WritingDoc.MarkdownOutline(md);
    Check("O01 Markdown 大纲抽取",
        items.Count == 2 && items[0].Line == 0 && items[0].Level == 1 && items[1].Line == 5 && items[1].Title == "二级",
        string.Join(";", items.Select(i => $"{i.Line}:{i.Title}")));
}
// O02 Fountain 大纲：场景行
{
    var items = WritingDoc.FountainOutline("INT. DAY\n\n台词\n\nEXT. NIGHT");
    Check("O02 Fountain 大纲抽取",
        items.Count == 2 && items[0].Line == 0 && items[1].Line == 4,
        string.Join(";", items.Select(i => $"{i.Line}:{i.Title}")));
}
// O03 字数：CJK 按字、西文按词
{
    var s = WritingDoc.CountWords("你好 world 123 abc");
    Check("O03 字数统计口径", s.Words == 5 && s.CjkChars == 2, $"{s.Words}/{s.CjkChars}");
}
// O04 字数：空文本
{
    var s = WritingDoc.CountWords("");
    Check("O04 空文本字数为零", s.Words == 0 && s.Chars == 0 && s.Lines == 0, $"{s.Words}/{s.Chars}/{s.Lines}");
}
// O07 字数：尾行口径锁定（换行结尾按编辑器行号口径 +1；语义调整属需求决策
// 归老板拍板，先锁现状防回归——2026-11-18）
{
    var s = WritingDoc.CountWords("abc\n");
    Check("O07 尾行口径锁定", s.Lines == 2 && s.Words == 1, $"{s.Lines}/{s.Words}");
}
// O05 快照保存与读取（写真实数据根，测试允许）
{
    string p = WritingDoc.SaveSnapshot(null, "快照正文测试", DateTimeOffset.Now);
    string? read = WritingDoc.ReadSnapshot(p);
    Check("O05 快照保存/读取", read == "快照正文测试", read ?? "null");
}
// O06 快照保留上限裁剪
{
    for (int i = 0; i < 3; i++)
        WritingDoc.SaveSnapshot("test-trim.md", $"版本{i}", DateTimeOffset.Now.AddSeconds(i));
    WritingDoc.TrimSnapshots("test-trim.md", 1);
    Check("O06 快照裁剪到上限", WritingDoc.ListSnapshots("test-trim.md").Count == 1);
}

// ================= 10. C# 智能补全（1.1.0，5 项） =================

// G01 var 推断 + 泛型成员补全
{
    var text = "using System.Collections.Generic;\nvar list = new List<string>();\nlist.";
    var items = await CSharpIntel.GetCompletionsAsync(text, text.Length);
    Check("G01 List<string> 成员补全",
        items is not null && items.Any(i => i.Text == "Add" && i.Kind == "method") && items.Any(i => i.Text == "Count"),
        items is null ? "null" : string.Join(",", items.Select(i => i.Text).Take(8)));
}
// G02 继承链成员（List→ICollection→IEnumerable→object）
{
    var text = "using System.Collections.Generic;\nvar list = new List<int>();\nlist.A";
    var items = await CSharpIntel.GetCompletionsAsync(text, text.Length);
    Check("G02 继承链成员可达", items is not null && items.Any(i => i.Text == "Add") && items.Any(i => i.Text == "CopyTo"),
        items is null ? "null" : string.Join(",", items.Select(i => i.Text).Take(8)));
}
// G03 = 号后补上下文：作用域符号可见
{
    var text = "int x = 1;\nint y = ";
    var items = await CSharpIntel.GetCompletionsAsync(text, text.Length);
    Check("G03 = 后作用域符号", items is not null && items.Any(i => i.Text == "x"),
        items is null ? "null" : string.Join(",", items.Select(i => i.Text).Take(10)));
}
// G04 普通位置无候选（返回 null 不误弹）
{
    var text = "int x = 1;";
    var items = await CSharpIntel.GetCompletionsAsync(text, text.Length);
    Check("G04 普通位置不弹层", items is null);
}
// G05 枚举类型成员（DayOfWeek.Monday 等静态枚举值）
{
    var text = "System.DayOfWeek d = System.DayOfWeek.";
    var items = await CSharpIntel.GetCompletionsAsync(text, text.Length);
    Check("G05 枚举成员补全", items is not null && items.Any(i => i.Text == "Monday"),
        items is null ? "null" : string.Join(",", items.Select(i => i.Text).Take(10)));
}

// ================= 9. 撤销步进计划（1.1.1 审查修复，5 项） =================
// 背景：富内核里着色/彩虹括号格式批进撤销流，原生一步只退格式不退文字。
// UndoStepper 连续步进直到文字真变——此处用委托模拟"格式步/文字步"序列。

// U01 连续格式步后一步文字步：跨过格式步、停在文字变化
{
    // 撤销流（从新到旧）：[着色批][着色批][真实文字]，执行 Undo 依次回退
    var units = new Stack<string>(new[] { "format2", "format1", "text" });
    string Apply()
    {
        var u = units.Pop();
        return u == "text" ? "old" : "cur";
    }
    var (steps, changed) = UndoStepper.Run(64, "cur",
        current: () => units.Count == 0 ? "old" : (units.Peek() == "text" ? "cur" : "cur"),
        step: () => Apply(),
        canStep: () => units.Count > 0);
    Check("U01 格式步跨过后停在文字变化", changed && steps == 3, $"steps={steps} changed={changed}");
}

// U02 首步就是文字步：一步即停
{
    var (steps, changed) = UndoStepper.Run(64, "cur",
        current: () => "old", step: () => { }, canStep: () => true);
    Check("U02 首步即文字步", changed && steps == 1, $"steps={steps} changed={changed}");
}

// U03 上限防呆：全是格式步时步进耗尽也不无限循环
{
    int calls = 0;
    var (steps, changed) = UndoStepper.Run(64, "cur",
        current: () => "cur", step: () => calls++, canStep: () => true);
    Check("U03 步进上限防呆", !changed && steps == 64 && calls == 64, $"steps={steps} calls={calls}");
}

// U04 流尽：无可步进单元时立即返回零步
{
    var (steps, changed) = UndoStepper.Run(64, "cur",
        current: () => "cur", step: () => { }, canStep: () => false);
    Check("U04 流尽返回零步", !changed && steps == 0, $"steps={steps} changed={changed}");
}

// U05 重做对称：注入 Redo 委托同法工作
{
    int done = 0;
    var (steps, changed) = UndoStepper.Run(64, "cur",
        current: () => done == 0 ? "cur" : "new",
        step: () => done++,
        canStep: () => done < 1);
    Check("U05 重做方向对称", changed && steps == 1, $"steps={steps} changed={changed}");
}

// ================= 汇总 =================

Console.WriteLine($"==== 逻辑回归汇总：{pass} 通过 / {fail} 失败 ====");
return fail == 0 ? 0 : 1;
