using System;
using System.Buffers.Binary;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace AntPad.Views;

/// <summary>
/// v39.3 超大文件只读快看通道（老板拍板的分治方案）：
/// 编辑器只管 50MB 内可编辑；超限文件不再拒开，改走本窗口——
/// 稀疏行索引（每 1024 行记一个字节偏移）+ 按屏解码渲染（约 500 行），
/// GB 级日志可看、可跳、定位快。编辑仍回编辑器（切片/剪出后改）。
/// 只读：本窗口没有写回路径，不存在与编辑器的一致性问题。
/// </summary>
public sealed class HugeFileViewer : Window
{
    const int IndexStride = 1024;   // 索引粒度：每 1024 行记一个字节偏移
    const int WindowLines = 500;    // 单屏渲染行数

    readonly string _path;
    long _fileLen;
    Encoding _enc = new UTF8Encoding(false);
    int _charStride = 1;            // 换行字节序列长度（UTF-16 为 2）
    bool _utf16Le;
    long[] _lineOffsets = Array.Empty<long>();  // [i] = 第 i*IndexStride 行的字节偏移
    long _totalLines = -1;          // 统计完成前置 -1
    TextBox _view = new();
    Slider _slider = new();
    TextBlock _posText = new();
    TextBlock _infoText = new();
    TextBox _gotoBox = new();
    bool _jumping;                  // 程序跳行期间抑制滑条回灌

    public HugeFileViewer(string path)
    {
        _path = path;
        _name = System.IO.Path.GetFileName(path);
        Title = $"{_name} — TaoPad 快看（只读）";
        BuildUi();
        _ = Task.Run(() => BuildIndexAsync());
    }

    // ================= 界面（代码构建，无 XAML 依赖） =================

    void BuildUi()
    {
        _view.IsReadOnly = true;
        _view.AcceptsReturn = true;
        _view.TextWrapping = Microsoft.UI.Xaml.TextWrapping.NoWrap;
        _view.FontFamily = new FontFamily("Consolas");
        _view.Margin = new Thickness(8);
        _view.PlaceholderText = "加载中…";

        _slider.Minimum = 0;
        _slider.Maximum = 0;
        _slider.StepFrequency = 1;
        _slider.ValueChanged += OnSliderChanged;

        _infoText.Text = _name;
        _posText.Text = "统计行数中…";
        _gotoBox.PlaceholderText = "行号";
        _gotoBox.Width = 90;
        var gotoBtn = new Button { Content = "跳转" };
        gotoBtn.Click += (_, _) => JumpFromBox();

        var bottom = new Grid { ColumnSpacing = 8, Margin = new Thickness(8) };
        bottom.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        bottom.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        bottom.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        bottom.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        bottom.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        _slider.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(_slider, 0);
        Grid.SetColumn(_posText, 1);
        _posText.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(_gotoBox, 2);
        Grid.SetColumn(gotoBtn, 3);
        bottom.Children.Add(_slider);
        bottom.Children.Add(_posText);
        bottom.Children.Add(_gotoBox);
        bottom.Children.Add(gotoBtn);

        var root = new Grid();
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        _infoText.Margin = new Thickness(12, 10, 12, 0);
        Grid.SetRow(_infoText, 0);
        Grid.SetRow(_view, 1);
        Grid.SetRow(bottom, 2);
        root.Children.Add(_infoText);
        root.Children.Add(_view);
        root.Children.Add(bottom);
        Content = root;
    }

    // ================= 稀疏行索引（后台一次性流扫） =================

    async Task BuildIndexAsync()
    {
        try
        {
            var fi = new FileInfo(_path);
            if (!fi.Exists) return;
            _fileLen = fi.Length;

            // 编码探测只看头部：BOM 决定换行字节形态（UTF-16 按 2 字节配对找 0x0A）
            using (var fs = new FileStream(_path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                Span<byte> head = stackalloc byte[2];
                int got = 0;
                while (got < 2)
                {
                    int r = fs.Read(head[got..]);
                    if (r <= 0) break;
                    got += r;
                }
                if (got == 2 && head[0] == 0xFF && head[1] == 0xFE)
                {
                    _enc = new UnicodeEncoding(bigEndian: false, byteOrderMark: false);
                    _utf16Le = true; _charStride = 2;
                }
                else if (got == 2 && head[0] == 0xFE && head[1] == 0xFF)
                {
                    _enc = new UnicodeEncoding(bigEndian: true, byteOrderMark: false);
                    _utf16Le = false; _charStride = 2;
                }
            }

            var offsets = new System.Collections.Generic.List<long>(1 << 12) { 0 };
            long lineNo = 0;
            using var fs2 = new FileStream(_path, FileMode.Open, FileAccess.Read, FileShare.Read);
            var buf = new byte[1 << 20];
            long globalPos = 0;
            int n;
            while ((n = fs2.Read(buf, 0, buf.Length)) > 0)
            {
                int i = 0;
                if (_charStride == 1)
                {
                    while (i < n)
                    {
                        if (buf[i] == 0x0A)
                        {
                            lineNo++;
                            long next = globalPos + i + 1;
                            if (lineNo % IndexStride == 0) offsets.Add(next);
                        }
                        i++;
                    }
                }
                else
                {
                    while (i + 1 < n)
                    {
                        bool nl = _utf16Le
                            ? buf[i] == 0x0A && buf[i + 1] == 0x00
                            : buf[i] == 0x00 && buf[i + 1] == 0x0A;
                        if (nl)
                        {
                            lineNo++;
                            long next = globalPos + i + 2;
                            if (lineNo % IndexStride == 0) offsets.Add(next);
                        }
                        i += 2;
                    }
                }
                globalPos += n;
            }
            _lineOffsets = offsets.ToArray();
            _totalLines = lineNo + (lineNo > 0 && !EndsWithNewline() ? 1 : 0);
            if (_totalLines == 0 && _fileLen > 0) _totalLines = 1;

            DispatcherQueue.TryEnqueue(() =>
            {
                _slider.Maximum = Math.Max(0, _totalLines - WindowLines);
                _posText.Text = $"共 {_totalLines} 行";
                _ = ShowWindowAsync(0);
            });
        }
        catch (Exception ex)
        {
            DispatcherQueue.TryEnqueue(() => { _view.Text = $"快看打开失败：{ex.Message}"; _posText.Text = ""; });
        }
    }

    bool EndsWithNewline()
    {
        try
        {
            using var fs = new FileStream(_path, FileMode.Open, FileAccess.Read, FileShare.Read);
            int stride = Math.Max(1, _charStride);
            if (_fileLen < stride) return _fileLen > 0;
            fs.Seek(_fileLen - stride, SeekOrigin.Begin);
            int b1 = fs.ReadByte(); int b2 = fs.ReadByte();
            if (stride == 1) return b1 == 0x0A;
            return _utf16Le ? (b2 == 0x0A && b1 == 0x00) : (b1 == 0x00 && b2 == 0x0A);
        }
        catch { return false; }
    }

    // ================= 按屏解码渲染 =================

    /// <summary>取 [firstLine, firstLine+WindowLines) 一屏解码显示；秒级，不建整篇字符串。</summary>
    async Task ShowWindowAsync(long firstLine)
    {
        try
        {
            if (_totalLines < 0) return;
            long clamped = Math.Max(0, Math.Min(firstLine, Math.Max(0, _totalLines - 1)));
            long baseOff = _lineOffsets[clamped / IndexStride];
            var sb = new StringBuilder(64 << 10);
            using var fs = new FileStream(_path, FileMode.Open, FileAccess.Read, FileShare.Read);
            fs.Seek(baseOff, SeekOrigin.Begin);
            using var sr = new StreamReader(fs, _enc, detectEncodingFromByteOrderMarks: false, 1 << 16);
            int skip = (int)(clamped % IndexStride);
            for (int i = 0; i < skip; i++) if (sr.ReadLine() is null) break;
            int shown = 0;
            while (shown < WindowLines)
            {
                var line = await sr.ReadLineAsync();
                if (line is null) break;
                if (shown > 0) sb.Append('\n');
                sb.Append(line);
                shown++;
            }
            string text = sb.ToString();
            DispatcherQueue.TryEnqueue(() =>
            {
                _jumping = true;
                _view.Text = text;
                _jumping = false;
            });
        }
        catch (Exception ex)
        {
            DispatcherQueue.TryEnqueue(() => _view.Text = $"读取失败：{ex.Message}");
        }
    }

    async void OnSliderChanged(object sender, Microsoft.UI.Xaml.Controls.Primitives.RangeBaseValueChangedEventArgs e)
    {
        if (_jumping || _totalLines < 0) return;
        await ShowWindowAsync((long)_slider.Value);
        DispatcherQueue.TryEnqueue(() =>
            _posText.Text = $"第 {(long)_slider.Value + 1} 行 / 共 {_totalLines} 行");
    }

    async void JumpFromBox()
    {
        if (!long.TryParse(_gotoBox.Text.Trim(), out long lineNo)) return;
        long target = Math.Max(0, Math.Min(lineNo - 1, Math.Max(0, _totalLines - 1)));
        _jumping = true;
        _slider.Value = Math.Max(_slider.Minimum, Math.Min(_slider.Maximum, target));
        _jumping = false;
        _posText.Text = $"第 {target + 1} 行 / 共 {_totalLines} 行";
        await ShowWindowAsync(target);
    }
}
