"""
AI Team Hub — FastAPI entry point.
Slack-style AI team collaboration platform.

v2: 状态机引擎 + DAG + 4层记忆 + Tool Gateway + Observability
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.routes import channels, teammates, apikeys, messages
from backend.cache import teammate_cache, channel_cache, apikey_cache, message_cache
from backend.services.cache_warmup_service import is_warmed_up

# v2 引擎
from backend.routes.traces import router as traces_router
from backend.routes.orchestrator import router as orchestrator_router
from backend.services.tool_gateway import init_tool_gateway


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 初始化 Tool Gateway
    init_tool_gateway()
    yield


app = FastAPI(
    title="AI Team Hub",
    version="2.0.0",
    description="AI Team Hub v2 — 状态机引擎 + DAG + 4层记忆 + Tool Gateway + Observability",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes（v1 兼容）
app.include_router(channels.router)
app.include_router(teammates.router)
app.include_router(apikeys.router)
app.include_router(messages.router)

# v2 引擎路由
app.include_router(traces_router)
app.include_router(orchestrator_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "AI Team Hub",
        "version": "2.0.0",
        "engine": "state_machine_dag",
    }


@app.get("/api/cache/stats")
async def cache_stats():
    return {
        "teammate_cache": teammate_cache.stats,
        "channel_cache": channel_cache.stats,
        "apikey_cache": apikey_cache.stats,
        "message_cache": message_cache.stats,
    }


# coordinator.py is FROZEN — endpoint removed
# Use /api/orchestrator/run instead


# Serve frontend in production
import os
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8910, reload=True)
