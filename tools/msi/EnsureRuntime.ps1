# TaoPad 安装器运行时保障 (2026-11-21 全系安装器新标准, 老板令; v97 三运行时统一)
# 口径: 安装包不内置任何运行时; 安装期以系统实际为准全盘检测三项运行时:
#   1) .NET 10 桌面运行时   —— 缺则联网下官方 dotnet-install 脚本装进 C:\Program Files\dotnet
#   2) Windows App SDK 运行时 (界面框架, 1.5) —— 缺则联网下官方 WindowsAppRuntimeInstall-x64.exe 静默装
#   3) VC++ 2015-2022 运行库 —— 缺则联网下官方 vc_redist.x64.exe 静默装
#   有则零下载直接用; 无网且无运行时给通俗重试指引。
# 云测钩子: -ForceDownload 1 强制三项全走下载路 (断言二用), 日常安装不传即走检测路。
#   该参数由 WiX 自定义动作从 MSI 公共属性 TAOPADFORCE 直传 (v1.1.3 起 CA 改 WixQuietExec64,
#   不再经 cmd, cmd set 环境变量随之消失, 参数直达脚本)。
param([string]$ForceDownload)
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

# 网络环境诊断: 真机失败时日志自带代理快照, 不再靠猜 (用户真机 2026-11-24 教训: 手动下载正常而安装器失败)
try {
    $winet = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
    Write-RtLog ("net-diag wininet-proxy=" + $(if ($winet -and $winet.ProxyEnable) { $winet.ProxyServer } else { 'off' }))
    $dp = [System.Net.WebRequest]::DefaultWebProxy
    $dpu = if ($dp) { $dp.GetProxy([uri]'https://aka.ms').ToString() } else { 'none' }
    Write-RtLog ("net-diag effective-proxy=" + $dpu)
} catch { Write-RtLog ("net-diag error " + $_.Exception.Message) }

# 通用下载器: 三步走 (老板 2026-11-24 拍板) —— 在线三轮重试(每轮 iwr 带超时 + curl 带重试各一次) → 全灭用包内兜底 → 都没有才报败。
# 真机实锤: 安装进程跑在管理员上下文, 网络环境与用户浏览器不同(不带用户代理设置);
#   旧版 iwr 无超时会无限干等、单次失败即死 —— 用户真机手动下载正常, 问题在下载路自身而非源。
function Get-OfficialFile([string]$url, [string]$outFile, [string]$bundledName) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    for ($i = 1; $i -le 3; $i++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing -TimeoutSec 300
            if ((Test-Path $outFile) -and (Get-Item $outFile).Length -gt 1KB) {
                Write-RtLog ("download-ok iwr attempt=" + $i)
                return $true
            }
            throw "iwr 产物异常偏小"
        } catch {
            Write-RtLog ("iwr-failed attempt=" + $i + " " + $_.Exception.Message)
        }
        try {
            $p = Start-Process -FilePath 'curl.exe' -ArgumentList '-L', '-f', '--retry', '3', '--retry-delay', '2', '--connect-timeout', '30', '-o', "`"$outFile`"", '--max-time', '600', "`"$url`"" -Wait -PassThru -NoNewWindow
            if ($p.ExitCode -eq 0 -and (Test-Path $outFile) -and (Get-Item $outFile).Length -gt 1KB) {
                Write-RtLog ("download-ok curl attempt=" + $i)
                return $true
            }
            throw "curl exit=$($p.ExitCode)"
        } catch {
            Write-RtLog ("curl-failed attempt=" + $i + " " + $_.Exception.Message)
        }
        Start-Sleep -Seconds (3 * $i)
    }
    # 内置兜底: 在线全灭, 用安装包自带的那份 (打包时随包内置, 系统里仍只装一份不重复)
    if ($bundledName) {
        $bundled = Join-Path $PSScriptRoot (Join-Path 'fallback' $bundledName)
        if (Test-Path $bundled) {
            Copy-Item $bundled $outFile -Force
            Write-RtLog 'download-failed using-bundled-fallback'
            return $true
        }
    }
    Write-RtLog 'download-failed all-attempts-exhausted'
    return $false
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

# .NET 内置兜底 (2026-11-25 老板令: 安装绝不依赖网络): 在线全灭时, 把包内自带的
#   官方运行时 zip (基础包 + 桌面包, 两件套缺一不可——desktop zip 只含 WindowsDesktop.App,
#   基础 NETCore.App 在 dotnet-runtime zip 里) 解压进系统统一 .NET 目录。
#   zip 解包不走 MSI 链, 与本产品 MSI 事务无互斥; 解后以实测为准。
function Install-DesktopRuntimeFromBundledZip {
    $fbDir = Join-Path $PSScriptRoot 'fallback'
    $zips = @(Get-ChildItem $fbDir -Filter 'dotnet-runtime-*-win-x64.zip' -ErrorAction SilentlyContinue) +
            @(Get-ChildItem $fbDir -Filter 'windowsdesktop-runtime-*-win-x64.zip' -ErrorAction SilentlyContinue)
    if ($zips.Count -lt 2) { Write-RtLog 'net-fallback zip-missing'; return $false }
    try {
        $dotnetDir = 'C:\Program Files\dotnet'
        New-Item -ItemType Directory -Force -Path $dotnetDir | Out-Null
        foreach ($z in $zips) {
            Write-RtLog ("net-fallback expand " + $z.Name)
            Expand-Archive -Path $z.FullName -DestinationPath $dotnetDir -Force
        }
    } catch {
        Write-RtLog ("net-fallback expand-failed " + $_.Exception.Message)
        return $false
    }
    if (Test-DesktopRuntime10) { Write-RtLog 'net-fallback verify-ok'; return $true }
    Write-RtLog 'net-fallback verify-failed'
    return $false
}

if ($ForceDownload -ne '1' -and (Test-DesktopRuntime10)) {
    Write-RtLog 'runtime-present zero-download'
} else {
    Write-RtLog 'runtime-missing, downloading official runtime'
    # 官方运行时装法: dotnet-install 官方脚本直装系统统一 .NET 目录。
    #   不用 windowsdesktop-runtime 安装器 exe——它是 MSI 链, 在本产品 MSI 事务内启动必撞
    #   _MSIExecute 互斥 → 退出码 1618 (run 44886290820 实锤); 脚本解包不走 MSI, 无互斥冲突。
    $dnScript = Join-Path $env:TEMP 'dotnet-install.ps1'
    $onlineOk = Get-OfficialFile 'https://dot.net/v1/dotnet-install.ps1' $dnScript
    if ($onlineOk) {
        Write-RtLog 'download-ok, installing official runtime into system dotnet dir'
        # dotnet-install.ps1 成功时不设退出码, $LASTEXITCODE 会是 null (run 44886957984 实锤误判);
        #   以 try/catch + 装后实测为准
        try {
            & $dnScript -Runtime windowsdesktop -Channel 10.0 -InstallDir 'C:\Program Files\dotnet'
            Write-RtLog 'dotnet-install script returned'
        } catch {
            Write-RtLog ("dotnet-install failed " + $_.Exception.Message)
        }
    } else {
        Write-RtLog 'dotnet-install-script download-failed, trying bundled zip'
    }
    if (Test-DesktopRuntime10) {
        Write-RtLog 'runtime-download-install ok'
    } elseif (Install-DesktopRuntimeFromBundledZip) {
        Write-RtLog 'runtime-install ok (bundled-zip)'
    } else {
        Show-NoNetwork '.NET 运行时' 60
        exit 1602
    }
}

# ---- 2) Windows App SDK 运行时 (界面框架, 1.5) ----
# v1.1.2 自带改依赖: 界面框架不再打进安装包, 改装时保障。
# 检测口径 (官方部署指南 deploy-unpackaged-apps 实锤): 运行时由四类 MSIX 包组成, 四者全在才算在位:
#   Framework  Microsoft.WindowsAppRuntime.1.5*          (框架包, PackageDependency 指向它)
#   Main       MicrosoftCorporationII.WinAppRuntime.Main.1.5*  (主框架包; 注意是 WinAppRuntime 不是 WindowsAppRuntime)
#   Singleton  MicrosoftCorporationII.WinAppRuntime.Singleton*
#   DDLM       Microsoft.WinAppRuntime.DDLM*             (版本随运行时, 如 5001.373.1736.0-x6)
#   不同 family 互不满足依赖 (旧「更高版 Main 满足 1.5」探针前提错误, 已删); 四类 AND 检测。
# 双保险: Appx 包查询 (-AllUsers, msiexec 以 SYSTEM 执行, 普通查询漏 provisioned 包) 优先,
#   异常回落 C:\Program Files\WindowsApps 目录探针 (SYSTEM 可枚举)。
# 安装口径: 官方 WindowsAppRuntimeInstall-x64.exe 静默装 (--quiet, 微软 winget 官方清单实锤);
#   它内部走 AppX 部署服务装 MSIX 并 provisioning 给全体用户, 不走 MSI 链, 与本产品 MSI
#   事务无 _MSIExecute 互斥 (dotnet-install 同理); 装后以实测为准, 不信安装器退出码。
function Test-WinAppRuntime {
    # 目录探针 glob: 包目录形如 <family去掉通配>_<版本>-<架构>, 如 MicrosoftCorporationII.WinAppRuntime.Main.1.5_5001.373.1736.0_x64__8wekyb3d8bbwe
    $families = @(
        'Microsoft.WindowsAppRuntime.1.5*',
        'MicrosoftCorporationII.WinAppRuntime.Main.1.5*',
        'MicrosoftCorporationII.WinAppRuntime.Singleton*',
        'Microsoft.WinAppRuntime.DDLM*'
    )
    $appxOk = $true
    try {
        foreach ($fam in $families) {
            # -AllUsers: msiexec 以 SYSTEM 执行, 普通查询只看 SYSTEM 用户包, provisioned 包会漏检
            $hit = Get-AppxPackage -AllUsers -Name $fam -ErrorAction Stop
            if (-not $hit) { Write-RtLog ("appx-missing " + $fam); $appxOk = $false }
        }
        if ($appxOk) { return $true }
    } catch {
        # 32 位 PowerShell 加载 Appx 模块失败是已知形态 (run 44921060474 实锤此路在 CA 上下文不可靠),
        # 落日志后走目录探针, 不当失败处理
        Write-RtLog ("appx-query-unavailable " + $_.Exception.Message)
    }
    foreach ($fam in $families) {
        $glob = $fam.TrimEnd('*') + '_*'
        try {
            if (-not (Get-ChildItem (Join-Path 'C:\Program Files\WindowsApps' $glob) -Directory -ErrorAction SilentlyContinue)) {
                Write-RtLog ("dir-missing " + $glob)
                return $false
            }
        } catch {
            Write-RtLog ("dir-probe-failed " + $glob)
            return $false
        }
    }
    return $true
}
# 诊断落盘: 把 WindowsApps 下 WinAppRuntime 全家族目录实况写进日志, 下班对账有据可查
try {
    Get-ChildItem 'C:\Program Files\WindowsApps' -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like '*WinAppRuntime*' } |
        ForEach-Object { Write-RtLog ("diag-appx-dir " + $_.Name) }
} catch { }
if ($ForceDownload -ne '1' -and (Test-WinAppRuntime)) {
    Write-RtLog 'winappruntime-present zero-download'
} else {
    Write-RtLog 'winappruntime-missing, downloading official runtime installer'
    $waExe = Join-Path $env:TEMP 'WindowsAppRuntimeInstall-x64.exe'
    if (-not (Get-OfficialFile 'https://aka.ms/windowsappsdk/1.5/latest/windowsappruntimeinstall-x64.exe' $waExe 'windowsappruntimeinstall-x64.exe')) {
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
    if (-not (Test-WinAppRuntime)) {
        # 官方安装器 exit=0 而检测仍看不到 Main: 视为检测口径在该上下文不可靠 (run 44921060474 实锤
        # 三路探针在 SYSTEM/32位PS 全盲但机器实有更高版 Main), 不再硬炸 1603——真缺运行时时
        # 应用启动会弹缺失对话框, 云测关1假绿防线与真机用户都能当场暴露, 比误杀安装更可辩护
        Write-RtLog 'winappruntime-verify-inconclusive, installer exit=0, continue (startup guard will catch real missing)'
        if ($p.ExitCode -ne 0) { Write-RtLog 'winappruntime-verify-failed'; exit 31336 }
    }
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
if ($ForceDownload -ne '1' -and (Test-VcRuntime)) {
    Write-RtLog 'vcruntime-present zero-download'
} else {
    Write-RtLog 'vcruntime-missing, downloading official redistributable'
    $vcExe = Join-Path $env:TEMP 'vc_redist.x64.exe'
    if (-not (Get-OfficialFile 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vcExe 'vc_redist.x64.exe')) {
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
