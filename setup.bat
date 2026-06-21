@echo off
chcp 65001 >nul
title AI Team Hub - 安装程序
echo ============================================
echo   AI Team Hub — Windows 安装
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.11+
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [1/4] Python 已检测 ✓

:: Check Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Node.js，请先安装 Node.js 18+
    echo 下载: https://nodejs.org/
    pause
    exit /b 1
)
echo [2/4] Node.js 已检测 ✓

:: Install Python deps
echo [3/4] 安装 Python 依赖...
pip install fastapi uvicorn sqlalchemy aiosqlite httpx socksio python-multipart 2>&1 | findstr /i "Successfully"
echo Python 依赖安装完成 ✓

:: Install Node deps
echo [4/4] 安装 Node 依赖...
cd /d "%~dp0frontend"
call npm install 2>&1 | findstr /i "added"
cd /d "%~dp0"

:: Done
echo.
echo ============================================
echo   ✅ 安装完成
echo.
echo   启动方式（二选一）:
echo.
echo   ① 双击 start.bat
echo   ② 或运行: start.bat
echo.
echo   然后浏览器打开: http://localhost:5173
echo ============================================
echo.
pause
