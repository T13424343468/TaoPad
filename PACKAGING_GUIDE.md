# AntPad 打包指南（Windows 侧操作）

> **v24 起本指南的打包部分仅作历史存档**：构建体系已对齐 TaoZip，打包命令以源码根目录 `build.bat` 与 `tools/msi/package.ps1` 为准（双击 build.bat 一键完成）。


> 本指南覆盖：VS 调试运行、发布独立 exe、用 WiX 生成可勾选关联格式的 MSI 安装包、
> 可选的代码签名，以及装包后的手工测试清单。
> WinUI 3 仅能在 Windows 上编译运行，以下步骤请全部在 Windows 10 1809+ / Win11 上执行。

## 一、环境准备

| 依赖 | 说明 |
|---|---|
| Visual Studio 2022 17.8+ | 勾选「.NET 桌面开发」与「Windows 应用程序开发」（WinUI 工作负载） |
| .NET 8 SDK | 8.0.400+，安装后 `dotnet --version` 应为 8.x |
| WiX Toolset 5 | 仅打 MSI 时需要：`dotnet tool install --global wix`，再 `wix extension add -g WixToolset.UI.wixext` |

## 二、VS 内开发调试

1. 用 VS 2022 打开 `AntPad.sln`（内含 `AntPad` 主工程与 `AntPad.Installer` 打包工程）。
2. 平台选 `x64`，配置选 `Debug`，把 `AntPad` 设为启动项目，按 **F5**。
3. 日常调试改 `AntPad` 工程即可；`AntPad.Installer` 只在出安装包时构建。

命令行等价操作：

```bash
dotnet build src/AntPad/AntPad.csproj -c Debug -p:Platform=x64
```

## 三、发布独立可执行目录（免安装版）

```bash
dotnet publish src/AntPad/AntPad.csproj -c Release -p:Platform=x64 ^
  -r win-x64 --self-contained true ^
  -p:WindowsAppSDKSelfContained=true -p:EmbedAssembliesIntoApk=false ^
  -o out/publish-x64
```

- 产物在 `out/publish-x64`，整目录拷贝到目标机即可运行（无需装 .NET 运行时）。
- `WindowsAppSDKSelfContained=true` 会把 Windows App SDK 运行时一并带上，
  目标机无需单独安装 WinAppSDK。
- ARM64 机器把 `-r win-x64 -p:Platform=x64` 换成 `-r win-arm64 -p:Platform=ARM64`。

免安装版直接双击 `AntPad.exe` 即可使用。

## 四、生成安装包（MSI + EXE，支持勾选关联格式）

安装包基于 WiX 5（`src/Installer/`），界面为功能树（WixUI_FeatureTree）：

- **AntPad 主程序**（必装）：编辑器 + 运行时文件 + AntPad 文档类型注册
- **可选关联**：`.txt` / `.md` / `.json` / `.xml` / `.html` / `.cs` / `.cpp+.h` / `.py` / `.sql`
  —— 装机时逐项勾选，勾选的格式注册为「AntPad 文档」默认打开方式，同时写入
  `OpenWithProgids` 备用（卸载时自动恢复原关联）。

### 方式 A：一键脚本（推荐）

双击仓库根目录的 **`build-installer.bat`**，等它跑完即可。产物在 `out\` 文件夹（共两项）：

- `exe\` —— 绿色版文件夹（内含 TaoPad.exe 与全部运行文件，双击直接运行）
- `TaoPad-1.9.1-x64.msi` —— MSI 安装包（可用于组策略批量分发）

脚本会自动完成：首次安装 WiX 工具 → 发布主程序 → 生成 MSI → 复制绿色版到 out。

### 方式 B：VS 里手动构建

1. 先执行第三步的 `dotnet publish`（发布目录要与 wixproj 中的 `PublishDir` 一致）。
2. 解决方案里右键 `AntPad.Installer` → 生成，得到 `TaoPad-1.0.0-x64.msi`。
3. 需要 EXE 的话再执行方式 C 中的第二条 `wix build` 命令。

### 方式 C：命令行（wix build）

```bash
# 1. 发布主程序（见第三步）
dotnet publish src/AntPad/AntPad.csproj -c Release -p:Platform=x64 -r win-x64 --self-contained true -p:WindowsAppSDKSelfContained=true

# 2. 生成 MSI
wix build src/Installer/Package.wxs ^
  -arch x64 -ext WixToolset.UI.wixext ^
  -p PublishDir=src/AntPad/bin/x64/Release/net8.0-windows10.0.19041.0/win-x64/publish/ ^
  -o out/TaoPad-1.0.0-x64.msi

# 3. 生成 EXE 安装向导（内嵌上面的 MSI）
wix build src/Installer/Bundle.wxs ^
  -p InstallerMsi=out/TaoPad-1.0.0-x64.msi ^
  -o out/TaoPad-1.0.0-x64.exe
```

版本升级时同步改两处：`Package.wxs` 的 `Version="1.0.0"` 与
`AntPad.Installer.wixproj` 的 `OutputName`。`UpgradeCode` 保持不变，
新 MSI 可直接覆盖升级旧版本。

## 五、可选：代码签名

未签名的 MSI 安装时会出 SmartScreen 警告。有代码签名证书（.pfx）时：

```bash
signtool sign /fd SHA256 /f mycert.pfx /p <证书密码> /t http://timestamp.digicert.com TaoPad-1.0.0-x64.msi
```

发布开源免费软件也可先不签名，警告点「仍要运行」即可。

## 六、装包后手工测试清单

沙箱无法运行 Windows GUI，以下项目请在装机后逐项确认（约 10 分钟）：

**安装向导**
- [ ] 功能树出现「主程序 + 9 个关联格式」勾选项，去掉勾选不装对应关联
- [ ] 安装完成后「应用」里出现 AntPad，含卸载入口
- [ ] 重复安装同版本 MSI 触发降级提示，卸载后再装正常

**关联行为**
- [ ] 勾选 `.txt` 后资源管理器双击 txt 用 AntPad 打开，图标变为 AntPad
- [ ] 未勾选的格式双击仍用原程序打开；右键「打开方式」里能看到 AntPad
- [ ] 卸载后原格式关联自动恢复（或恢复为系统默认）

**编辑器冒烟测试**
- [ ] 新建/打开/保存（UTF-8、GBK、UTF-16 各存一次，重开内容正确）
- [ ] 中文输入、删字、光标移动、双击选词、Shift 选区
- [ ] 撤销/重做：连续打字一步撤销；删除后重做
- [ ] 查找替换：普通/正则/整词/大小写/全部替换，F3 与 Shift+F3
- [ ] 行号、语法着色（打开 .cs / .py / .json / .xml / .md / .sql 各看一眼）
- [ ] Ctrl+滚轮缩放，跟随系统主题切换（Win11 深色模式切换观察）
- [ ] 大文件：打开 10MB 级文本，滚动与输入不卡顿
- [ ] 拖放文件到窗口打开；最近文件菜单正常

## 七、常见问题

| 现象 | 处理 |
|---|---|
| VS 打开 sln 提示缺少工作负载 | 装上「Windows 应用程序开发」工作负载（含 WinUI/WinAppSDK） |
| `error MSB4030`/平台不匹配 | 确认用 `-p:Platform=x64`，VS 平台下拉选 x64 |
| `wix build` 找不到 WixUI | `wix extension add -g WixToolset.UI.wixext`，命令行加 `-ext WixToolset.UI.wixext` |
| MSI 打包报找不到发布目录 | 先跑 `dotnet publish`，路径与 `DefineConstants.PublishDir` 一致 |
| 双击文件没反应 | Win11 首次关联后注销重登，或在「设置 → 默认应用」手动指定 |


## v25 变更（2026-10-31）

- **运行库随包集成**：EXE 安装包内已包含 Windows App Runtime 1.5 安装器，
  双击 EXE 一次装完，不再需要现场联网；运行库文件由脚本下载到
  `out\TaoPad-runtime-1.5.exe`（首次需联网，之后沿用本地缓存），
  EXE 安装包体积因此变为几十 MB，MSI 仍为几 MB。
  首次下载失败时脚本会明确报错，重跑即可。
- **单实例**：程序已运行时再双击文件，会在现有程序中开新窗口，
  不再另起进程（文件路径经本机命名管道转交，可靠）。
- **编辑核心**：改为系统文本控件（输入稳定），语法着色与行号暂缺，
  智能提示按 VS 交互提供（前缀触发 + 点号出成员，↑↓/回车/Esc 操作）。


## v26 变更（2026-10-31）：微信式单页安装界面

- 双击 EXE 不再是多页向导，而是一页式安装界面：
  顶部许可协议滚动框 → 勾选“我已阅读并同意许可协议” →
  安装目录输入框（可直接输入不存在的路径，自动创建文件夹）→
  三个选项勾选（桌面快捷方式 / 右键菜单 / 关联常见文档类型，默认全开）→
  “立即安装”大按钮 → 确认页 → 进度 → 完成。
- 未勾选许可时点“立即安装”会弹小提醒，不会进入安装。
- 取消勾选的选项在安装时自动跳过对应组件。
