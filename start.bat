@echo off
chcp 65001 >nul 2>&1
title AI Team Hub - 启动器
color 0A

echo ============================================
echo   AI Team Hub - 团队协作平台
echo   学校代理网络开箱即用版
echo ============================================
echo.

cd /d "%~dp0"

:: ── 检测代理 ──
:: 检查大/小写两种环境变量（Windows 10 学校网络常见配置）
set PROXY_DETECTED=0
if not "%HTTP_PROXY%"=="" set PROXY_DETECTED=1
if not "%HTTPS_PROXY%"=="" set PROXY_DETECTED=1
if not "%http_proxy%"=="" set PROXY_DETECTED=1
if not "%https_proxy%"=="" set PROXY_DETECTED=1

if %PROXY_DETECTED% equ 1 (
    echo [✓] 检测到系统代理
    if not "%HTTP_PROXY%"==""  echo      HTTP_PROXY = %HTTP_PROXY%
    if not "%http_proxy%"==""  echo      http_proxy = %http_proxy%
) else (
    echo [!] 未检测到系统代理
    echo     如果在学校网络下，请先设置代理再重新运行：
    echo.
    echo      set HTTP_PROXY=http://你的代理地址:端口
    echo      set HTTPS_PROXY=http://你的代理地址:端口
    echo.
)
echo.

:: ── 检测 Python ──
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [×] 错误：未检测到 Python
    echo.
    echo     下载 Python 3.11+（安装时务必勾选 "Add Python to PATH"）:
    echo     https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo [1/4] %PY_VER% ✓
echo.

:: ── 检测 Node.js ──
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [×] 错误：未检测到 Node.js
    echo.
    echo     下载 Node.js 18+:
    echo     https://nodejs.org/
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%i in ('node --version 2^>^&1') do set NODE_VER=%%i
echo [2/4] Node.js %NODE_VER% ✓
echo.

:: ── 后端依赖 ──
if not exist "backend\.venv" (
    echo [3/4] 正在安装后端 Python 依赖...
    echo      创建虚拟环境...
    python -m venv "backend\.venv"
    if %errorlevel% neq 0 (
        echo [×] 虚拟环境创建失败
        pause
        exit /b 1
    )
    call "backend\.venv\Scripts\activate.bat"
    
    :: 代理环境下 pip 自动使用代理
    if %PROXY_DETECTED% equ 1 (
        if not "%HTTP_PROXY%"=="" (
            echo      使用代理安装 (HTTP_PROXY)...
            pip install --proxy=%HTTP_PROXY% -r "backend\requirements.txt"
        ) else if not "%http_proxy%"=="" (
            echo      使用代理安装 (http_proxy)...
            pip install --proxy=%http_proxy% -r "backend\requirements.txt"
        ) else (
            pip install -r "backend\requirements.txt"
        )
    ) else (
        pip install -r "backend\requirements.txt"
    )
    
    if %errorlevel% neq 0 (
        echo [×] 后端依赖安装失败
        echo.
        echo     可能原因：
        echo     1. 学校网络需要代理 → 在 CMD 中先运行:
        echo        set HTTP_PROXY=http://你的代理:端口
        echo        set HTTPS_PROXY=http://你的代理:端口
        echo     2. 然后重新双击 start.bat
        echo.
        pause
        exit /b 1
    )
    echo [✓] 后端依赖安装完成
) else (
    echo [✓] 后端依赖已安装
)
echo.

:: ── 前端构建 ──
if not exist "frontend\dist" (
    if not exist "frontend\node_modules" (
        echo [4/4] 正在安装前端依赖并构建...
        cd frontend
        
        :: 代理环境下 npm 自动配置代理
        if %PROXY_DETECTED% equ 1 (
            if not "%HTTP_PROXY%"=="" (
                call npm config set proxy %HTTP_PROXY% >nul 2>&1
                call npm config set https-proxy %HTTP_PROXY% >nul 2>&1
            ) else if not "%http_proxy%"=="" (
                call npm config set proxy %http_proxy% >nul 2>&1
                call npm config set https-proxy %http_proxy% >nul 2>&1
            )
        )
        
        echo      安装 node_modules...
        call npm install 2>&1 | find /V "npm WARN" | find /V "added 1 package"
        if %errorlevel% neq 0 (
            cd ..
            echo [×] 前端依赖安装失败
            pause
            exit /b 1
        )
        cd ..
    )
    
    cd frontend
    echo      构建前端...
    call npm run build 2>&1
    if %errorlevel% neq 0 (
        cd ..
        echo [×] 前端构建失败
        pause
        exit /b 1
    )
    cd ..
    echo [✓] 前端构建完成
) else (
    echo [✓] 前端已构建
)
echo.

:: ── 启动服务 ──
echo ============================================
echo   ✓ 所有依赖就绪，正在启动服务...
echo.
echo   服务地址: http://127.0.0.1:8910
echo   本机访问: http://localhost:8910
echo ============================================
echo.

:: 延迟启动浏览器（给后端几秒初始化时间）
start /B "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8910"

:: 启动后端
call "backend\.venv\Scripts\activate.bat"
python -m backend.main

echo.
echo 服务已停止。
pause
