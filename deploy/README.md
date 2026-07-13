# AI Team Hub — Self-hosted Deployment Guide

## Quick Start (Docker)

```bash
cd deploy
cp .env.example .env
# Edit .env — add your Fernet encryption key:
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste the output as AI_TEAM_HUB_CRYPTO_KEY in .env

docker compose up -d --build
```

Wait ~30s for startup, then visit **http://localhost:8910**

## Configuration

All config via environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AI_TEAM_HUB_CRYPTO_KEY` | **Yes** | — | Fernet key for encrypting API keys |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///data/aiteamhub.db` | SQLite (dev) or PostgreSQL (prod) |
| `CORS_ORIGINS` | No | `*` (open) | Comma-separated allowed origins |
| `AI_TEAM_HUB_ADMIN_KEY` | No | — | Admin key for sensitive endpoints |
| `LOG_LEVEL` | No | `info` | Python log level |
| `PORT` | No | `8910` | HTTP port |

## Production Checklist

1. **Set `AI_TEAM_HUB_CRYPTO_KEY`** — required for API key encryption
2. **Set `CORS_ORIGINS`** — restrict to your frontend domain
3. **Set `AI_TEAM_HUB_ADMIN_KEY`** — protect management endpoints
4. **Use PostgreSQL** for multi-user: `DATABASE_URL=postgresql+asyncpg://user:pass@host/db`
5. **Run behind reverse proxy** (nginx/caddy) for TLS termination
6. **Remove `--reload`** from CMD in production (already done in Dockerfile)

## Persistent Data

Data is stored in the `aiteamhub_data` Docker volume at `/app/data/`:
- `aiteamhub.db` — SQLite database (tasks, teammates, memory, executions)
- `.crypto_key` — auto-generated Fernet key (if env var not set)

## Manual Start (no Docker)

```bash
# Backend
cd /path/to/ai-team-hub
python3 -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8910

# Frontend (dev mode)
cd frontend
npm install
npm run dev
```
