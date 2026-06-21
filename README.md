# AI Team Hub

Slack 风格的 AI 团队协作平台，支持多模型 AI 队友、频道聊天、流式响应。

## 系统要求

- **Windows 10** 及以上
- Python 3.8+（安装时勾选 "Add Python to PATH"）
- Node.js 18+

## 快速启动（Windows）

### 一键启动

1. 确保已安装 Python 和 Node.js
2. **双击** `start.bat`

首次运行会自动：
- ✅ 检测系统代理（学校网络自动适配）
- ✅ Python 虚拟环境 + 后端依赖安装
- ✅ 前端 node_modules + 构建
- ✅ 启动后端服务
- ✅ 自动打开浏览器

### 学校代理网络

如果 `start.bat` 依赖安装失败，先设置代理再运行：

```batch
set HTTP_PROXY=http://你的代理地址:端口
set HTTPS_PROXY=http://你的代理地址:端口
start.bat
```

也可以在 Windows 系统设置 → 网络和 Internet → 代理 中配置系统全局代理。

### 手动启动

```batch
:: 后端
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m backend.main

:: 前端（可选，构建后不需要单独启动）
cd frontend
npm install
npm run build
```

## 访问

- **生产模式**: http://127.0.0.1:8910（后端直接托管前端）
- **开发模式**: http://127.0.0.1:5173（前端 dev server + API 代理）

## 功能

| 功能 | 说明 |
|------|------|
| 落地页 | 带 GSAP 动画的品牌展示页面 |
| Launch App | 进入主应用 |
| 频道 | 创建和管理聊天频道 |
| AI 队友 | 添加 GPT-4 / Claude / Gemini 等 AI 队友 |
| 聊天 | 流式 AI 响应、文件上传 |
| 设置 | 管理 API Key、模型配置 |

## 目录结构

```
ai-team-hub/
├── start.bat          # Windows 一键启动（推荐）
├── backend/           # FastAPI 后端（端口 8910）
│   ├── main.py
│   ├── requirements.txt
│   ├── database.py
│   ├── models.py
│   ├── routes/        # API 路由
│   └── services/      # AI 服务
├── frontend/          # React + Vite 前端
│   ├── dist/          # 构建产物
│   ├── src/           # 源码
│   └── package.json
├── data/              # 数据库（自动创建）
├── setup.bat          # 仅安装依赖，不启动
└── README.md
```

## 常见问题

### 端口 8910 被占用

1. 关闭占用该端口的程序
2. 或修改 `backend/main.py` 中的端口号，然后重新启动

### 依赖安装失败（网络问题）

```batch
set HTTP_PROXY=http://你的代理:端口
set HTTPS_PROXY=http://你的代理:端口
start.bat
```

### pip 报 `externally-managed-environment`

`start.bat` 使用虚拟环境部署，不会触发此错误。如果手动安装遇到此问题，请使用虚拟环境或 `--break-system-packages`。

### npm 构建报错

```batch
cd frontend
rmdir /s /q node_modules
npm install
npm run build
```

## 技术栈

- **后端**: FastAPI + SQLAlchemy + SQLite + aiosqlite
- **前端**: React 18 + Vite + Tailwind CSS + GSAP + Framer Motion
- **API**: RESTful + Server-Sent Events（SSE 流式响应）
