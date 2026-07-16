"""
routes/maeos.py — Team Engine API

Provides:
  POST /api/maeos/submit        — Submit task to Team Engine
  GET  /api/maeos/status/{id}    — Get task status
  GET  /api/maeos/debug/{id}     — Get full debug info (trace, diversity, outputs)
  GET  /api/maeos/tasks           — List all tasks
  GET  /api/maeos/stats           — System statistics
  GET  /api/maeos/memory/stats    — Memory layer statistics
  GET  /api/maeos/wait/{id}       — Block until task completes
"""

import asyncio
import logging
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("maeos")

router = APIRouter(prefix="/api/maeos", tags=["maeos"])


class SubmitRequest(BaseModel):
    task: str
    priority: int = 2               # 0=CRITICAL 1=HIGH 2=NORMAL 3=LOW 4=BACKGROUND
    intent: Optional[str] = None
    provider: Optional[str] = "openrouter"
    model: Optional[str] = "openrouter/auto"


# ── Singleton Team Engine instance (lives as long as backend process) ──
_maeos: Optional["MAEOS"] = None
_init_lock: Optional[asyncio.Lock] = None


async def _get_maeos(**kwargs):
    """Get or initialize Team Engine singleton (async-safe)."""
    global _maeos, _init_lock
    # If MAEOS was already started but has no api_key, upgrade it
    # (happens when init_maeos(max_workers=4) was called without a key).
    if _maeos is not None and _maeos._started:
        if not _maeos._runtime.default_api_key and not kwargs.get("api_key"):
            await _upgrade_maeos_key(_maeos)
        return _maeos

    if _init_lock is None:
        _init_lock = asyncio.Lock()

    async with _init_lock:
        if _maeos is not None and _maeos._started:
            return _maeos

        from backend.services.maeos import MAEOS
        # ponytail: when no api_key was configured, try to load the first
        # legacy (workspace-less) DB key so planning tasks don't fail.
        # Isolation is preserved: _apply_db_key_to_kwargs only ever scopes to
        # a legacy NULL workspace — it never borrows another workspace's key.
        # If no legacy key exists, degrade to "no key" instead of failing:
        # the caller (e.g. PlanningEngine) supplies its own workspace key.
        if not kwargs.get("api_key") and not os.environ.get("AI_TEAM_HUB_API_KEY"):
            try:
                await _apply_db_key_to_kwargs(kwargs)
            except ValueError as e:
                logger.warning("[MAEOS] no legacy global key available: %s", e)
        _maeos = MAEOS(**kwargs)
        await _maeos.start()
        return _maeos


async def _apply_db_key_to_kwargs(kwargs: dict, workspace_id: str = None) -> None:
    """Mutate kwargs in-place with the active DB key for the given workspace.

    Scoping rule (workspace isolation, no silent cross-borrow):
      - workspace_id given  → only that workspace's key is eligible.
      - workspace_id None   → ONLY legacy keys with empty workspace_id.
                              Never borrows another workspace's key.
    Raises ValueError if no eligible key exists, so a missing key fails loud
    instead of letting MAEOS run with a borrowed/foreign key.
    """
    try:
        from backend.database import async_session
        from backend.models import APIKey
        from sqlalchemy import select
        from backend.crypto import decrypt_value
        async with async_session() as sess:
            q = select(APIKey).where(APIKey.is_active == "1")
            if workspace_id:
                q = q.where(APIKey.workspace_id == workspace_id)
            else:
                # ponytail: legacy-only scope — an empty workspace_id means
                # "global/admin key", NOT "any workspace's key".
                q = q.where(APIKey.workspace_id.is_(None))
            row = (await sess.execute(q.limit(1))).scalar_one_or_none()
            if row:
                plain = decrypt_value(row.api_key)
                if plain:
                    kwargs.setdefault("provider", row.provider)
                    kwargs["api_key"] = plain
                    if row.base_url:
                        kwargs["base_url"] = row.base_url
                    logger.info("[MAEOS] auto-loaded API key from DB: %s (ws=%s)", row.id[:8], workspace_id or "legacy-global")
                    return
            # No eligible key — fail loud, never borrow another workspace's key.
            scope = workspace_id or "legacy-global"
            raise ValueError(
                f"No active API key found for scope '{scope}'. "
                f"Add an API key to this workspace (or a legacy global key) "
                f"before running automation jobs."
            )
    except ValueError:
        raise
    except Exception as e:
        logger.warning("[MAEOS] failed to auto-load API key: %s", e)


async def _upgrade_maeos_key(maeos) -> None:
    """Populate an existing MAEOS instance's default key from DB."""
    from backend.services.runtime.executor import ExecutionRuntime
    kwargs = {}
    await _apply_db_key_to_kwargs(kwargs)
    if kwargs.get("api_key"):
        maeos._runtime.default_api_key = kwargs["api_key"]
        maeos._runtime.default_provider = kwargs.get("provider", maeos._runtime.default_provider)
        if kwargs.get("base_url"):
            maeos._runtime.default_base_url = kwargs["base_url"]
        logger.info("[MAEOS] upgraded existing MAEOS with DB key")


async def _resolve_workspace_key(workspace_id: str) -> dict:
    """Resolve API key+provider+base_url for a specific workspace.

    Returns dict with keys: api_key, provider, base_url.
    Raises ValueError if workspace has no active key — no silent cross-workspace borrowing.
    """
    kwargs = {}
    await _apply_db_key_to_kwargs(kwargs, workspace_id)
    if not kwargs.get("api_key"):
        raise ValueError(
            f"Workspace {workspace_id[:12]}... has no active API key configured. "
            "Please add an API key to this workspace before running automation jobs."
        )
    return kwargs


def init_maeos(max_workers: int = 4, provider: str = "openrouter",
               model: str = "openrouter/auto", api_key: str = "", base_url: str = None):
    """Initialize Team Engine at startup (call from main.py startup hook)."""
    global _maeos
    from backend.services.maeos import MAEOS as _MAEOS
    _maeos = _MAEOS(
        max_workers=max_workers,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    asyncio.create_task(_maeos.start())
    return _maeos


@router.post("/submit")
async def submit_task(req: SubmitRequest):
    """Submit a task to Team Engine."""
    try:
        maeos = await _get_maeos()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Team Engine init failed: {e}")

    task_id = await maeos.submit(
        description=req.task,
        priority=req.priority,
        intent=req.intent or "",
        provider=req.provider,
        model=req.model,
        wait=False,
    )

    return {"task_id": task_id, "status": "submitted"}


@router.get("/status/{task_id}")
async def get_status(task_id: str):
    """Get task status."""
    global _maeos
    if _maeos is None:
        raise HTTPException(status_code=503, detail="Team Engine not initialized")
    status = _maeos.get_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@router.get("/debug/{task_id}")
async def debug_task(task_id: str):
    """Get full debug info for a task."""
    global _maeos
    if _maeos is None:
        raise HTTPException(status_code=503, detail="Team Engine not initialized")
    debug = _maeos.debug_task(task_id)
    if not debug:
        raise HTTPException(status_code=404, detail="Task not found in memory")
    return debug


@router.get("/tasks")
async def list_tasks(status: str = None):
    """List all tasks, optionally filtered by status."""
    global _maeos
    if _maeos is None:
        raise HTTPException(status_code=503, detail="Team Engine not initialized")
    return _maeos.list_tasks(status=status)


@router.get("/stats")
async def system_stats():
    """Get full system statistics."""
    global _maeos
    if _maeos is None:
        raise HTTPException(status_code=503, detail="Team Engine not initialized")
    return await _maeos.stats()


@router.get("/memory/stats")
async def memory_stats():
    """Get memory layer statistics."""
    global _maeos
    if _maeos is None:
        raise HTTPException(status_code=503, detail="Team Engine not initialized")
    return _maeos.memory.stats()


@router.get("/wait/{task_id}")
async def wait_task(task_id: str, timeout: float = 300.0):
    """Wait for a task to complete and return result."""
    maeos = await _get_maeos()
    task = await maeos.wait(task_id, timeout=timeout)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or timeout")
    return task.to_dict()
