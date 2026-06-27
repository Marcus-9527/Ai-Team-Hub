"""
routes/v1.py — Public API Layer (Productization)

Unified external API with standardized response schema.
Hides internal FSM/Kernel/Agent complexity.

Endpoints:
  POST /v1/task/run          — Execute a task
  POST /v1/workspace/create   — Create workspace
  GET  /v1/task/status        — Get task status
  GET  /v1/task/trace         — Get task trace
  POST /v1/agent/chat         — Simplified agent chat
  GET  /v1/health             — Health check
  GET  /v1/system/modes       — Available modes

Modes:
  auto   — Full FSM + agents + cache (default)
  control — User specifies agent behavior
  debug  — Full trace, FSM states, logs visible
"""
import time
import uuid
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List

router = APIRouter(prefix="/v1", tags=["v1-public"])


# ═══════════════════════════════════════════════════════════
# Unified Response Schema (Phase 4)
# ═══════════════════════════════════════════════════════════

class TaskResponse(BaseModel):
    """Unified task response — ALL endpoints return this shape."""
    task_id: str = ""
    status: str = ""
    result: str = ""
    trace_id: str = ""
    cost: str = "0"
    latency: str = "0ms"
    message: str = ""


class WorkspaceResponse(BaseModel):
    workspace_id: str = ""
    status: str = ""
    title: str = ""
    created_at: str = ""
    message: str = ""


class TraceResponse(BaseModel):
    trace_id: str = ""
    task_id: str = ""
    status: str = ""
    steps: List[Dict[str, Any]] = []
    fsm_transitions: List[Dict[str, str]] = []
    agent_calls: List[Dict[str, Any]] = []
    cache_hits: int = 0
    total_cost: str = "0"
    total_latency: str = "0ms"
    message: str = ""


class ChatResponse(BaseModel):
    session_id: str = ""
    status: str = ""
    response: str = ""
    agent_used: str = ""
    latency: str = "0ms"
    message: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "AI Team Hub"
    version: str = "2.0.0"
    modes_available: List[str] = ["auto", "control", "debug"]
    latency: str = "0ms"


# ═══════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════

class TaskRunRequest(BaseModel):
    task: str = Field(..., description="Task description or instruction")
    mode: Optional[str] = Field("auto", description="auto | control | debug")
    provider: Optional[str] = "openrouter"
    model: Optional[str] = "openrouter/owl-alpha"
    workspace_id: Optional[str] = None
    # Control mode: override agent behavior
    agent_config: Optional[Dict[str, Any]] = Field(None, description="Control mode: agent overrides")
    # Max budget in USD
    budget: Optional[float] = Field(0.5, description="Max cost in USD")
    # Timeout in seconds
    timeout: Optional[int] = Field(120, description="Timeout seconds")

    class Config:
        json_schema_extra = {
            "example": {
                "task": "Analyze the market for AI code editors",
                "mode": "auto",
                "provider": "openrouter",
                "model": "openrouter/owl-alpha",
                "budget": 0.5,
                "timeout": 120
            }
        }


class WorkspaceCreateRequest(BaseModel):
    title: str = Field(..., description="Workspace title")
    description: Optional[str] = ""

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Data Analysis Project",
                "description": "Team workspace for analyzing Q3 data"
            }
        }


class AgentChatRequest(BaseModel):
    message: str = Field(..., description="Message to agent")
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    mode: Optional[str] = "auto"

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Summarize our current progress",
                "mode": "auto"
            }
        }


# ═══════════════════════════════════════════════════════════
# Response Helpers
# ═══════════════════════════════════════════════════════════

def _success(task_id="", status="ok", result="", trace_id="", cost="0", latency_ms=0, message="OK") -> TaskResponse:
    return TaskResponse(
        task_id=task_id,
        status=status,
        result=result,
        trace_id=trace_id,
        cost=f"${cost}",
        latency=f"{latency_ms}ms",
        message=message,
    )


def _error(message: str, latency_ms=0) -> TaskResponse:
    return TaskResponse(
        status="error",
        message=message,
        latency=f"{latency_ms}ms",
    )


# ═══════════════════════════════════════════════════════════
# Endpoints (Phase 1 + Phase 3: System Modes)
# ═══════════════════════════════════════════════════════════

@router.post("/task/run", response_model=TaskResponse)
async def v1_task_run(req: TaskRunRequest, request: Request):
    """
    Execute a task through the AI Runtime.

    - **auto** (default): Full FSM + agents + cache pipeline
    - **control**: Specify agent_config to override behavior
    - **debug**: Returns full trace, FSM states, and internal logs
    """
    start = time.time()
    task_id = str(uuid.uuid4())[:8]

    try:
        # Route to appropriate mode handler
        if req.mode == "debug":
            return await _run_debug(req, task_id, start)
        elif req.mode == "control" and req.agent_config:
            return await _run_control(req, task_id, start)
        else:
            return await _run_auto(req, task_id, start)
    except HTTPException:
        raise
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return _error(f"Internal error: {str(e)}", elapsed)


@router.post("/workspace/create", response_model=WorkspaceResponse)
async def v1_workspace_create(req: WorkspaceCreateRequest, request: Request):
    """Create a new workspace for task execution."""
    from backend.services.workspace import get_workspace_manager
    start = time.time()

    mgr = get_workspace_manager()
    ws = await mgr.create_workspace(title=req.title, description=req.description)

    elapsed = round((time.time() - start) * 1000)
    return WorkspaceResponse(
        workspace_id=ws.id,
        status="created",
        title=ws.title,
        created_at=str(ws.created_at),
        latency=f"{elapsed}ms",
    )


@router.get("/task/{task_id}/status", response_model=TaskResponse)
async def v1_task_status(task_id: str, request: Request):
    """Get current task status and result if complete."""
    from backend.services.orchestrator_core import get_observability
    start = time.time()

    obs = get_observability()
    # Check in-memory state from observability
    state = None
    if hasattr(obs, "_states"):
        state = obs._states.get(task_id)

    elapsed = round((time.time() - start) * 1000)

    if state:
        ctx = state.get("context", {})
        return TaskResponse(
            task_id=task_id,
            status=state.get("state", "unknown"),
            result=ctx.get("final_result", ctx.get("execution_result", "")),
            trace_id=state.get("trace_id", ""),
            cost="0",
            latency=f"{elapsed}ms",
        )
    else:
        return TaskResponse(
            task_id=task_id,
            status="queued",
            message="Task not yet processed or completed",
            latency=f"{elapsed}ms",
        )


@router.get("/task/{task_id}/trace", response_model=TraceResponse)
async def v1_task_trace(task_id: str, request: Request):
    """
    Get full execution trace.
    Returns step-by-step events, FSM transitions, agent calls, and cache hits.
    """
    from backend.services.orchestrator_core import get_observability
    start = time.time()

    obs = get_observability()
    replay = obs.replay(task_id) if hasattr(obs, "replay") else {}

    elapsed = round((time.time() - start) * 1000)

    events = replay.get("events", [])
    # Build trace steps
    steps = []
    fsm_transitions = []
    agent_calls = []
    cache_hits = 0

    for ev in events:
        step = {
            "step": ev.get("step", ""),
            "agent": ev.get("agent", ""),
            "latency_ms": ev.get("latency_ms", 0),
            "timestamp": ev.get("timestamp", ""),
        }
        steps.append(step)

        if "fsm_" in ev.get("step", "") or ev.get("step") in ("fsm_completed", "fsm_transition"):
            fsm_transitions.append({
                "from": ev.get("from_state", ""),
                "to": ev.get("to_state", ev.get("step", "")),
            })
        if ev.get("agent") and ev.get("agent") != "system":
            agent_calls.append({
                "agent": ev.get("agent"),
                "input_preview": str(ev.get("input_data", ""))[:100],
                "output_preview": str(ev.get("output_data", ""))[:200],
                "latency_ms": ev.get("latency_ms", 0),
            })
        if "cache" in ev.get("step", "").lower() and "hit" in str(ev.get("output_data", "")).lower():
            cache_hits += 1

    return TraceResponse(
        trace_id=replay.get("trace_id", task_id),
        task_id=task_id,
        status="complete" if replay else "not_found",
        steps=steps,
        fsm_transitions=fsm_transitions,
        agent_calls=agent_calls,
        cache_hits=cache_hits,
        total_cost="0",
        total_latency=f"{elapsed}ms",
        message="Trace retrieved" if events else "No trace found for this task",
    )


@router.post("/agent/chat", response_model=ChatResponse)
async def v1_agent_chat(req: AgentChatRequest, request: Request):
    """
    Simplified agent chat — one-shot Q&A without FSM lifecycle.
    Auto-routes to the best available agent.
    """
    start = time.time()
    session_id = req.session_id or str(uuid.uuid4())[:8]

    try:
        from backend.services.maeos import MAEOS
        from backend.routes.maeos import _get_maeos

        maeos = await _get_maeos()

        # Simple chat = single agent call (executor only)
        task_id = await maeos.submit(
            description=req.message,
            priority=2,
            wait=True,
        )

        elapsed = round((time.time() - start) * 1000)

        return ChatResponse(
            session_id=session_id,
            status="ok",
            response=f"Task submitted, ID: {task_id}",
            agent_used="executor",
            latency=f"{elapsed}ms",
        )
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        return ChatResponse(
            session_id=session_id,
            status="error",
            response=str(e),
            latency=f"{elapsed}ms",
            message=f"Chat failed: {str(e)}",
        )


@router.get("/health", response_model=HealthResponse)
async def v1_health():
    """Public API health check."""
    return HealthResponse(
        status="ok",
        service="AI Team Hub",
        version="2.0.0",
        modes_available=["auto", "control", "debug"],
        latency="0ms",
    )


@router.get("/system/modes")
async def v1_system_modes():
    """List available system modes and their capabilities."""
    return {
        "modes": [
            {
                "name": "auto",
                "description": "Full FSM + agent pipeline + cache (recommended)",
                "features": ["fsm_routing", "agent_planning", "execution", "review", "diversity_check", "cache"],
                "complexity": "high",
            },
            {
                "name": "control",
                "description": "User overrides agent behavior via agent_config",
                "features": ["custom_agent", "overridable_pipeline"],
                "complexity": "medium",
            },
            {
                "name": "debug",
                "description": "Full visibility into FSM states, traces, and internals",
                "features": ["full_trace", "fsm_state_dump", "agent_logs", "cache_hit_trace", "cost_breakdown"],
                "complexity": "high",
            },
        ],
    }


# ═══════════════════════════════════════════════════════════
# Mode Handlers (Phase 3)
# ═══════════════════════════════════════════════════════════

async def _run_auto(req: TaskRunRequest, task_id: str, start: float) -> TaskResponse:
    """AUTO MODE: Full FSM + agents + cache."""
    from backend.services.orchestrator_core import create_fsm_orchestrator, get_observability

    api_key_val = await _get_provider_key(req.provider)
    orch = create_fsm_orchestrator(
        provider=req.provider,
        model=req.model,
        api_key=api_key_val,
        max_retries=3,
        adaptive=True,
    )
    ctx = await orch.run(req.task)

    # Save trace (reuse existing observability)
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

    elapsed = round((time.time() - start) * 1000)
    return TaskResponse(
        task_id=ctx.task_id,
        status=ctx.state,
        result=ctx.final_result or ctx.execution_result or "",
        trace_id=orch.trace_id,
        cost="0",
        latency=f"{elapsed}ms",
        message="Task completed successfully",
    )


async def _run_control(req: TaskRunRequest, task_id: str, start: float) -> TaskResponse:
    """CONTROL MODE: User specifies agent behavior."""
    from backend.services.orchestrator_core import create_fsm_orchestrator

    api_key_val = await _get_provider_key(req.provider)
    orch = create_fsm_orchestrator(
        provider=req.provider,
        model=req.model,
        api_key=api_key_val,
        max_retries=3,
        adaptive=True,
        force_mode=req.agent_config.get("force_mode") if req.agent_config else None,
        enforce_diversity=req.agent_config.get("enforce_diversity", True) if req.agent_config else True,
    )
    ctx = await orch.run(req.task)

    elapsed = round((time.time() - start) * 1000)
    return TaskResponse(
        task_id=ctx.task_id,
        status=ctx.state,
        result=ctx.final_result or ctx.execution_result or "",
        trace_id=orch.trace_id,
        cost="0",
        latency=f"{elapsed}ms",
        message="Control mode execution completed",
    )


async def _run_debug(req: TaskRunRequest, task_id: str, start: float) -> TaskResponse:
    """DEBUG MODE: Full trace + FSM states."""
    from backend.services.orchestrator_core import create_fsm_orchestrator, get_observability

    api_key_val = await _get_provider_key(req.provider)
    orch = create_fsm_orchestrator(
        provider=req.provider,
        model=req.model,
        api_key=api_key_val,
        max_retries=3,
        adaptive=True,
        force_mode=req.agent_config.get("force_mode") if req.agent_config else None,
    )
    ctx = await orch.run(req.task)

    # Full trace
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

    elapsed = round((time.time() - start) * 1000)
    return TaskResponse(
        task_id=ctx.task_id,
        status=ctx.state,
        result=ctx.final_result or ctx.execution_result or "",
        trace_id=orch.trace_id,
        cost="0",
        latency=f"{elapsed}ms",
        message="Debug mode: use /v1/task/{task_id}/trace for full details",
    )


async def _get_provider_key(provider: str) -> str:
    """Fetch API key from cache/database."""
    from backend.database import async_session
    from sqlalchemy import select
    from backend.models import APIKey

    try:
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
