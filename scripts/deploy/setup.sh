#!/bin/bash
#===========================================
#  AI Team Hub — 新机部署脚本
#  在新机器上运行: bash setup.sh
#===========================================
set -e

echo "============================================"
echo "  AI Team Hub — 新机部署"
echo "============================================"
echo ""

# 1. Python 依赖
echo "[1/4] 安装 Python 依赖..."
pip3 install --break-system-packages fastapi uvicorn sqlalchemy aiosqlite httpx socksio python-multipart 2>&1 | tail -3

# 2. Node 依赖
echo "[2/4] 安装 Node 依赖..."
cd "$(dirname "$0")/frontend"
npm install 2>&1 | tail -3

# 3. 创建启动脚本快捷方式
echo "[3/4] 创建桌面快捷方式..."
cd "$(dirname "$0")"
DESKTOP="${HOME}/桌面"
if [ -d "$DESKTOP" ]; then
  cat > "$DESKTOP/AI Team Hub.desktop" << 'EOF'
[Desktop Entry]
Name=AI Team Hub
Comment=Slack-style AI team collaboration
Exec=bash -c "cd $(dirname %k)/../ && bash start.sh"
Terminal=true
Type=Application
Icon=utilities-terminal
EOF
  chmod +x "$DESKTOP/AI Team Hub.desktop"
  echo "  → $DESKTOP/AI Team Hub.desktop"
fi

# 4. 启动
echo "[4/4] 启动服务..."
bash start.sh

echo ""
echo "✅ 部署完成，打开浏览器访问:"
echo "   http://localhost:5173"
