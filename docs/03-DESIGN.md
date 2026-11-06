# TaoPad 模块详细设计

## 1. CodeEditor（Controls/CodeEditor.cs，核心）

### 1.1 双内核适配层
| 成员 | TextBox 内核 | RichEditBox 内核 |
|---|---|---|
| RawText | Text 属性归一 \r\n→\n | GetText(None)→归一（偏移 1:1） |
| SelPos/SelLen | SelectionStart/Length | Document.Selection.Start/End |
| SelTextRaw | SelectedText | Selection.Text（自动格式还原） |
| Sel(s,len) | Select | SetRange |
| 着色 | 无（纯文本不支持） | Recolor 逐 Token 格式化 |

- 内核选择：`UseRich(lang)` — plain/markdown 用 TextBox，其余 RichEditBox；`SwitchCore` 保留文本与光标位置迁移。
- 整体写入（RawText setter）：BeginUndoGroup/EndUndoGroup 包裹，保证 Ctrl+Z 一步撤销；写入后清 `_lastColorText`（格式已随 SetText 清空，必须重着色）。

### 1.2 着色管线
1. `ScheduleRecolor()`：DispatcherQueueTimer 220ms 防抖，重复触发重置计时。
2. `Recolor()`：`_syncing` 屏蔽（同步伪事件）→ 幂等检查（`_lastColorText`）→ 全文分词 →
   逐 Token `GetRange(i,len).CharacterFormat.ForegroundColor`（5000 次上限）→ `ApplyRainbow` 嵌套四色（朱红/琥珀/苔绿/黛蓝）。
3. Token→资源键映射：Ant.TokKeyword/Control/String/Comment/Number/Type/Preproc/Tag/Attr/Heading；缺失资源用保底色。

### 1.3 智能提示状态机
- 触发：TextChanged（真编辑）→ MaybeShowPopup。
- 过滤链：plain 不弹 → 引擎候选 → 弹层已开时前缀退化过滤 → 空集/超 200 收起 → **唯一候选==当前词收起（不弹）** → ShowPopup。
- 弹层复用：`_listKey` 指纹（前缀+前 12 项），内容不变只更新定位；`_popup.IsOpen` 时不动焦点。
- 定位：内层 try（TextBox 精确）→ 外层 try（估算）→ 最终兜底 (24,24)；开弹层动作保证执行。
- 键盘：Down/Up/PageDown/PageUp 选择、Enter/Tab 接受、Esc 关闭；弹层未开时 Tab=缩进。

### 1.4 事件流
- TextChanged 真编辑：`_lastRaw` 更新 → MaybeShowPopup → ScheduleRecolor → Modified/StatusChanged。
- 主题应用 OnThemeApplied：重读 Ant.EdText/Ant.EdBg/Ant.Surface/Ant.Border → 更新两内核与弹层配色 → HidePopup 复位 → 清着色基线重刷。
- 崩溃兜底：CodeEditor 所有 UI 适配点 try/catch + 注释说明。

## 2. Tokenizer（Utils）
- 手写扫描器：标识符、数字（含十六进制/后缀）、字符串（含转义）、逐行/块注释、预处理行、XML 标签/属性、Markdown 标题。
- 语义增强：紧邻 '.' 的标识符 → Member；大写开头标识符 → Type。
- 纯函数无状态，全部被 logictest 覆盖。

## 3. CompletionEngine（Utils）
- 输入：全文、光标偏移、语言定义；输出：候选列表 + 当前前缀。
- 候选源：语言关键字 + 全文标识符扫描（正则一次扫描，去重排序）；前缀 <2 不触发。
- 过滤：StartsWith(前缀, Ordinal)；同词抑制在 CodeEditor 层做（引擎保持纯粹）。

## 4. FormatEngine（Utils）
- 缩进归一：统一 4 空格；花括号语言做 K&R 换行与缩进层级；XML 做标签缩进。
- Ctrl+K,Ctrl+D 全文 / Ctrl+K,Ctrl+F 选区；两段式快捷键 2 秒超时。

## 5. EncodingDetector（Utils）
- BOM 优先（UTF-8/UTF-16LE/BE）；无 BOM 做字节统计启发（ASCII→UTF-8 校验→GB 系）。
- 读写对称：检测结果保存在 DocState，保存时用同一编码。

## 6. ThemeService（Services）
- 三套资源字典（Ant 水墨默认 / Ant.Light / Ant.Dark）；`Apply(theme)` 替换 MergedDictionaries 后广播 `ThemeApplied`。
- 失败回退 Ant.Light（v37 增强），杜绝切换失败黑屏。

## 7. CrashLog（Services）
- App.xaml.cs 全局 `UnhandledException` + `OnLaunched` try/catch。
- 写 `%LOCALAPPDATA%\TaoPad\crash.log`（时间+类型+堆栈），并 user32 MessageBoxW 弹窗（托管弹窗可能不可用时的原生兜底）。

## 8. Installer（src/Installer）
- Package.wxs：perMachine，Codepage 936，微信风格单页 UI（协议勾选/目录/文件关联），MajorUpgrade（依赖递增版本），UpgradeCode `D5A3F0C2-…` 恒定。
- Bundle.wxs：内嵌运行库（自包含发布产物 + Windows App SDK 自带），无网安装。
- 产物：`TaoPad-1.7.0-x64.msi` / `TaoPad-1.7.0-x64.exe`。

## 9. 已知限制
- RichEditBox 光标定位为等宽估算（一般语言下误差 ≤1 字符宽度）。
- 彩虹括号 5000 次上限，超大嵌套文档只着色前 5000 个括号。
- 智能提示不含语义分析（无类型推断/成员解析），属词法级补全。
