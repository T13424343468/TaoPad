REM TaoPad 一键构建（需 Windows 10 1809+ 与 .NET 8 SDK）
REM 产物统一输出 out 文件夹: 仅 1 项 TaoPad-1.0.9-x64.msi（微信风格安装器）
@echo off
chcp 936 >nul
cd /d "%~dp0"
echo [准备] 清理旧编译缓存, 防止 XAML 编译器增量状态损坏...
if exist src\AntPad\obj rmdir /s /q src\AntPad\obj >nul 2>&1
if exist src\AntPad\bin rmdir /s /q src\AntPad\bin >nul 2>&1
echo [1/5] 源码自检 (BOM/命名铁律, 不过不编译)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\Check-Source.ps1" || goto :err
echo [2/5] 还原依赖...
dotnet restore src\AntPad\AntPad.csproj || goto :err
echo [3/5] 生成自包含发布包 (首次较慢, 需下载运行时组件)...
dotnet publish src\AntPad\AntPad.csproj -c Release -r win-x64 --self-contained true -p:WindowsAppSDKSelfContained=true -p:Platform=x64 || goto :err
set "PUBDIR=src\AntPad\bin\x64\Release\net8.0-windows10.0.19041.0\win-x64\publish"
if not exist "%PUBDIR%\TaoPad.exe" set "PUBDIR=src\AntPad\bin\x64\Release\net8.0-windows10.0.19041.0\x64\win-x64\publish"
echo [4/5] 生成安装器 (.msi, 首次需联网安装打包工具)...
if exist out rmdir /s /q out >nul 2>&1
if exist out (
    echo [!] out 文件夹清不掉: 多半是资源管理器正停在 out 里面, 关掉该窗口后重跑。
    pause
    exit /b 1
)
if not exist out mkdir out
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\msi\package.ps1" -PublishDir "%PUBDIR%" -OutDir "out" -WxsPath "src\Installer\Package.wxs" || goto :err
echo [5/5] out 清单自检 (应只有 1 项 msi)...
set N=0
del /q out\*.wixpdb 2>nul
for /f %%i in ('dir /b out\*.msi 2^>nul ^| find /c /v ""') do set N=%%i
if not "%N%"=="1" (
    echo [!] out 清单自检失败: 应只有 1 项, 实际 %N% 项。请把此信息发给开发助手
    pause
    exit /b 1
)
echo.
echo 完成! out 文件夹里只有一项:
echo   TaoPad-1.0.9-x64.msi     —— 微信风格安装器: 单页界面, 目录可改, 选项可勾
pause
exit /b 0
:err
echo 构建失败, 请把上方报错内容发给开发助手
pause
exit /b 1
