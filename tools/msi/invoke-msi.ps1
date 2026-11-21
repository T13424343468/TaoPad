# msiexec 等待守卫（云测红1 修复, 2026-11-14）:
# 实锤: run 43599577839 install.log 显示 MSI 引擎 13:26:33-13:26:36 三秒走完 InstallFinalize 并成功(status 0),
# 挂点是 pwsh `Start-Process -Wait` 等待层 —— -Wait 会等目标进程及其全部后代, msiexec 退出后该层死等 38 分钟被 job 级超时砍掉。
# 这里改为只等 msiexec 主进程 + 超时封顶(默认 15 分钟); 超时或失败都抓安装日志尾部再 fail,
# 让证据随 CI 的 if:always() 归档步骤落盘, 下一班拿到日志可直接定位。
param(
    [Parameter(Mandatory = $true)][string]$MsiArgs,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [int]$TimeoutSec = 900
)
$ErrorActionPreference = 'Stop'
Write-Host "invoke-msi: msiexec $MsiArgs (等待上限 $TimeoutSec 秒)"
$p = Start-Process msiexec.exe -ArgumentList $MsiArgs -PassThru
if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    Write-Host "==== msiexec 超过 $TimeoutSec 秒未退出, 视为挂起, 抓取日志尾部 ===="
    if (Test-Path $LogPath) {
        Write-Host "---- $LogPath 尾部 100 行 ----"
        Get-Content $LogPath -Tail 100
    } else {
        Write-Host "安装日志不存在: $LogPath"
    }
    Write-Host "==== 结束挂起的 msiexec 进程树 (pid=$($p.Id)) ===="
    taskkill /f /t /pid $p.Id | Out-Null
    throw "msiexec 等待超时($TimeoutSec 秒), 按挂起处理: $MsiArgs (日志尾部见上方输出)"
}
$code = $p.ExitCode
Write-Host "msiexec exit=$code"
if ($code -notin 0, 3010) {
    if (Test-Path $LogPath) {
        Write-Host "---- $LogPath 尾部 100 行 ----"
        Get-Content $LogPath -Tail 100
    }
    # 运行时保障日志 (机器级固定路径): 自定义动作成败的第一手证据, 失败时一并落盘
    $rtLog = Join-Path $env:ProgramData 'TaoPad\taopad-runtime.log'
    if (Test-Path $rtLog) {
        Write-Host "---- $rtLog 全文 ----"
        Get-Content $rtLog
    } else {
        Write-Host "运行时保障日志不存在: $rtLog (自定义动作可能未执行到写日志处)"
    }
    $caOut = Join-Path $env:ProgramData 'TaoPad\ca-out.txt'
    if (Test-Path $caOut) {
        Write-Host "---- $caOut 全文 (自定义动作 PS 输出) ----"
        Get-Content $caOut
    }
    throw "msiexec 失败 exit=$code ($MsiArgs)"
}
