# TaoPad 安装器运行时保障 (2026-11-21 全系安装器新标准, 老板令; v97 三运行时统一)
# 口径: 安装包不内置任何运行时; 安装期以系统实际为准全盘检测三项运行时:
#   1) .NET 10 桌面运行时   —— 缺则联网下官方 dotnet-install 脚本装进 C:\Program Files\dotnet
#   2) Windows App SDK 运行时 (界面框架, 1.5) —— 缺则联网下官方 WindowsAppRuntimeInstall-x64.exe 静默装
#   3) VC++ 2015-2022 运行库 —— 缺则联网下官方 vc_redist.x64.exe 静默装
#   有则零下载直接用; 无网且无运行时给通俗重试指引。
# 云测钩子: TAOPAD_FORCE_RUNTIME_DOWNLOAD=1 强制三项全走下载路 (断言二用), 日常安装不设即走检测路。
#   该变量由 WiX 自定义动作内 cmd set 从 MSI 公共属性 TAOZIPFORCE 注入 (环境变量传不进 msiexec 服务上下文, run 44885229031 实锤)。
$ErrorActionPreference = 'Stop'
# 日志落机器级固定路径: 本脚本由 WiX 自定义动作在 per-machine msiexec (SYSTEM) 上下文执行,
#   $env:TEMP 指向 C:\Windows\Temp, 云测断言按 runner 用户 TEMP 查不到 (run 44870126512 实锤);
#   ProgramData 下产品目录全用户可读, SYSTEM/用户均可写
$rtLogDir = Join-Path $env:ProgramData 'TaoPad'
if (-not (Test-Path $rtLogDir)) { New-Item -ItemType Directory -Force -Path $rtLogDir | Out-Null }
$log = Join-Path $rtLogDir 'taopad-runtime.log'
function Write-RtLog([string]$m) {
    try { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) } catch { }
}

# 通用下载器: iwr 先行, 失败回落系统自带 curl.exe (32 位 PS 5.1 在 SYSTEM 上下文偶发秒败, run 44875970874 实锤)
function Get-OfficialFile([string]$url, [string]$outFile) {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing
    } catch {
        Write-RtLog ("iwr-failed " + $_.Exception.Message + ", fallback to curl.exe")
        try {
            $p = Start-Process -FilePath 'curl.exe' -ArgumentList '-L', '-f', '-o', "`"$outFile`"", '--max-time', '600', "`"$url`"" -Wait -PassThru -NoNewWindow
            if ($p.ExitCode -ne 0) { throw "curl exit=$($p.ExitCode)" }
            if (-not (Test-Path $outFile) -or (Get-Item $outFile).Length -lt 1KB) { throw "curl 产物异常偏小" }
        } catch {
            Write-RtLog ("download-failed " + $_.Exception.Message)
            return $false
        }
    }
    return (Test-Path $outFile)
}

# 无网统一指引: 仅交互会话弹窗; SYSTEM/会话0 里弹窗无人点击会挂死安装 (防御性修复)
function Show-NoNetwork([string]$what, [int]$mb) {
    $msg = "TaoPad 需要联网下载$what（约 $mb MB），当前没有检测到网络连接。`n`n请连上网络后重新运行安装程序即可，无需其他操作。"
    try {
        if ([Environment]::UserInteractive) {
            Add-Type -AssemblyName System.Windows.Forms
            [System.Windows.Forms.MessageBox]::Show($msg, 'TaoPad 安装', 'OK', 'Information') | Out-Null
        }
    } catch { }
}

# ---- 1) .NET 10 桌面运行时 ----
function Test-DesktopRuntime10 {
    # 以系统实际注册为准: 统一目录 shared 下有 10.x 桌面运行时, 或注册表 InstalledVersions 有 10.x 键。
    # 注意: 本脚本由 WiX 自定义动作以 32 位 PowerShell 执行 (SysWOW64), $env:ProgramFiles 会指到
    #   'C:\Program Files (x86)', 注册表也会被重定向到 Wow6432Node (run 44875970874 实锤漏检);
    #   故目录按 64 位固定路径查, 注册表显式开 Registry64 视图。
    try {
        $shared = Get-ChildItem 'C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App' -ErrorAction SilentlyContinue |
                  Where-Object { $_.Name -like '10.*' }
        if ($shared) { return $true }
        $rk = [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', [Microsoft.Win32.RegistryView]::Registry64)
        $sub = $rk.OpenSubKey('SOFTWARE\dotnet\Setup\InstalledVersions\x64')
        if ($sub) {
            $hit = @($sub.GetSubKeyNames() | Where-Object { $_ -like '10.*' })
            if ($hit.Count -gt 0) { return $true }
        }
        return $false
    } catch { return $false }
}
if ($env:TAOPAD_FORCE_RUNTIME_DOWNLOAD -ne '1' -and (Test-DesktopRuntime10)) {
    Write-RtLog 'runtime-present zero-download'
} else {
    Write-RtLog 'runtime-missing, downloading official runtime'
    # 官方运行时装法: dotnet-install 官方脚本直装系统统一 .NET 目录。
    #   不用 windowsdesktop-runtime 安装器 exe——它是 MSI 链, 在本产品 MSI 事务内启动必撞
    #   _MSIExecute 互斥 → 退出码 1618 (run 44886290820 实锤); 脚本解包不走 MSI, 无互斥冲突。
    $dnScript = Join-Path $env:TEMP 'dotnet-install.ps1'
    if (-not (Get-OfficialFile 'https://dot.net/v1/dotnet-install.ps1' $dnScript)) {
        Show-NoNetwork '.NET 运行时' 60
        exit 1602
    }
    Write-RtLog 'download-ok, installing official runtime into system dotnet dir'
    # dotnet-install.ps1 成功时不设退出码, $LASTEXITCODE 会是 null (run 44886957984 实锤误判);
    #   以 try/catch + 装后实测为准
    try {
        & $dnScript -Runtime windowsdesktop -Channel 10.0 -InstallDir 'C:\Program Files\dotnet'
        Write-RtLog 'dotnet-install script returned'
    } catch {
        Write-RtLog ("dotnet-install failed " + $_.Exception.Message)
        exit 31338
    }
    if (-not (Test-DesktopRuntime10)) { Write-RtLog 'verify-failed'; exit 31337 }
    Write-RtLog 'runtime-download-install ok'
}

# ---- 2) Windows App SDK 运行时 (界面框架, 1.5) ----
# v1.1.2 自带改依赖: 界面框架不再打进安装包, 改装时保障。
# 检测口径双保险: Appx 包查询 (Microsoft.WindowsAppRuntime.1.5*) 优先, 异常回落
#   C:\Program Files\WindowsApps 目录探针 (SYSTEM 可枚举); 任一命中即算在位。
# 安装口径: 官方 WindowsAppRuntimeInstall-x64.exe 静默装 (--quiet, 微软 winget 官方清单实锤);
#   它内部走 AppX 部署服务装 MSIX 并 provisioning 给全体用户, 不走 MSI 链, 与本产品 MSI
#   事务无 _MSIExecute 互斥 (dotnet-install 同理); 装后以实测为准, 不信安装器退出码。
function Test-WinAppRuntime {
    try {
        # -AllUsers: msiexec 以 SYSTEM 执行, 普通查询只看 SYSTEM 用户包, provisioned 包会漏检
        $hit = Get-AppxPackage -AllUsers -Name 'Microsoft.WindowsAppRuntime.1.5*' -ErrorAction Stop
        if ($hit) { return $true }
    } catch { }
    try {
        if (Get-ChildItem 'C:\Program Files\WindowsApps\Microsoft.WindowsAppRuntime.1.5_*' -Directory -ErrorAction SilentlyContinue) { return $true }
    } catch { }
    return $false
}
if ($env:TAOPAD_FORCE_RUNTIME_DOWNLOAD -ne '1' -and (Test-WinAppRuntime)) {
    Write-RtLog 'winappruntime-present zero-download'
} else {
    Write-RtLog 'winappruntime-missing, downloading official runtime installer'
    $waExe = Join-Path $env:TEMP 'WindowsAppRuntimeInstall-x64.exe'
    if (-not (Get-OfficialFile 'https://aka.ms/windowsappsdk/1.5/latest/windowsappruntimeinstall-x64.exe' $waExe)) {
        Show-NoNetwork '界面框架运行时' 62
        exit 1602
    }
    Write-RtLog 'winappruntime-download-ok, installing silently'
    try {
        $p = Start-Process -FilePath $waExe -ArgumentList '--quiet' -Wait -PassThru -NoNewWindow
        Write-RtLog ("winappruntime-installer exit=" + $p.ExitCode)
    } catch {
        Write-RtLog ("winappruntime-install failed " + $_.Exception.Message)
        exit 31334
    }
    if (-not (Test-WinAppRuntime)) { Write-RtLog 'winappruntime-verify-failed'; exit 31336 }
    Write-RtLog 'winappruntime-download-install ok'
}

# ---- 3) VC++ 2015-2022 运行库 ----
# 官方部署指南明确: 依赖框架的未打包应用以 VC++ 可再发行包为先决条件, 缺失则程序起不来。
# 检测口径: 注册表 Runtimes\x64 Installed=1 (Registry64 视图, 32 位 PS 重定向坑同上) 或
#   System32 下 vcruntime140.dll 与 msvcp140.dll 双双在位; 安装器静默参数 /install /quiet /norestart,
#   退出码 1638=已有更新版本 (算在位), 3010=需重启 (装齐, 重启后生效)。
function Test-VcRuntime {
    try {
        $rk = [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', [Microsoft.Win32.RegistryView]::Registry64)
        $sub = $rk.OpenSubKey('SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64')
        if ($sub -and $sub.GetValue('Installed') -eq 1) { return $true }
    } catch { }
    try {
        if ((Test-Path 'C:\Windows\System32\vcruntime140.dll') -and (Test-Path 'C:\Windows\System32\msvcp140.dll')) { return $true }
    } catch { }
    return $false
}
if ($env:TAOPAD_FORCE_RUNTIME_DOWNLOAD -ne '1' -and (Test-VcRuntime)) {
    Write-RtLog 'vcruntime-present zero-download'
} else {
    Write-RtLog 'vcruntime-missing, downloading official redistributable'
    $vcExe = Join-Path $env:TEMP 'vc_redist.x64.exe'
    if (-not (Get-OfficialFile 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vcExe)) {
        Show-NoNetwork '系统组件' 25
        exit 1602
    }
    Write-RtLog 'vcruntime-download-ok, installing silently'
    try {
        $p = Start-Process -FilePath $vcExe -ArgumentList '/install', '/quiet', '/norestart' -Wait -PassThru -NoNewWindow
        Write-RtLog ("vcruntime-installer exit=" + $p.ExitCode)
        if ($p.ExitCode -eq 1638) { Write-RtLog 'vcruntime-newer-already-installed' }
        elseif ($p.ExitCode -eq 3010) { Write-RtLog 'vcruntime-installed-reboot-required' }
        elseif ($p.ExitCode -ne 0) { Write-RtLog 'vcruntime-installer-failed'; exit 31333 }
    } catch {
        Write-RtLog ("vcruntime-install failed " + $_.Exception.Message)
        exit 31335
    }
    if (-not (Test-VcRuntime)) { Write-RtLog 'vcruntime-verify-failed'; exit 31333 }
    Write-RtLog 'vcruntime-download-install ok'
}
Write-RtLog 'all-runtimes ok'
exit 0
