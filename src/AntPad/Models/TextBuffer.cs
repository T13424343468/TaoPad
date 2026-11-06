using System.Text;

namespace AntPad.Models;

/// <summary>
/// 文本缓冲区：按行存储，支持增量编辑与撤销/重做（记录差量变更）。
/// 换行符统一规范化为 \n。
/// </summary>
public sealed class TextBuffer
{
    public struct Change { public int Pos; public string Removed; public string Inserted; }

    readonly List<string> _lines = new() { "" };
    readonly Stack<Change> _undo = new();
    readonly Stack<Change> _redo = new();
    int _len; // 不含换行符

    public event Action? Changed;

    public int LineCount => _lines.Count;
    public string Line(int i) => _lines[i];
    public int Length => _len;
    public bool CanUndo => _undo.Count > 0;
    public bool CanRedo => _redo.Count > 0;

    public string Text
    {
        get
        {
            var sb = new StringBuilder(_len + _lines.Count);
            for (int i = 0; i < _lines.Count; i++)
            {
                if (i > 0) sb.Append('\n');
                sb.Append(_lines[i]);
            }
            return sb.ToString();
        }
    }

    public void SetText(string text)
    {
        _lines.Clear();
        int eols = 0;
        int start = 0;
        for (int i = 0; i < text.Length; i++)
        {
            if (text[i] == '\r')
            {
                _lines.Add(text[start..i]);
                if (i + 1 < text.Length && text[i + 1] == '\n') i++;
                start = i + 1;
                eols++;
            }
            else if (text[i] == '\n')
            {
                _lines.Add(text[start..i]);
                start = i + 1;
                eols++;
            }
        }
        _lines.Add(text[start..]);
        _len = text.Length - eols;
        _undo.Clear();
        _redo.Clear();
        Changed?.Invoke();
    }

    public void PosToLineCol(int pos, out int line, out int col)
    {
        // 位置总数按含换行符计算：_len 不含换行，行数-1 个换行需补回
        pos = Math.Clamp(pos, 0, _len + _lines.Count - 1);
        int acc = 0;
        for (int i = 0; i < _lines.Count; i++)
        {
            int l = _lines[i].Length;
            if (pos <= acc + l) { line = i; col = pos - acc; return; }
            acc += l + 1;
        }
        line = _lines.Count - 1;
        col = _lines[^1].Length;
    }

    public int LineColToPos(int line, int col)
    {
        line = Math.Clamp(line, 0, _lines.Count - 1);
        int acc = 0;
        for (int i = 0; i < line; i++) acc += _lines[i].Length + 1;
        return acc + Math.Clamp(col, 0, _lines[line].Length);
    }

    public string GetRange(int pos, int count)
    {
        if (count <= 0) return "";
        PosToLineCol(pos, out int l, out int c);
        var sb = new StringBuilder(count);
        int remaining = count;
        for (int i = l; i < _lines.Count && remaining > 0; i++)
        {
            string ln = _lines[i];
            if (c < ln.Length)
            {
                int take = Math.Min(remaining, ln.Length - c);
                sb.Append(ln, c, take);
                remaining -= take;
            }
            if (remaining > 0 && i < _lines.Count - 1)
            {
                sb.Append('\n');
                remaining--;
            }
            c = 0;
        }
        return sb.ToString();
    }

    public void Insert(int pos, string text)
    {
        if (text.Length == 0) return;
        PushUndo(new Change { Pos = pos, Removed = "", Inserted = text }, coalesce: true);
        InsertRaw(pos, text);
        _redo.Clear();
        Changed?.Invoke();
    }

    public void Remove(int pos, int count)
    {
        if (count <= 0) return;
        string rem = GetRange(pos, count);
        PushUndo(new Change { Pos = pos, Removed = rem, Inserted = "" }, coalesce: false);
        DeleteRaw(pos, count);
        _redo.Clear();
        Changed?.Invoke();
    }

    public void Replace(int pos, int count, string text)
    {
        string rem = count > 0 ? GetRange(pos, count) : "";
        PushUndo(new Change { Pos = pos, Removed = rem, Inserted = text }, coalesce: false);
        if (count > 0) DeleteRaw(pos, count);
        if (text.Length > 0) InsertRaw(pos, text);
        _redo.Clear();
        Changed?.Invoke();
    }

    public bool Undo()
    {
        if (_undo.Count == 0) return false;
        var ch = _undo.Pop();
        if (ch.Inserted.Length > 0) DeleteRaw(ch.Pos, ch.Inserted.Length);
        if (ch.Removed.Length > 0) InsertRaw(ch.Pos, ch.Removed);
        _redo.Push(ch);
        Changed?.Invoke();
        return true;
    }

    public bool Redo()
    {
        if (_redo.Count == 0) return false;
        var ch = _redo.Pop();
        if (ch.Removed.Length > 0) DeleteRaw(ch.Pos, ch.Removed.Length);
        if (ch.Inserted.Length > 0) InsertRaw(ch.Pos, ch.Inserted);
        _undo.Push(ch);
        Changed?.Invoke();
        return true;
    }

    void PushUndo(Change ch, bool coalesce)
    {
        if (coalesce && _undo.Count > 0)
        {
            var top = _undo.Peek();
            if (top.Removed.Length == 0 && ch.Inserted.Length == 1 &&
                top.Pos + top.Inserted.Length == ch.Pos &&
                top.Inserted[^1] != '\n' && top.Inserted[^1] != '\r' &&
                ch.Inserted[0] != '\n' && ch.Inserted[0] != '\r')
            {
                _undo.Pop();
                top.Inserted += ch.Inserted;
                _undo.Push(top);
                return;
            }
        }
        _undo.Push(ch);
        if (_undo.Count > 400)
        {
            var arr = _undo.ToArray(); // arr[0] 最新，arr[^1] 最旧
            _undo.Clear();
            for (int i = arr.Length - 2; i >= 0; i--) _undo.Push(arr[i]);
        }
    }

    void DeleteRaw(int pos, int count)
    {
        PosToLineCol(pos, out int sl, out int sc);
        PosToLineCol(pos + count, out int el, out int ec);
        string head = _lines[sl][..sc];
        string tail = _lines[el][Math.Min(ec, _lines[el].Length)..];
        _len -= count;
        _lines[sl] = head + tail;
        if (el > sl) _lines.RemoveRange(sl + 1, el - sl);
    }

    void InsertRaw(int pos, string text)
    {
        PosToLineCol(pos, out int l, out int c);
        string cur = _lines[l];
        string head = cur[..c], tail = cur[c..];
        var parts = SplitLines(text);

        if (parts.Count == 1)
        {
            _lines[l] = head + parts[0] + tail;
            _len += parts[0].Length;
        }
        else
        {
            _lines[l] = head + parts[0];
            var middle = new string[parts.Count - 1];
            for (int i = 1; i < parts.Count; i++) middle[i - 1] = parts[i];
            _lines.InsertRange(l + 1, middle);
            _lines[l + parts.Count - 1] += tail;
            _len += text.Length - (parts.Count - 1);
        }
    }

    static List<string> SplitLines(string s)
    {
        var r = new List<string>();
        int start = 0;
        for (int i = 0; i < s.Length; i++)
        {
            if (s[i] == '\r')
            {
                r.Add(s[start..i]);
                if (i + 1 < s.Length && s[i + 1] == '\n') i++;
                start = i + 1;
            }
            else if (s[i] == '\n')
            {
                r.Add(s[start..i]);
                start = i + 1;
            }
        }
        r.Add(s[start..]);
        return r;
    }
}
