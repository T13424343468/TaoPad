@echo off
chcp 936 >nul
title TaoPad 崩溃现场抓取
REM ============================================================
REM  让系统在程序意外退出时自动保存现场快照（dump）。
REM  这种方式连"立即处决式"的崩溃都能抓住，一次配置长期有效。
REM ============================================================
net session >nul 2>&1
if errorlevel 1 (
  echo 需要管理员权限：请右键本文件，选择"以管理员身份运行"。
  pause
  exit /b 1
)
reg add "HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\TaoPad.exe" /v DumpFolder /t REG_EXPAND_SZ /d "%LOCALAPPDATA%\TaoPad\dumps" /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\TaoPad.exe" /v DumpType /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\TaoPad.exe" /v DumpCount /t REG_DWORD /d 5 /f >nul
echo 已开启。之后程序每次意外退出，系统会自动把现场快照存到：
echo   %LOCALAPPDATA%\TaoPad\dumps
echo.
echo 复现闪退后，把该文件夹里最新的 .dmp 文件发回来即可定位。
echo （只想取消抓取时，删除注册表里 LocalDumps\TaoPad.exe 这一项即可）
pause
