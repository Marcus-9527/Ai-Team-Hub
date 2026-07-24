"""
routes/maeos.py — Team Engine API

Provides:
  POST /api/maeos/submit        — Submit task to Team Engine
  GET  /api/maeos/status/{id}    — Get task status
  GET  /api/maeos/debug/{id}     — Get full debug info
  GET  /api/maeos/tasks           — List all tasks
  GET  /api/maeos/stats           — System statistics
  GET  /api/maeos/memory/stats    — Memory layer statistics
  GET  /api/maeos/wait/{id}       — Block until task completes

Injects ExecutionRuntime via Depends() instead of a MAEOS wrapper class.
"""
import asyncio
import logging
import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from backend.services.runtime.executor import ExecutionRuntime, TaskPriority, ExecStatus

logger = logging.getLogger("maeos")

router = APIRouter(prefix="/api/maeos", tags=["maeos"])


class SubmitRequest(BaseModel):
    task: str
    priority: int = 2               # 0=CRITICAL 1=HIGH 2=NORMAL 3=LOW 4=BACKGROUND
    intent: Optional[str] = None
    provider: Optional[str] = "openrouter"
    model: Optional[str] = "openrouter/auto"


# ── Singleton + Dependency ──

_runtime: Optional[ExecutionRuntime] = None
_init_lock: Optional[asyncio.Lock] = None


def get_runtime() -> ExecutionRuntime:
    """FastAPI Depends() target — returns the singleton ExecutionRuntime."""
    global _runtime
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Team Engine not initialized")
    return _runtime


async def _ensure_key_loaded() -> None:
    """Auto-load API key from DB on first use if not already set."""
    global _runtime
    if _runtime is None:
        return
    if _runtime.default_api_key:
        return
    kwargs = {}
    try:
        await _apply_db_key_to_kwargs(kwargs)
        if kwargs.get("api_key"):
            _runtime.default_api_key = kwargs["api_key"]
            _runtime.default_provider = kwargs.get("provider", _runtime.default_provider)
            if kwargs.get("base_url"):
                _runtime.default_base_url = kwargs["base_url"]
    except (ValueError, Exception) as e:
        logger.warning("[MAEOS] no legacy global key available: %s", e)


@router.post("/submit")
async def submit_task(req: SubmitRequest, runtime: ExecutionRuntime = Depends(get_runtime)):
    """Submit a task to Team Engine."""
    await _ensure_key_loaded()
    task_id = await runtime.submit(
        description=req.task,
        priority=req.priority,
        intent=req.intent or "",
        provider=req.provider,
        model=req.model,
        wait=False,
    )
    return {"task_id": task_id, "status": "submitted"}


def _map_status(status: str) -> str:
    mapping = {
        ExecStatus.PENDING: "PENDING",
        ExecStatus.RUNNING: "RUNNING",
        ExecStatus.COMPLETED: "COMPLETED",
        ExecStatus.FAILED: "FAILED",
        ExecStatus.ABORTED: "ABORTED",
    }
    return mapping.get(status, status)


@router.get("/status/{task_id}")
async def get_status(task_id: str, runtime: ExecutionRuntime = Depends(get_runtime)):
    """Get task status."""
    status = runtime.get_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    status["status"] = _map_status(status.get("status", "UNKNOWN"))
    return status


@router.get("/debug/{task_id}")
async def debug_task(task_id: str, runtime: ExecutionRuntime = Depends(get_runtime)):
    """Get full debug info for a task."""
    status = runtime.get_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found in memory")
    return {"task_id": task_id, **status, "_runtime_v1": True}



@router.get("/stats")
async def system_stats(runtime: ExecutionRuntime = Depends(get_runtime)):
    """Get full system statistics."""
    base = await runtime.stats()
    return {**base, "status": "running"}


@router.get("/memory/stats")
async def memory_stats():
    """Get memory layer statistics."""
    return {"total_entries": 0, "max_entries": 1000}


@router.get("/wait/{task_id}")
async def wait_task(task_id: str, timeout: float = 300.0, runtime: ExecutionRuntime = Depends(get_runtime)):
    """Wait for a task to complete and return result."""
    rt = await runtime.wait(task_id, timeout=timeout)
    if rt is None:
        raise HTTPException(status_code=404, detail="Task not found or timeout")
    return {
        "id": rt.id,
        "description": rt.description[:200],
        "priority": rt.priority,
        "status": _map_status(rt.status),
        "result_length": len(rt.result),
        "error": rt.error[:200] if rt.error else "",
        "created_at": rt.created_at,
        "completed_at": rt.completed_at,
    }


# ── Startup init ──

def init_runtime(max_workers: int = 4, provider: str = "openrouter",
                 model: str = "openrouter/auto", api_key: str = "", base_url: str = None):
    """Initialize Team Engine runtime at startup (call from main.py)."""
    global _runtime
    _runtime = ExecutionRuntime(
        max_workers=max_workers,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    asyncio.create_task(_runtime.start())
    return _runtime


# ── DB key resolution (kept for backward compat / test imports) ──

async def _apply_db_key_to_kwargs(kwargs: dict, workspace_id: str = None) -> None:
    """Mutate kwargs in-place with the active DB key for the given workspace.

    Delegates to OrganizationRuntime.resolve_workspace_api_key() for the single
    truth of workspace-scoped key resolution.
    """
    from backend.services.organization.runtime import resolve_workspace_api_key
    resolved = await resolve_workspace_api_key(workspace_id)
    if resolved:
        api_key, base_url, provider = resolved
        kwargs.setdefault("provider", provider)
        kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        logger.info("[MAEOS] auto-loaded API key from DB (ws=%s)", workspace_id or "legacy-global")
        return
    scope = workspace_id or "legacy-global"
    raise ValueError(
        f"No active API key found for scope '{scope}'. "
        f"Add an API key to this workspace (or a legacy global key) "
        f"before running automation jobs."
    )
