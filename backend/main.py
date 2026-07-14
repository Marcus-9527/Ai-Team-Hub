"""
AI Team Hub — FastAPI entry point.
Slack-style AI team collaboration platform.

v2: Team Engine + Multi-Teammate Collaboration + Memory + Tool Gateway
v2.1: Productization Layer — Public API + Auth + Observability
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select

from backend.routes.brain import router as brain_router
from backend.routes.autonomous import router as autonomous_router


class APIKeyFilter(logging.Filter):
    """Filter out any log message containing potential API key patterns."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        # Block common API key patterns in logs
        blocked_patterns = [
            "sk-", "cfut_", "api_key", "apikey", "Bearer ",
            "x-api-key", "Authorization",
        ]
        return not any(p in msg.lower() for p in blocked_patterns)


for logger_name in ("ai_service", "team_collaboration", "apikeys", "key_vault_service", "security.crypto"):
    logging.getLogger(logger_name).addFilter(APIKeyFilter())

from backend.database import init_db
from backend.routes import channels, teammates, apikeys, messages, models
from backend.security.crypto import validate_key, get_encryption_key_info, ENCRYPTION_KEY_ENV
from backend.services.model_sync import (
    sync_models,
    get_cached_models,
    get_cached_models_with_meta,
    CACHE_TTL,
)
from backend.cache import teammate_cache, channel_cache, apikey_cache, message_cache
from backend.services.cache_warmup_service import is_warmed_up
from backend.services.key_vault_service import list_keys
from backend.services.migration import migrate_plaintext_keys

# v2 引擎 — legacy orchestrator route removed; Worker is the sole orchestration runtime

# v2.1 Public API Layer
from backend.routes.v1 import router as v1_router
from backend.middleware.auth import AuthMiddleware, validate_api_key

# teammate_files (internal route name: agent_rag)
from backend.routes.files import router as files_router
from backend.routes.query import router as query_router
from backend.routes.team_files import router as team_files_router
from backend.services.tool_gateway import init_tool_gateway

# ── Previously-unregistered routers (observability / management endpoints) ──
# These were implemented but missed include_router; wired up here to restore
# SDK/UI reachability. No existing route behavior is changed.
from backend.routes.v1_observability import router as v1_observability_router
from backend.routes.semantic_cache import router as semantic_cache_router
from backend.routes.traces import router as traces_router
from backend.routes.executions import router as executions_router
from backend.routes.artifacts import router as artifacts_router
from backend.routes.dags import router as dags_router
from backend.routes.approvals import router as approvals_router
from backend.routes.dashboard import router as dashboard_router
from backend.routes.policy import router as policy_router
from backend.routes.brain import router as brain_router
from backend.routes.automation import router as automation_router, automation_poll_loop
from backend.routes.demo import router as demo_router
from backend.routes.teams import router as teams_router

logger = logging.getLogger("main")

_sync_task: asyncio.Task | None = None
_automation_task: asyncio.Task | None = None


async def _periodic_model_sync(interval: int = CACHE_TTL):
    """Background task: sync models every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        try:
            logger.info("Periodic model sync starting...")
            await sync_models()
        except Exception as e:
            logger.warning("Periodic model sync failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sync_task
    await init_db()

    # ── Encryption key validation ──
    key_info = get_encryption_key_info()
    logger.info("Encryption key source: %s", key_info["source"])
    try:
        validate_key()
    except RuntimeError as e:
        logger.error("Encryption key validation FAILED: %s", e)
        raise

    # ── Migrate any existing plaintext keys ──
    try:
        migrated = await migrate_plaintext_keys()
        if migrated > 0:
            logger.info("Migrated %d plaintext API keys to encrypted storage", migrated)
    except Exception as e:
        logger.warning("Plaintext key migration failed (non-fatal): %s", e)

    # 初始化 Tool Gateway
    init_tool_gateway()
    # ── Team Execution Engine ──
    from backend.routes.maeos import init_maeos
    init_maeos(max_workers=4)

    # ── V3.1 Phase A: Memory Lifecycle Hook ──
    from backend.services.memory.memory_event_handler import MemoryTaskHook
    from backend.services.task.task_hooks import get_task_hook_registry
    registry = get_task_hook_registry()
    registry.register(MemoryTaskHook())
    logger.info("MemoryTaskHook registered — task lifecycle → memory pipeline active")

    # ── Phase 12: Brain Task Hook (reflection) ──
    from backend.services.brain.task_hook import BrainTaskHook
    registry.register(BrainTaskHook())
    logger.info("BrainTaskHook registered — task lifecycle → brain reflection active")

    # ── Phase 20: Channel Notify Hook (auto-publish results to channel) ──
    from backend.services.brain.channel_notify_hook import ChannelNotifyHook
    registry.register(ChannelNotifyHook())
    logger.info("ChannelNotifyHook registered — task results → channel messages")

    # ── API key gate (locks /api + /v1 unless AI_TEAM_HUB_API_KEY is set) ──
    from backend.middleware.auth import ensure_api_key
    ensure_api_key()

    # ── Model auto-sync ──
    # Always sync on startup when online (non-blocking)
    try:
        asyncio.create_task(sync_models())
        logger.info("Startup model sync triggered")
    except Exception as e:
        logger.warning("Startup model sync error: %s", e)

    # Periodic background refresh
    _sync_task = asyncio.create_task(_periodic_model_sync())
    logger.info("Periodic model sync scheduled every %ds", CACHE_TTL)

    # ── Phase 7: Automation poll loop ──
    _automation_task = asyncio.create_task(automation_poll_loop(interval=30))
    logger.info("Automation poll loop started (30s interval)")

    yield

    # Shutdown
    if _sync_task:
        _sync_task.cancel()
        try:
            await _sync_task
        except asyncio.CancelledError:
            pass
    if _automation_task:
        _automation_task.cancel()
        try:
            await _automation_task
        except asyncio.CancelledError:
            pass
    from backend.routes.maeos import _maeos
    if _maeos:
        await _maeos.shutdown(wait=True)


app = FastAPI(
    title="AI Team Hub",
    version="2.1.0",
    description="AI Team Hub v2.1 — Team Collaboration Platform",
    lifespan=lifespan,
)

# CORS — origins are configurable via CORS_ORIGINS (comma-separated).
# IMPORTANT: wildcard "*" is incompatible with allow_credentials=True; when
# credentials are used we must echo a concrete origin. When CORS_ORIGINS is
# omitted we default to open dev mode but drop credentials to stay RFC-compliant.
import os as _os

_cors_raw = _os.environ.get("CORS_ORIGINS", "")
if _cors_raw.strip():
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    _cors_credentials = True
else:
    # Open dev mode: allow any origin but WITHOUT credentials (valid combination)
    _cors_origins = ["*"]
    _cors_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# P3 #6 (short-term mitigation): lock down script sources so a same-origin XSS
# can't pull an external script to exfiltrate the API key from localStorage.
# 'unsafe-eval' removed (no eval in the app bundle). 'unsafe-inline' retained
# because legacy/SPA routes rely on inline scripts — dropping it whitescreens
# the app; move inline → external files + nonce before removing it.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp

# Auth middleware (protects /v1/* routes)
app.add_middleware(AuthMiddleware, api_key_callback=validate_api_key)

# API Routes（legacy — no auth required）
app.include_router(channels.router)
app.include_router(teammates.router)
app.include_router(apikeys.router)
app.include_router(messages.router)

# v2 引擎路由 — legacy routes removed; Worker is the sole orchestration runtime


# v2.1 Public API Layer (with auth)
app.include_router(v1_router)

# Model listing & sync (no auth — used by frontend)
app.include_router(models.router)

# teammate_files route (internal name: agent_rag)
app.include_router(files_router)

# v2.5 Task Execution Layer
from backend.routes.tasks import router as tasks_router
app.include_router(tasks_router)
app.include_router(query_router)
app.include_router(team_files_router)

# ── Observability / management routers (restored registration) ──
app.include_router(v1_observability_router)   # /v1/timeline, /v1/cost, /v1/cache/vis, /v1/team/interactions, /v1/system/summary
app.include_router(semantic_cache_router)     # /api/semantic-cache/*
app.include_router(traces_router)             # /api/traces/*
app.include_router(executions_router)         # /api/executions/*
app.include_router(artifacts_router)          # /api/artifacts/*
from backend.routes.evaluations import router as evaluations_router
app.include_router(evaluations_router)        # /api/evaluations/*
app.include_router(dags_router)               # /api/dags/*
app.include_router(approvals_router)           # /api/approvals/*
app.include_router(dashboard_router)            # /api/dashboard
app.include_router(policy_router)               # /api/policy
app.include_router(brain_router)

# Phase 13 — Autonomous Collaboration
app.include_router(autonomous_router)                 # /api/brain
app.include_router(automation_router)             # /api/automation
app.include_router(demo_router)
app.include_router(teams_router)                    # /api/demo


@app.get("/api/health")
async def health():
    return {"status": "ok"}


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
    # SPA 入口 HTML 不缓存（否则 CF 边缘会把旧构建的 index.html 钉住）；
    # /assets/* 带内容 hash，可安全长缓存。
    @app.middleware("http")
    async def _no_cache_html(request: Request, call_next):
        resp = await call_next(request)
        ct = resp.headers.get("content-type", "")
        if ct.startswith("text/html"):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8910, reload=True)
