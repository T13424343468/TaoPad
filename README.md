# TaoPad — WinUI 3 文本编辑器

**正式版 1.0.9（2026-11-06，定版 1.0 线迭代）**

> 1.0.9 更新（真机修复）：行号栏/小地图底色改走专属键 Ant.GutterBg
> （三象齐备、纯色、不经陶瓷渐变换装）；代码取色放宽到 GradientBrush 基类并
> 直连当前主题字典兜底——修复 Ant.Surface 被陶瓷渐变换装后真机读取失灵、
> 墨夜下行号栏/小地图停首主题白（保底色 248,249,250）的残留。

> 1.0.8 更新（真机修复）：换肤链路加固——主题字典交换摘除 App.xaml 静态合并的
> 水墨字典（链上只留一份主题字典），主题直涂与编辑器换肤回调逐面隔离（单环
> 异常不再拖垮后续大面，失败面记入崩溃日志可追溯）；修复真机"正文换墨夜、
> 行号栏/小地图/状态栏停首主题白"的残留。
> 1.0.7 更新（真机修复）：陶瓷渐变作用域收进当前主题字典——修复切换主题后
> 卡片/编辑区/状态栏停留首主题色、"墨夜换不回来"的换肤缺陷。
> 1.0.6 更新（全系 PC 天青统一）：「天灰」主题整档换装「天青」——天青釉底、
> 墨青文字、青瓷点缀；卡片/输入面引入陶瓷质感（竖向微渐变，三主题统一生效）。
> 1.0.5 真机反馈四修（主题残留根治 / 查找替换 VS 化 / 取消注释快捷键 / 快捷键
> 补齐）与更早版本说明见 README.txt 与更新日志。

AntPad 是一个用 .NET 8 + WinUI 3 编写的 Notepad++ 风格多标签文本/代码编辑器，
界面采用水墨美学配色，内置**水墨 / 天青 / 墨夜**三套主题（默认水墨），
道生三象，只此三套；全系 Tao 系列产品统一按此三套实现。

## 功能清单

- 多标签编辑，标签未保存标记 ●，可拖放文件到窗口打开，最近文件列表
- 自绘代码编辑器控件（Win2D 渲染，只绘制可见行，大文件流畅）
  - 行号、当前行高亮、鼠标/双击选词、Shift 选区
  - 语法着色：C/C++/C#/Java/JS/TS/Go/Rust（共用 C 系）、Python、JSON、XML/HTML、Markdown、SQL
  - 撤销/重做（差量记录，保留最近 400 步）
  - 自动换行（字符折行）、Ctrl+滚轮缩放（25%–500%）
- 查找 / 替换：字面量与正则、大小写、全字匹配、查找下一个/上一个（F3/Shift+F3）、
  全部替换、匹配高亮计数
- 转到行（Ctrl+G）
- 行操作：删除当前行、复制当前行、上移/下移当前行
- 大小写转换、插入时间日期（F5）
- 编码：自动识别 UTF-8（含 BOM 探测）/ UTF-16 / GBK 回退；保存编码可切换
  UTF-8、UTF-8 BOM、UTF-16 LE、GBK、Big5
- 换行符：识别并按 CRLF / LF / CR 显示与转换
- 主题：水墨（默认）/ 天青 / 墨夜，三象轮转
- 滚动条：VSCode 风格右侧滚动条，细条常显、悬停加宽、可拖可点（点轨道翻一屏），颜色随三套主题

## 已知限制（Notepad++ 中未实现的部分）

- 列（矩形）选区、宏录制、插件体系、会话快照恢复未实现
- 输入法组合窗口（中文输入预编辑）依赖系统 CharacterReceived，极少数情况下
  组合输入行为可能与常规编辑器略有差异
- 多文档分屏未实现；书签按行号记录，书签上方增删行后位置会漂移
- 多光标以列块高亮 + 块编辑引擎务实形态交付（WinUI 内核暂不支持多插入点）；
  文件监视、导出可打印 HTML、大文件只读、小地图、设置页已实现
- 真实着色 PDF 导出、原生多光标、LSP、插件体系规划于 v2.0

## 构建与运行

需要 Windows 10 1809+（建议 Win11）与 .NET 8 SDK（含 Windows 平台支持）。
Visual Studio 2022 打开 `AntPad.sln` 直接 F5；或命令行：

```bash
dotnet build AntPad.sln -c Release -p:Platform=x64
```

输出为免安装（unpackaged）程序，可直接运行：

```
src\AntPad\bin\x64\Release\net8.0-windows10.0.19041.0\win-x64\AntPad.exe
```

> 说明：WinUI 3 / Windows App SDK 仅能在 Windows 上编译运行，无法在 Linux/macOS 沙箱内验证，首次构建请在 Windows 环境执行。

### 质量验证状态（1.0.9 定版口径）

- 全部 C# 源码已通过真实 Roslyn 编译器编译检查（引用 WindowsAppSDK 1.5 与
  Win2D 1.2 的真实程序集，**0 错误 0 警告**）。
- 全量测试 口径见更新日志（万链归账 84.8 万断言零违规、5000 链模拟真人、
  亮度阶梯、主题消费直涂、滚动条几何万链等关键维度逐项绿）。
- 视觉观测：全样式面 + 真人操作留影 + 三主题直涂/滚动条核对样张，逐帧亲验通过。

## 安装包（MSI）

**双击根目录 `build.bat`** 一键完成（第 1 步源码自检：BOM/命名铁律，
违者中止）。产物固定为 out 文件夹仅 1 项：`TaoPad-1.0.9-x64.msi`
（微信风格单页安装器：许可勾选 + 安装目录可改，默认
`D:\Program Files\TaoPad` + 快捷方式/右键菜单/文件关联可勾选）。
打包脚本见 `tools/msi/package.ps1`；详细步骤见
**[PACKAGING_GUIDE.md](PACKAGING_GUIDE.md)**（历史存档）。

### 发布信息

- 版本：1.0.5（正式版，定版 1.0 线迭代，2026-11-03）
- 运行环境：Windows 10 1809+（建议 Win11），.NET 8 运行时自包含
- 数据存储：默认 `D:\TaoPadData\TaoPad`（D 盘不可用自动回退
  `%LOCALAPPDATA%\TaoPad`，首启自动迁移旧数据）
- 程序集：Product=TaoPad，Company=Tao，Copyright (c) 2026
- 许可：免费使用，个人与商业均可（安装器内含许可条款）

## 工程结构

```
src/AntPad/
├─ App.xaml(.cs)              应用入口，注册代码页编码
├─ MainWindow.xaml(.cs)       主窗口：菜单栏、标签页、状态栏、文档管理
├─ Controls/CodeEditor.cs     自绘代码编辑器控件（核心）
├─ Models/TextBuffer.cs       文本缓冲区（行存储、增量撤销/重做）
├─ Syntax/Tokenizer.cs        语言定义与词法着色
├─ Services/SearchEngine.cs   查找/替换引擎（字面量+正则）
├─ Services/EncodingHelper.cs 编码探测与选项
├─ Services/ThemeService.cs   主题服务（三象轮转：水墨/天青/墨夜）
├─ Services/ThemeRule.cs      主题决策纯函数与三套语法定色板
├─ Views/FindReplacePanel.xaml(.cs)  查找替换浮层
├─ Themes/Ant.*.xaml           主题三象字典（水墨/天青/墨夜）
（安装包工程已移至 tools/msi/ 打包脚本，与 TaoZip 同款）
```

## 快捷键

| 操作 | 快捷键 |
|---|---|
| 新建/打开/保存/另存为 | Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S |
| 关闭标签 / 退出 | Ctrl+W / Alt+F4 |
| 撤销/重做 | Ctrl+Z / Ctrl+Y |
| 剪切/复制/粘贴/全选 | Ctrl+X / Ctrl+C / Ctrl+V / Ctrl+A |
| 查找/替换/转到行 | Ctrl+F / Ctrl+H / Ctrl+G |
| 在文件中查找 | Ctrl+Shift+F |
| 查找下一个/上一个 | F3 / Shift+F3（查找框内 Alt+Enter 向上） |
| 书签：打/取消、下一个、上一个 | Ctrl+F2 / F2 / Shift+F2 |
| 跳到配对括号 | Ctrl+\\ |
| 行操作：复制行、上/下移行 | Ctrl+D / Alt+↑ / Alt+↓ |
| 缩进与反缩进 | Tab / Shift+Tab（缩写命中时 Tab 展开代码片段） |
| 缩放 | Ctrl+滚轮 或 Ctrl+加/减/0 |
| 插入时间日期 | F5 |

## 开发文档（docs/ 目录）

| 文档 | 内容 |
|---|---|
| 01-REQUIREMENTS | 功能需求、非功能需求、约束 |
| 02-ARCHITECTURE | 分层、关键决策、数据流、目录结构 |
| 03-DESIGN | CodeEditor/Tokenizer/补全/主题/安装器等逐模块 |
| 04-BUILD_RELEASE | 环境要求、一键打包、版本发布规则、常见问题 |
| 05-TEST_REPORT | 沙箱验证结果、链路自检清单、真机验收建议 |
| 06-USER_MANUAL | 安装、快捷键、常见操作、故障排查 |
| 07-CHANGELOG | 各版本变更记录 |
| 08-ROADMAP | 优化项、新增批次路线、明确排除项 |
| TAO_PRINCIPLES | 以道家思想为核心的工程总纲：八条原则与代码机制的映射、改造守则 |
