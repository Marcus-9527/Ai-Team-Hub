"""
AI Team Hub — FastAPI entry point.
Slack-style AI team collaboration platform.

v2: 状态机引擎 + DAG + 4层记忆 + Tool Gateway + Observability
v2.1: Productization Layer — Public API + Auth + Observability
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.routes import channels, teammates, apikeys, messages
from backend.routes.semantic_cache import router as semantic_cache_router
from backend.cache import teammate_cache, channel_cache, apikey_cache, message_cache
from backend.services.kernel.cache_kernel import is_warmed_up

# v2 引擎
from backend.routes.traces import router as traces_router
from backend.routes.orchestrator import router as orchestrator_router
from backend.routes.maeos import router as maeos_router
from backend.routes.workspace import router as workspace_router
from backend.services.orchestrator_core import init_tool_gateway

# v2.1 Public API Layer
from backend.routes.v1 import router as v1_router
from backend.routes.v1_observability import router as v1_obs_router
from backend.middleware.auth import AuthMiddleware, validate_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 初始化 Tool Gateway
    init_tool_gateway()
    # 初始化 MAEOS Execution OS
    from backend.routes.maeos import init_maeos
    init_maeos(max_workers=4)
    yield
    # Shutdown MAEOS
    from backend.routes.maeos import _maeos
    if _maeos:
        await _maeos.shutdown(wait=True)


app = FastAPI(
    title="AI Team Hub",
    version="2.1.0",
    description="AI Team Hub v2.1 — Public API + State Machine Engine + Multi-Agent OS",
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

# Auth middleware (protects /v1/* routes)
app.add_middleware(AuthMiddleware, api_key_callback=validate_api_key)

# API Routes（legacy — no auth required）
app.include_router(channels.router)
app.include_router(teammates.router)
app.include_router(apikeys.router)
app.include_router(messages.router)

# v2 引擎路由
app.include_router(traces_router)
app.include_router(orchestrator_router)
app.include_router(maeos_router)
app.include_router(workspace_router)

# 语义缓存路由
app.include_router(semantic_cache_router)

# v2.1 Public API Layer (with auth)
app.include_router(v1_router)
app.include_router(v1_obs_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "AI Team Hub",
        "version": "2.1.0",
        "engine": "state_machine_dag",
    }


@app.get("/api/cache/stats")
async def cache_stats():
    from backend.services.kernel.cache_kernel import (
        get_multi_layer_cache, get_embedding_cache, get_prompt_deduplicator,
    )

    mlc = get_multi_layer_cache()
    emb = get_embedding_cache()
    dedup = get_prompt_deduplicator()

    return {
        "teammate_cache": teammate_cache.stats,
        "channel_cache": channel_cache.stats,
        "apikey_cache": apikey_cache.stats,
        "message_cache": message_cache.stats,
        "semantic_cache": {
            "multi_layer": mlc.stats,
            "embedding": emb.stats,
            "prompt_dedup": dedup.stats,
        },
    }


# Serve frontend in production
import os
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8910, reload=True)
