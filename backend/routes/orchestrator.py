"""
routes/orchestrator.py — Orchestrator API (FSM v3)

Provides:
  POST /api/orchestrator/run — Execute task via FSM
  GET  /api/orchestrator/state — Get current state
  GET  /api/orchestrator/trace/{trace_id} — Get trace report

Replaces conversational orchestration with deterministic FSM.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.services.orchestrator_fsm import create_fsm_orchestrator, FSMOrchestrator
from backend.services.observability import get_observability

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


class RunRequest(BaseModel):
    task: str
    intent: Optional[str] = None
    provider: Optional[str] = "deepseek"
    model: Optional[str] = "deepseek-chat"
    adaptive: Optional[bool] = True        # v5: enable adaptive orchestration
    force_mode: Optional[str] = None       # v5: force SIMPLE/STANDARD/COMPLEX


# ── Active orchestrator instance (for state inspection) ──
_active_orchestrator: Optional[FSMOrchestrator] = None


@router.post("/run")
async def run_task(req: RunRequest):
    """
    Execute task through adaptive FSM.

    v5 Flow: INIT → CLASSIFY → Mode Router → Execution Pipeline → DONE
    Modes: SIMPLE (executor) | STANDARD (executor+validation) | COMPLEX (full FSM)
    """
    api_key = await _get_api_key(req.provider)
    if not api_key:
        raise HTTPException(status_code=400, detail=f"No API key for provider: {req.provider}")

    global _active_orchestrator

    # Create fresh FSM orchestrator (no singleton — each run is independent)
    orch = create_fsm_orchestrator(
        provider=req.provider,
        model=req.model,
        api_key=api_key,
        max_retries=3,
        adaptive=req.adaptive,
        force_mode=req.force_mode,
    )
    _active_orchestrator = orch

    # Execute FSM
    ctx = await orch.run(req.task, intent=req.intent)

    # Save trace
    obs = get_observability()
    trace_report = orch.get_trace_report()
    for event in trace_report.get("events", []):
        obs.record(
            trace_id=orch.trace_id,
            task_id=ctx.task_id,
            step=event.get("step", ""),
            agent=event.get("agent", ""),
            input_data=event.get("input_data", {}),
            output_data=event.get("output_data", {}),
            latency_ms=event.get("latency_ms", 0),
        )

    obs.save_state(
        task_id=ctx.task_id,
        trace_id=orch.trace_id,
        state=ctx.state,
        context=ctx.to_dict(),
    )

    return {
        "task_id": ctx.task_id,
        "trace_id": orch.trace_id,
        "state": ctx.state,
        "intent": ctx.intent,
        "plan": ctx.plan,
        "execution_result": ctx.execution_result,
        "review_result": ctx.review_result,
        "final_result": ctx.final_result,
        "retry_count": ctx.retry_count,
        "trace_report": trace_report,
    }


@router.get("/state")
async def get_state():
    """Get current FSM state."""
    if _active_orchestrator is None:
        return {"state": "idle"}
    return {
        "state": _active_orchestrator.state.value,
        "trace_id": _active_orchestrator.trace_id,
        "trace_length": len(_active_orchestrator.trace),
    }


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str):
    """Get trace report."""
    obs = get_observability()
    result = obs.replay(trace_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


async def _get_api_key(provider: str) -> str:
    """Fetch API key from database."""
    try:
        from backend.database import async_session
        from sqlalchemy import select
        from backend.models import APIKey
        async with async_session() as sess:
            result = await sess.execute(
                select(APIKey).where(APIKey.provider == provider).limit(1)
            )
            key_obj = result.scalar_one_or_none()
            if key_obj and key_obj.api_key:
                return key_obj.api_key
    except Exception:
        pass
    return ""
