# TaoPad 总体架构设计

## 1. 架构概览

```
┌─────────────────────────────────────────────┐
│ App.xaml / App.xaml.cs                       │  入口、全局异常、崩溃日志
├─────────────────────────────────────────────┤
│ MainWindow                                   │  菜单/标签页/状态栏/查找替换/设置
│   ├─ DocState[]                              │  每文档状态（路径/编码/修改标记）
│   ├─ Tabs 区（TabView）                      │
│   └─ StatusBar                               │
├─────────────────────────────────────────────┤
│ Controls/CodeEditor（核心控件，可复用）       │  双内核编辑 + 补全 + 着色
├─────────────────────────────────────────────┤
│ Services/                                    │  ThemeService / CrashLog
│ Utils/（CompletionEngine, Tokenizer, LangDef,│
│        EncodingDetector, FormatEngine 等）   │  纯逻辑，无 UI 依赖
├─────────────────────────────────────────────┤
│ Installer（WiX 5：Package.wxs + Bundle.wxs） │  MSI + EXE 安装器
└─────────────────────────────────────────────┘
```

分层原则：
- **纯逻辑层**（Utils/）不引用任何 UI 类型，全部可在 Linux 沙箱做逻辑回归测试（logictest 41 项）。
- **UI 层**（Controls/MainWindow）只做适配：把纯逻辑结果绘制到 WinUI 控件，UI 特有 API（ITextDocument 等）集中在 CodeEditor 的"内核适配层"。
- **服务层**（Services/）提供跨窗口单例能力（主题、崩溃日志）。

## 2. 关键设计决策

### D1 双内核编辑器（CodeEditor）
- 决策：编辑区不使用自绘控件，按语言把工作委托给两个系统内核：
  - `_tb`（TextBox）：plain / markdown。稳定、原生输入法行为。
  - `_re`（RichEditBox）：代码语言，可做逐 Token 颜色格式化。
- 理由：自绘编辑器（布局/输入法/选择/无障碍）成本极高；RichEditBox 的 ITextDocument 支持范围格式化，是 WinUI 3 下唯一可行的着色路径。
- 适配层：`RawText`（规范 \n 文本 1:1 对应文档偏移）、`SelPos/SelLen/SelTextRaw/Sel()`、`OutputEol`（保存还原换行）。上层逻辑只面对适配层。

### D2 着色 = 防抖 + 分词 + 幂等
- TextChanged → ScheduleRecolor（220ms 防抖）→ Tokenizer 分词 → 逐 Token 设置 CharacterFormat → ApplyRainbow。
- 幂等基线 `_lastColorText`：文本没变直接跳过，一次格式化都不做——任何时序的伪事件（WinUI 对格式化会触发 TextChanged）都无法形成循环。
- 上限保护：5000 次格式化操作上限；>300KB 跳过彩虹括号。

### D3 智能提示 = 纯引擎 + 薄弹层
- CompletionEngine（纯逻辑）：给定全文/光标/语言 → 候选列表 + 当前前缀。候选 = 关键字 ∪ 全文标识符。
- 弹层（Popup+Border+StackPanel）只负责展示与定位；状态机在 CodeEditor：过滤、指纹复用（`_listKey`）、精确匹配抑制、焦点管理。
- 定位：TextBox 精确（GetRectFromCharacterIndex）；RichEditBox 按等宽字体估算（行列 × 字符宽高），失败兜底左上角。

### D4 主题 = 资源字典 + 广播
- ThemeService 持有三套 MergedDictionaries（水墨/Light/Dark），切换时替换字典并广播 `ThemeApplied`。
- 订阅方：MainWindow（窗口 chrome 配色）、每个 CodeEditor（编辑区配色 + 弹层配色 + 着色基线重置）。

### D5 分发 = 自包含 + 双安装包
- dotnet publish `--self-contained` + `WindowsAppSDKSelfContained=true`：不依赖系统 .NET 与 Windows App Runtime，装完即用。
- MSI（WiX Package）负责文件与注册表；EXE（WiX Bundle）负责运行库内嵌与向导；MajorUpgrade 依赖递增版本号清理旧版。

## 3. 数据流示例（一次按键）

```
按键 'f' → RichEditBox.TextChanged → OnTextChanged
  ├─ _lastRaw 比对：伪事件 → 直接返回（防循环）
  ├─ MaybeShowPopup → CompletionEngine → 弹层更新（指纹复用）
  ├─ ScheduleRecolor（220ms 后）→ Recolor → 幂等检查 → 分词 → 格式化
  ├─ Modified 事件 → 标签 ● 与脏标记
  └─ StatusChanged → 状态栏行/列/字符数
```

## 4. 目录结构

```
AntPad/
├─ build-installer.bat        一键打包（GBK+CRLF）
├─ README.md
├─ docs/                      全套开发文档（本目录）
└─ src/
   ├─ AntPad/                 产品工程
   │  ├─ App.xaml(.cs)        入口/全局异常
   │  ├─ MainWindow.xaml(.cs) 主窗口
   │  ├─ Controls/CodeEditor.cs   双内核编辑控件（核心，~1000 行）
   │  ├─ Services/            ThemeService / CrashLog
   │  ├─ Utils/               CompletionEngine / Tokenizer / LangDef /
   │  │                       EncodingDetector / FormatEngine …
   │  └─ Assets/              图标
   └─ Installer/
      ├─ Package.wxs          MSI 定义（微信风格单页向导）
      └─ Bundle.wxs           EXE 安装器定义
```
