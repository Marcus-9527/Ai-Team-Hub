"""
routes/traces.py — Trace API（可观测性端点）

提供：
- GET /api/traces — 列出最近的 traces
- GET /api/traces/{trace_id} — 获取完整 trace
- GET /api/traces/{trace_id}/replay — 回放 trace
- GET /api/traces/{trace_id}/analysis — 故障分析
- GET /api/tasks/{task_id}/state — 获取任务状态（用于恢复）
"""
from fastapi import APIRouter, HTTPException
from typing import Optional

from backend.services.observability import get_observability

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("/")
async def list_traces(limit: int = 20):
    """列出最近的 traces"""
    obs = get_observability()
    return obs.list_traces(limit=limit)


@router.get("/{trace_id}")
async def get_trace(trace_id: str):
    """获取完整 trace"""
    obs = get_observability()
    events = obs.get_trace(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {"trace_id": trace_id, "events": events}


@router.get("/{trace_id}/replay")
async def replay_trace(trace_id: str):
    """回放 trace"""
    obs = get_observability()
    result = obs.replay(trace_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{trace_id}/analysis")
async def analyze_trace(trace_id: str):
    """故障分析"""
    obs = get_observability()
    result = obs.analyze_failures(trace_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── 任务状态（用于恢复）──

@router.get("/tasks/{task_id}/state")
async def get_task_state(task_id: str):
    """获取任务状态"""
    obs = get_observability()
    state = obs.get_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task state not found")
    return state
