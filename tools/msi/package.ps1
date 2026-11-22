# 生成 TaoPad 的微信风格安装器 (.msi)
# 单页界面：许可勾选 + 安装目录(可自由修改) + 快捷方式/右键菜单/文件关联可勾选
# 用法: powershell -File package.ps1 -PublishDir <publish目录> -OutDir <out目录> [-WxsPath <安装定义>]
param(
    [Parameter(Mandatory = $true)][string]$PublishDir,
    [string]$OutDir = "out",
    [string]$WxsPath = "src\Installer\Package.wxs"
)
$ErrorActionPreference = 'Stop'
$publishRoot = (Resolve-Path $PublishDir).Path
if (-not (Test-Path (Join-Path $publishRoot 'TaoPad.exe'))) {
    throw "发布目录里没找到 TaoPad.exe: $PublishDir"
}
if (-not (Test-Path $WxsPath)) { throw "找不到安装定义文件: $WxsPath" }

# wix 命令可能没装，也可能装的是旧版（如 v5，会报 WIX6101）：统一确保为 6.x
$env:PATH = "$env:USERPROFILE\.dotnet\tools;$env:PATH"
$wixVer = ""
try { $wixVer = (wix --version 2>$null | Out-String).Trim() } catch {}
if ($wixVer -notmatch '^6') {
    $listed = ((dotnet tool list --global | Out-String) -match '(?m)^\s*wix\s')
    if ($listed) {
        dotnet tool update --global wix --version 6.0.2
    } else {
        dotnet tool install --global wix --version 6.0.2
    }
    if ($LASTEXITCODE -ne 0) { throw "WiX 打包工具自动安装失败，请检查网络后重试" }
    $wixVer = (wix --version 2>$null | Out-String).Trim()
    if ($wixVer -notmatch '^6') { throw "WiX 工具版本不对 ($wixVer)，请把该信息发给开发助手" }
}

# 文件名版本号取自安装定义（Package.wxs 的 Package Version），杜绝手写漂移
# （2026-11-18 审查发现：原写死 TaoPad-1.0.9，出 1.1.0 包会顶旧名）
$wxsRaw = Get-Content $WxsPath -Raw
if ($wxsRaw -notmatch 'Version="(\d+\.\d+\.\d+)"') { throw "Package.wxs 里找不到版本号" }
$pkgVersion = $Matches[1]
$msi = Join-Path $OutDir "TaoPad-$pkgVersion-x64.msi"
if (Test-Path $msi) { Remove-Item $msi -Force }
# ---- 全系安装器运行时新标准 (2026-11-21 老板令): 安装包不内置运行时 ----
# 安装期由 EnsureRuntime.ps1 检测/补装三项运行时; 脚本随发布文件进包 (wxs Files ** 自动收)。
# 顺序铁律 (TaoPad run 44902065712 实锤 1603): 拷贝必须排在 wix build 之前——
# Files Include 是打包瞬间枚举发布目录, 拷贝放在 build 后面 = 脚本永远进不了 MSI,
# CA 起跑 powershell -File 找不到文件秒退 (ca-out.txt: "does not exist")。
$rtSrc = Join-Path $PSScriptRoot 'EnsureRuntime.ps1'
if (-not (Test-Path $rtSrc)) { throw "运行时保障脚本缺失: $rtSrc (请使用完整包)" }
Copy-Item $rtSrc (Join-Path $publishRoot 'EnsureRuntime.ps1') -Force

# PublishDir 由命令行传入，界面文件不用改动
# -ext WixToolset.Util.wixext：EnsureRuntimes CA 用 WixQuietExec64（下载不弹命令窗，全系安装器标准）
# -pdbtype none：不落调试附档（.wixpdb），保证 out 里只有 msi 一项
& wix build $WxsPath -d "PublishDir=$publishRoot" -o $msi -pdbtype none -ext WixToolset.Util.wixext
if ($LASTEXITCODE -ne 0) { throw "WiX 构建 msi 失败" }
Get-ChildItem $OutDir -Filter *.wixpdb -ErrorAction SilentlyContinue | Remove-Item -Force

# ===== 构建后自检：MSI 里必须真的带微信风格单页界面（MainDlg）=====
# 防止"源码里定义了，装出来却是标准向导"的回归：出包时就把问题卡死。
$found = $false
try {
    # 直接走 COM 晚绑定调用（不要用 InvokeMember 反射：
    # 部分机器上反射封送参数类型不匹配会报 DISP_E_TYPEMISMATCH）。
    # 用 SELECT * 全表扫：Control 表的对话框列实际叫 Dialog_（带下划线），
    # 之前按 "Dialog" 查会报 OpenView,Sql（列不存在）。
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $db = $installer.OpenDatabase((Resolve-Path $msi).Path, 0)
    $view = $db.OpenView("SELECT * FROM ``Control``")
    $view.Execute()
    while ($true) {
        $rec = $view.Fetch()
        if ($null -eq $rec) { break }
        if ($rec.StringData(1) -eq 'MainDlg') { $found = $true; break }
    }
    $view.Close()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($view) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($db) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($installer) | Out-Null
} catch {
    throw "自检执行失败（无法读取 MSI 界面表）：$($_.Exception.Message)"
}
if (-not $found) {
    throw "自检失败：MSI 里没有微信风格单页界面（MainDlg），装出来会是标准向导！请把此信息发给开发助手"
}
Write-Host "安装器已生成: $msi"
Write-Host "微信风格界面自检: 通过（单页许可 + 目录可改 + 选项可勾）"
