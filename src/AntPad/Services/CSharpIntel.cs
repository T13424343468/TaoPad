using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace AntPad.Services;

/// <summary>
/// C# 全量语法智能补全（1.1.0 拍板：补全能力对齐 VS）。
/// 引 Roslyn（VS 同源分析引擎，微软开源）做语义级补全：
/// - 成员访问：x. 之后按 x 的类型列出成员（var 推断、泛型、继承链都吃）；
/// - 表达式上下文（= 与括号/逗号后）：列出作用域内可见的局部变量、字段、类型。
/// 引擎懒加载：只在打开 C# 文件并触发补全时初始化，其他语言零开销。
/// 失败一律返回空表，不影响编辑（补全是增益，不是依赖）。
/// </summary>
public static class CSharpIntel
{
    public sealed record IntelItem(string Text, string Kind);

    // 引用程序集只探一次（进程内不变）
    static IReadOnlyList<MetadataReference>? _refs;
    static readonly object Gate = new();

    /// <summary>把本进程已加载的运行时程序集当引用面（自包含应用自带全套运行库）。</summary>
    static IReadOnlyList<MetadataReference> References()
    {
        lock (Gate)
        {
            if (_refs is not null) return _refs;
            var list = new List<MetadataReference>();
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    if (asm.IsDynamic) continue;
                    string loc = asm.Location;
                    if (loc.Length == 0 || !File.Exists(loc)) continue;
                    list.Add(MetadataReference.CreateFromFile(loc));
                }
                catch { /* 单件读不到不挡其余 */ }
            }
            _refs = list;
            return _refs;
        }
    }

    static (SyntaxTree Tree, CSharpCompilation Comp) Build(string text)
    {
        var tree = CSharpSyntaxTree.ParseText(text, new CSharpParseOptions(LanguageVersion.Latest));
        var comp = CSharpCompilation.Create("antpad-intel", [tree], References());
        return (tree, comp);
    }

    /// <summary>光标处的补全候选；无补全上下文返回空表。
    /// 永不抛出：分析失败当无候选处理。</summary>
    public static async Task<List<IntelItem>?> GetCompletionsAsync(string text, int caret)
    {
        try
        {
            var r = await Task.Run(() => GetCompletions(text, caret)).ConfigureAwait(false);
            LastError = null;
            return r;
        }
        catch (Exception ex) { LastError = $"{ex.GetType().Name}: {ex.Message}"; return null; }
    }

    /// <summary>最近一次语义分析失败的自报（仅测试诊断用；成功或未跑为 null）。</summary>
    public static string? LastError { get; private set; }

    static List<IntelItem>? GetCompletions(string text, int caret)
    {
        if (string.IsNullOrEmpty(text) || caret <= 0 || caret > text.Length) return null;
        var (tree, comp) = Build(text);
        var root = tree.GetRoot();
        var model = comp.GetSemanticModel(tree);

        // 成员访问：光标前是"."（或点后已敲了几个字母）→ 按目标表达式类型列成员
        if (TryMemberAccess(root, caret, out var expr))
        {
            var t = model.GetTypeInfo(expr).Type;
            if (t is null) return [];
            return MembersOf(t).Select(i => new IntelItem(i.Text, i.Kind)).ToList();
        }

        // 表达式上下文：= / ( / , 之后 → 作用域内可见符号（局部变量、字段、类型）
        if (InExpressionContext(text, caret))
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            var result = new List<IntelItem>();
            // 位置口径（LogicTests G03 探针定谳）：LookupSymbols 落在文末
            // （EOF 位置）会丢作用域内的局部变量；光标语义是「下一个字符的
            // 索引」，实际查询点取光标前一个字符所在处，与成员访问一致。
            foreach (var sym in model.LookupSymbols(Math.Min(caret - 1, root.Span.End - 1)))
            {
                if (!seen.Add(sym.Name) || sym.Name.Length == 0) continue;
                result.Add(new(sym.Name, KindOf(sym)));
            }
            return result;
        }
        return null;
    }

    /// <summary>光标前是否成员访问：找到紧邻的"."所属的成员访问节点，返回其目标表达式。
    /// 点后已敲字母时 FindToken 落在标识符上，沿语法树向上仍命中同一节点。</summary>
    static bool TryMemberAccess(SyntaxNode root, int caret, out ExpressionSyntax expr)
    {
        expr = null!;
        var token = root.FindToken(Math.Min(caret - 1, root.Span.End - 1));
        for (SyntaxNode? node = token.Parent; node is not null; node = node.Parent)
        {
            if (node is MemberAccessExpressionSyntax ma && ma.OperatorToken.Text == ".")
            {
                expr = ma.Expression;
                return true;
            }
            if (node is StatementSyntax) break;
        }
        return false;
    }

    /// <summary>类型及其继承链的全部实例成员（去重），枚举取静态成员。</summary>
    static IEnumerable<IntelItem> MembersOf(ITypeSymbol type)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        ITypeSymbol? t = type;
        // 沿继承链收成员：GetMembers() 只含本类型声明的，逐层向上
        while (t is not null)
        {
            foreach (var m in t.GetMembers())
            {
                if (m is IMethodSymbol { MethodKind: MethodKind.Constructor or MethodKind.StaticConstructor }) continue;
                if (m.DeclaredAccessibility is not (Accessibility.Public or Accessibility.Protected or Accessibility.ProtectedOrInternal)) continue;
                if (m.IsStatic && SymbolEqualityComparer.Default.Equals(t, type) && type.TypeKind is not TypeKind.Enum) continue;   // RS1024：符号比较用 SymbolEqualityComparer
                if (!seen.Add(m.Name)) continue;
                yield return new(m.Name, KindOf(m));
            }
            t = t.BaseType;
        }
    }

    static string KindOf(ISymbol sym) => sym switch
    {
        IMethodSymbol => "method",
        IPropertySymbol => "property",
        IFieldSymbol => "field",
        IEventSymbol => "event",
        INamedTypeSymbol => "type",
        _ => "other",
    };

    /// <summary>表达式上下文判定：从光标往回找，先遇到 = ( 或半角逗号、且中途没撞上语句边界。</summary>
    static bool InExpressionContext(string text, int caret)
    {
        for (int i = caret - 1; i >= 0; i--)
        {
            char c = text[i];
            if (char.IsWhiteSpace(c)) continue;
            if (c == '=' || c == '(' || c == ',') return true;
            if (c == ';' || c == '{' || c == '}') return false;
            return false;
        }
        return false;
    }
}
