"""
AI Team Hub — FastAPI entry point.
Slack-style AI team collaboration platform.

v2: Team Engine + Multi-Teammate Collaboration + Memory + Tool Gateway
v2.1: Productization Layer — Public API + Auth + Observability
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.logging_setup import setup_logging
from backend.config import CORS_ORIGINS, CORS_CREDENTIALS
from backend.middleware.auth import AuthMiddleware, validate_api_key, ensure_api_key
from backend.middleware.security_headers import add_security_headers
from backend.router_registry import register_routers
from backend.static_serving import mount_frontend
from backend.startup import (
    init_encryption, migrate_legacy_keys, register_task_hooks,
    register_event_subscribers, BackgroundTaskManager,
)
from backend.services.tool_gateway import init_tool_gateway
from backend.services.model_sync import sync_models, CACHE_TTL

setup_logging()
logger = logging.getLogger("main")
task_manager = BackgroundTaskManager()


async def _periodic_model_sync(interval: int = CACHE_TTL):
    """Background task: sync models every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        try:
            await sync_models()
        except Exception as e:
            logger.warning("Periodic model sync failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_encryption()
    await migrate_legacy_keys()

    init_tool_gateway()

    # ── Team Execution Engine ──
    from backend.routes.maeos import init_maeos
    init_maeos(max_workers=4)

    register_task_hooks()
    register_event_subscribers()
    ensure_api_key()

    # ── Model auto-sync + automation poll loops ──
    task_manager.spawn(sync_models(), "startup_model_sync")
    task_manager.spawn(_periodic_model_sync(), "periodic_model_sync")
    from backend.routes.automation import automation_poll_loop
    from backend.routes.automation_v2 import automation_v2_poll_loop, reap_orphaned_runs, automation_orphan_reaper_loop
    # Reclaim runs that died with the previous process (fire-and-forget create_task).
    await reap_orphaned_runs()
    task_manager.spawn(automation_orphan_reaper_loop(interval=300), "automation_orphan_reaper")
    task_manager.spawn(automation_poll_loop(interval=30), "automation_poll")
    task_manager.spawn(automation_v2_poll_loop(interval=60), "automation_v2_poll")

    yield

    await task_manager.shutdown()
    from backend.routes.maeos import _maeos
    if _maeos:
        await _maeos.shutdown(wait=True)


app = FastAPI(
    title="AI Team Hub",
    version="2.1.0",
    description="AI Team Hub v2.1 — Team Collaboration Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(add_security_headers)
app.add_middleware(AuthMiddleware, api_key_callback=validate_api_key)

register_routers(app)
mount_frontend(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8910, reload=True)
