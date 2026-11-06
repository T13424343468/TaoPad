# TaoPad 构建与发布指南

> **v24 起本指南的打包部分仅作历史存档**：构建体系已对齐 TaoZip，打包命令以源码根目录 `build.bat` 与 `tools/msi/package.ps1` 为准（双击 build.bat 一键完成）。


## 1. 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Windows | 10 1809+ / 11 | 构建机 |
| .NET SDK | 8.0+ | `dotnet --version` 验证 |
| Windows App SDK | 1.5（NuGet 自动还原） | 无需手动装运行库 |
| WiX Toolset | 5.0.2 | bat 首次运行自动 `dotnet tool install` |

## 2. 用户一键打包（推荐）

```
build-installer.bat
```

流程：① 安装/重置 WiX 5.0.2 与扩展 → ② `dotnet publish`（x64，自包含，运行库全内嵌）→ ③ 生成 MSI → ④ 生成 EXE 安装器。
产物在 `out\`：`TaoPad-1.7.0-x64.msi` 与 `TaoPad-1.7.0-x64.exe`。全程无需联网。

## 3. 开发者手动构建

```bash
# 编译主程序
dotnet build src/AntPad/AntPad.csproj -c Release -p:Platform=x64

# 发布（自包含）
dotnet publish src/AntPad/AntPad.csproj -c Release -p:Platform=x64 -r win-x64 \
  --self-contained true -p:WindowsAppSDKSelfContained=true

# MSI（进入 src/Installer 目录执行）
wix build Package.wxs -bindpath <publish目录> -d "PublishDir=<publish目录>/"
# EXE 安装器
wix build Bundle.wxs -ext WixToolset.BootstrapperApplications.wixext -d InstallerMsi=<msi路径>
```

## 4. 质量验证（发布前必做）

1. **编译零警告**：`dotnet build` 产品代码 0 error / 0 warning（测试桩除外）。
2. **逻辑回归**：logictest 工程 41 项全过（Tokenizer/CompletionEngine/编码/格式化/文本往返）。
3. **安装包基线**：wix 构建 error 仅有 WIX0389（跨平台构建的固有提示）；出现其他 WIX 错误必须修复。
4. **静态规范**：
   - 源码 .cs/.xaml/.wxs/.csproj 必须 UTF-8 **BOM**；
   - .bat 必须 **GBK + CRLF**（python 字节级写入，禁止文本编辑器直接存）；
   - Package.wxs / Bundle.wxs / bat 产物名 / README 的版本号**四处一致**。

## 5. 版本发布规则（重要）

- **每次交付必须递增版本号**：Package.wxs 与 Bundle.wxs 的 `Version`（如 1.7.0→1.8.0）。
  - 同版本号重装不会触发 MajorUpgrade，会并排出多个旧条目且用户可能一直运行旧文件（v38 教训）。
- UpgradeCode 恒定不变；bat 中产物文件名与 README 截图说明同步修改。
- 命名：`TaoPad-<版本>-x64.msi/.exe`。

## 6. 常见问题

| 现象 | 原因与处理 |
|---|---|
| WIX8016/文件占用 | 关闭正在运行的 TaoPad 与资源管理器占用后重试 |
| WIX0389 | Linux/非 Windows 构建的平台提示，可忽略 |
| 装完双击无反应 | 检查是否装了旧版本（设置→应用 全部卸载后重装）；看 %LOCALAPPDATA%\TaoPad\crash.log |
| 安装出现多个旧版本 | v38 前的历史遗留；卸载旧条目后安装 1.5.0+ 会自动清理同版本链 |
