@echo off
chcp 936 >nul
title TaoPad 环境查一查
echo ===== 正在运行的 TaoPad 程序及路径 =====
powershell -NoProfile -Command "Get-Process TaoPad -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path"
if errorlevel 1 echo （当前没有运行中的 TaoPad）
echo.
echo ===== 系统里登记过的安装项 =====
powershell -NoProfile -Command "Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -like '*TaoPad*'} | Select-Object DisplayName, InstallLocation | Format-List"
echo ===== 排查建议 =====
echo 1. 上面若出现多个不同路径，说明电脑上有多份 TaoPad：
echo    建议只留一份，其余在 设置-应用 里卸载或直接删除文件夹。
echo 2. 桌面/任务栏快捷方式：右键-打开文件位置，确认目标指向
echo    D:\Program Files\TaoPad\TaoPad.exe 或最新构建的 out\TaoPad\TaoPad.exe。
echo    指向旧文件夹的快捷方式请删除重建，避免测到老程序。
echo 3. 绿色版与安装版组件各自独立、不会互相污染；但两份同时只会
echo    显示一个窗口（先开的接管后开的）。测试时请只开一份。
pause
