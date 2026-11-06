# 源码树常驻自检（2026-11-01 全系铁律）：构建前卡死两类历史坑
# 1) BOM 铁律：所有 .cs/.xaml 必须带 UTF-8 BOM（GBK 机器上无 BOM 会把中文读错，编译报错或运行乱码）
# 2) 命名铁律：全树文件名必须 ASCII（路径/文件名零中文；界面字符串与注释保留中文不受影响）
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$bad = @()
Get-ChildItem -Path $root -Recurse -File -Include *.cs,*.xaml |
    Where-Object { $_.FullName -notmatch '\\(obj|bin)\\' } | ForEach-Object {
    $b = [System.IO.File]::ReadAllBytes($_.FullName)
    if ($b.Length -lt 3 -or $b[0] -ne 0xEF -or $b[1] -ne 0xBB -or $b[2] -ne 0xBF) {
        $bad += ("缺BOM: " + $_.FullName.Substring($root.Length + 1))
    }
}
Get-ChildItem -Path $root -Recurse -File |
    Where-Object { $_.FullName -notmatch '\\(obj|bin|\.git|\.vs)\\' } | ForEach-Object {
    if ($_.Name -match '[^\x20-\x7E]') {
        $bad += ("非ASCII文件名: " + $_.FullName.Substring($root.Length + 1))
    }
}
if ($bad.Count -gt 0) {
    $bad | ForEach-Object { Write-Host $_ }
    throw ("源码自检失败 " + $bad.Count + " 项，请把以上内容发给开发助手")
}
Write-Host "源码自检: 通过（全部 .cs/.xaml 带 BOM，文件名全 ASCII）"
