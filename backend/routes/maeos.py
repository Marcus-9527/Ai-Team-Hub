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
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

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
    if _maeos is not None and _maeos._started:
        return _maeos

    if _init_lock is None:
        _init_lock = asyncio.Lock()

    async with _init_lock:
        if _maeos is not None and _maeos._started:
            return _maeos

        from backend.services.maeos import MAEOS
        _maeos = MAEOS(**kwargs)
        await _maeos.start()
        return _maeos


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
    return _maeos.stats()


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
