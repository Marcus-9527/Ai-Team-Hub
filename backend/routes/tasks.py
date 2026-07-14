"""
routes/tasks.py — Task CRUD + Execution API

Provides:
  POST   /api/tasks                       — Create task
  GET    /api/tasks                       — List tasks (filterable)
  GET    /api/tasks/{task_id}             — Get task detail (with steps)
  PATCH  /api/tasks/{task_id}             — Update task metadata
  DELETE /api/tasks/{task_id}             — Delete task

  POST   /api/tasks/{task_id}/plan        — CREATED → PLANNING
  POST   /api/tasks/{task_id}/execute     — PLANNING → EXECUTING → run steps
  POST   /api/tasks/{task_id}/pause       — EXECUTING → PAUSED
  POST   /api/tasks/{task_id}/resume      — PAUSED → EXECUTING
  POST   /api/tasks/{task_id}/cancel      — any active → CANCELLED
  POST   /api/tasks/{task_id}/complete    — EXECUTING → COMPLETED
  POST   /api/tasks/{task_id}/fail        — EXECUTING/PLANNING → FAILED

  POST   /api/tasks/{task_id}/steps       — Add a step to a task
  GET    /api/tasks/{task_id}/steps       — List steps of a task
  PATCH  /api/tasks/{task_id}/steps/{step_id}  — Update a step
  GET    /api/tasks/{task_id}/steps/{step_id}  — Get step detail
  POST   /api/tasks/{task_id}/executions  — List executions for a step
  GET    /api/tasks/{task_id}/progress    — Get execution progress
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, List

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.runtime.execution_store import SSEBroadcaster
from backend.services.task.task_orchestrator import TaskOrchestrator, get_task_broadcaster
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_executor import TaskExecutor
from backend.services.runtime.executor import ExecutionRuntime
from backend.services.task.task_approval_service import TaskApprovalService
from backend.services.task.task_policy import TaskPolicyService, RiskLevel
from backend.services.task.task_plan_service import (
    TaskPlanService,
    PlanConversionError,
    EmptyPlanError,
    NoActivePlanError,
    PolicyBlockedError,
)
from backend.services.task.task_plan_review import (
    TaskPlanReviewService,
    ReviewGateBlockedError,
)

from backend.services.task.task_hooks import (
    TaskLifecycleEvent,
    TaskHookContext,
    get_task_hook_registry,
)

logger = logging.getLogger("routes.tasks")
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# ── Singleton ──

_manager: Optional[TaskManager] = None
_executor: Optional[TaskExecutor] = None
_runtime: Optional[ExecutionRuntime] = None


def _get_manager() -> TaskManager:
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager


def _get_executor() -> TaskExecutor:
    """Get or create the TaskExecutor singleton."""
    global _executor
    if _executor is None:
        _executor = TaskExecutor()
    return _executor


def _get_runtime() -> ExecutionRuntime:
    """Get or create the ExecutionRuntime singleton."""
    global _runtime
    if _runtime is None:
        _runtime = ExecutionRuntime(max_workers=4)
    return _runtime


# ── Approval Singleton ──

_approval: Optional[TaskApprovalService] = None


def _get_approval() -> TaskApprovalService:
    global _approval
    if _approval is None:
        _approval = TaskApprovalService()
    return _approval


# ── Policy Singleton ──

_policy: Optional[TaskPolicyService] = None


def _get_policy() -> TaskPolicyService:
    global _policy
    if _policy is None:
        _policy = TaskPolicyService()
    return _policy


# ── Plan Singleton ──

_plan_service: Optional[TaskPlanService] = None


def _get_plan_service() -> TaskPlanService:
    global _plan_service
    if _plan_service is None:
        _plan_service = TaskPlanService()
    return _plan_service


# ── Review Singleton ──

_review: Optional[TaskPlanReviewService] = None


def _get_review() -> TaskPlanReviewService:
    global _review
    if _review is None:
        _review = TaskPlanReviewService()
    return _review


# ═══════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    channel_id: Optional[str] = None
    workspace_id: Optional[str] = None
    priority: int = 2
    intent: str = ""
    created_by: str = "system"


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    intent: Optional[str] = None
    channel_id: Optional[str] = None
    workspace_id: Optional[str] = None


class TaskResponse(BaseModel):
    id: str
    channel_id: Optional[str]
    workspace_id: Optional[str]
    title: str
    description: str
    status: str
    priority: int
    intent: str
    created_by: str
    created_at: Optional[str]
    updated_at: Optional[str]
    completed_at: Optional[str]
    steps_count: int
    # ── Phase 4 delivery fields ──
    review_status: Optional[str] = "pending"
    git_commit: Optional[str] = None
    files_changed: List[str] = []
    commands_run: List[str] = []
    test_result: str = ""
    review_comments: str = ""
    review_rounds: int = 0
    techlead_decision: Optional[dict] = None


class TaskDetailResponse(TaskResponse):
    steps: list[dict] = []


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


class TaskStepResponse(BaseModel):
    id: str
    task_id: str
    teammate_id: Optional[str]
    order: int
    objective: str
    input_context: str
    output: str
    status: str
    maeos_task_id: Optional[str]
    error: str
    retry_count: int
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


# ═══════════════════════════════════════════════════════════════
# Step Schemas
# ═══════════════════════════════════════════════════════════════


class CreateStepRequest(BaseModel):
    objective: str
    teammate_id: Optional[str] = None
    order: Optional[int] = None  # auto-assign if None
    requires_approval: str = "0"  # "0"=no, "1"=yes (Phase C1)


class UpdateStepRequest(BaseModel):
    objective: Optional[str] = None
    teammate_id: Optional[str] = None
    input_context: Optional[str] = None
    output: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    requires_approval: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# Approval Schemas (Phase C1)
# ═══════════════════════════════════════════════════════════════


class ApprovalActionRequest(BaseModel):
    """Request body for approve / reject."""
    approved_by: str = "system"
    reason: str = ""


class ApprovalResponse(BaseModel):
    id: str
    task_id: str
    step_id: Optional[str]
    status: str
    reason: str
    requested_at: Optional[str]
    approved_at: Optional[str]
    approved_by: Optional[str]


# ═══════════════════════════════════════════════════════════════
# Policy Schemas (Phase C2)
# ═══════════════════════════════════════════════════════════════


class UpdatePolicyRequest(BaseModel):
    approval_required: Optional[str] = None
    max_retry: Optional[int] = None
    max_cost: Optional[int] = None
    risk_level: Optional[str] = None
    allowed_teammates: Optional[str] = None  # JSON array string


class PolicyResponse(BaseModel):
    id: str
    task_id: str
    approval_required: str
    max_retry: int
    max_cost: int
    risk_level: str
    allowed_teammates: list[str]
    created_at: Optional[str]


# ═══════════════════════════════════════════════════════════════
# Plan Schemas (Phase C)
# ═══════════════════════════════════════════════════════════════


class PlanResponse(BaseModel):
    id: str
    task_id: str
    title: str
    description: str
    confidence: str
    rationale: str
    risk_level: str
    estimated_cost: str
    status: str
    steps_count: int
    steps: list[dict] = []
    created_at: Optional[str]


class PlanApplyRequest(BaseModel):
    """Optional overrides when applying a plan."""
    force: bool = False  # skip policy check


# ═══════════════════════════════════════════════════════════════
# Plan Review Schemas (Phase D)
# ═══════════════════════════════════════════════════════════════


class PlanReviewRequest(BaseModel):
    """Request body for requesting a plan review."""
    reviewer: str = ""
    comment: str = ""


class PlanReviewActionRequest(BaseModel):
    """Request body for approve / reject."""
    reviewer: str = ""
    comment: str = ""


class PlanReviewResponse(BaseModel):
    id: str
    plan_id: str
    status: str
    reviewer: str
    comment: str
    created_at: Optional[str]


# ═══════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(req: CreateTaskRequest, db: AsyncSession = Depends(get_db)):
    """Create a new task. Returns immediately — orchestration runs in background."""
    mgr = _get_manager()
    task = await mgr.create_task(
        db,
        title=req.title,
        description=req.description,
        channel_id=req.channel_id,
        workspace_id=req.workspace_id,
        priority=req.priority,
        intent=req.intent,
        created_by=req.created_by,
    )
    await db.commit()
    await db.refresh(task)

    # ── Dispatch TASK_CREATED with rich context ──
    try:
        from backend.services.task.task_hooks import (
            TaskLifecycleEvent,
            TaskHookContext,
            get_task_hook_registry,
        )
        registry = get_task_hook_registry()
        ctx = TaskHookContext(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description,
            task_status=task.status,
            channel_id=task.channel_id or "",
            workspace_id=task.workspace_id or "",
            extra={"intent": task.intent, "created_by": task.created_by, "priority": task.priority},
        )
        await registry.dispatch(TaskLifecycleEvent.TASK_CREATED, ctx)
    except Exception as e:
        logger.debug(f"[ROUTES] TASK_CREATED dispatch failed (non-fatal): {e}")

    # ── Step 1: fire TASK_CREATED on the wakeup bus (claim competition) ──
    # Coexists with _background_orchestrate below; handler only competes for
    # the claim, does not enter the execution layer yet.
    try:
        from backend.services.autonomous.event_wakeup import (
            get_event_wakeup_bus, WakeupEvent, WakeupPayload,
        )
        get_event_wakeup_bus().fire(WakeupEvent.TASK_CREATED, WakeupPayload(
            event_type=WakeupEvent.TASK_CREATED.value,
            task_id=task.id,
            channel_id=task.channel_id or "",
            reason="task created via API",
        ))
    except Exception as e:
        logger.debug(f"[ROUTES] TASK_CREATED wakeup fire failed (non-fatal): {e}")

    # ── Background orchestration: plan → execute (no blocking) ──
    goal = req.intent or req.title or req.description
    if goal:
        asyncio.create_task(_background_orchestrate(task.id, goal))

    return _task_to_response(task)


async def _background_orchestrate(task_id: str, goal: str) -> None:
    """Run TaskOrchestrator in background with its own DB session."""
    from backend.database import async_session
    from backend.services.task.task_manager import TaskManager
    from backend.services.task.task_hooks import (
        TaskLifecycleEvent,
        TaskHookContext,
        get_task_hook_registry,
    )
    async with async_session() as db:
        try:
            runtime = _get_runtime()
            orch = TaskOrchestrator(runtime=runtime)
            await orch.start_task(db, task_id, goal)
            await db.commit()
            logger.info("[BG-ORCH] Task %s completed via background orchestration", task_id[:8])
        except Exception as e:
            logger.warning("[BG-ORCH] Background orchestration for %s failed: %s", task_id[:8], e)
            try:
                await db.rollback()
                mgr = TaskManager()
                task = await mgr.get_task(db, task_id)
                if task and task.status not in ("COMPLETED", "FAILED", "CANCELLED"):
                    await mgr.fail(db, task_id)
                    await db.commit()
            except Exception:
                pass

        # ── Dispatch completion hooks (Memory → Brain → Channel Notify) ──
        # ponytail: one dispatch here covers the whole background path; no
        # new scheduler/queue. Uses the live task so ctx carries real data.
        try:
            mgr = TaskManager()
            task = await mgr.get_task(db, task_id)
            if task:
                lifecycle = (
                    TaskLifecycleEvent.TASK_COMPLETED
                    if task.status == "COMPLETED"
                    else TaskLifecycleEvent.TASK_FAILED
                )
                ctx = TaskHookContext(
                    task_id=task.id,
                    task_title=task.title,
                    task_description=task.description,
                    task_status=task.status,
                    channel_id=task.channel_id or "",
                    workspace_id=task.workspace_id or "",
                )
                await get_task_hook_registry().dispatch(lifecycle, ctx)
        except Exception as e:
            logger.debug("[BG-ORCH] completion hook dispatch failed (non-fatal): %s", e)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    channel_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List tasks with optional filters."""
    mgr = _get_manager()
    tasks = await mgr.list_tasks(
        db,
        channel_id=channel_id,
        status=status,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
    total = await mgr.count_tasks(db, channel_id=channel_id, status=status)
    return {
        "tasks": [_task_to_response(t) for t in tasks],
        "total": total,
    }


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Get task detail with steps."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_detail(task)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    req: UpdateTaskRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update task metadata. Excludes status transitions."""
    mgr = _get_manager()
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        task = await mgr.update_task(db, task_id, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await db.commit()
    await db.refresh(task)
    return _task_to_response(task)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a task (cascades to steps and executions)."""
    mgr = _get_manager()
    try:
        await mgr.delete_task(db, task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await db.commit()


# ═══════════════════════════════════════════════════════════════
# Lifecycle Routes
# ═══════════════════════════════════════════════════════════════


@router.post("/{task_id}/plan", response_model=TaskResponse)
async def plan_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Analyze task goal, generate plan, assign teammates, and create steps.

    Flow: TaskAnalyzer -> PlanningEngine (+ LLM via MAEOS) -> DAGBuilder
          -> TeammateSelector -> save plan -> create steps -> PLANNING

    Falls back to keyword-only analysis when MAEOS/LLM is unavailable.
    """
    mgr = _get_manager()

    # 1. Get task
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    goal = task.intent or task.title or task.description
    if not goal:
        raise HTTPException(status_code=400, detail="Task has no goal to plan")

    from backend.services.planner.planning_engine import PlanningEngine, PlanningError

    dag = None
    engine = PlanningEngine()

    # 2. Try full PlanningEngine (MAEOS + LLM), fall back to keyword-only
    try:
        dag = await engine.plan(
            goal=goal,
            context={"task_id": task.id, "priority": task.priority},
            task_id=task.id,
        )
        logger.info(
            "[PLAN] PlanningEngine produced %d nodes for task %s",
            len(dag.nodes), task_id,
        )
    except (PlanningError, ImportError, RuntimeError) as e:
        logger.warning(
            "[PLAN] PlanningEngine failed (%s: %s) - fallback to keyword analysis",
            type(e).__name__, e,
        )

    # 3. If PlanningEngine failed, build minimal DAG from keyword analysis
    if dag is None or not dag.nodes:
        from backend.services.planner.task_analyzer import TaskAnalyzer
        from backend.services.planner.dag_builder import DAGBuilder
        from backend.services.task.task_planner_schema import TaskPlan, TaskStepProposal

        analyzer = TaskAnalyzer()
        analysis = analyzer.analyze(goal)
        task_type = analysis.task_type

        from backend.services.teammate_intelligence import SkillRegistry, TeammateSelector
        required_skills = SkillRegistry.get_skills(task_type)

        profiles = await TeammateSelector.recommend_by_skills(
            required_skills, top_n=3, db=db,
        )
        # ponytail: no teammate carries the generic skill tags → fall back to
        # any teammates so planning still produces steps.
        if not profiles:
            profiles = await TeammateSelector.recommend_by_skills([], top_n=3, db=db)

        if profiles:
            steps = []
            for i, p in enumerate(profiles):
                steps.append(TaskStepProposal(
                    order=i + 1,
                    teammate_id=p.id,
                    objective=f"{goal} - {p.role or p.name}",
                    risk_level="LOW",
                ))
            plan = TaskPlan(
                task_id=task_id,
                title=f"Plan: {goal[:60]}",
                description=f"Keyword analysis [{task_type}], {len(steps)} steps",
                steps=steps,
                risk_level="LOW",
            )
            dag = DAGBuilder().build(plan)

    # 4. No plan at all -> fail
    if dag is None or not dag.nodes:
        raise HTTPException(
            status_code=400,
            detail="Failed to generate any steps for this task",
        )

    # 5. Assign teammates via TeammateSelector for each DAG node
    from backend.services.teammate_intelligence import TeammateSelector

    for node in dag.nodes.values():
        if node.required_skills and not node.selected_teammate_id and not node.teammate:
            try:
                profiles = await TeammateSelector.recommend_by_skills(
                    node.required_skills, top_n=1, db=db,
                )
                if profiles:
                    node.selected_teammate_id = profiles[0].id
                    node.teammate = profiles[0].name
                    logger.info(
                        "[PLAN] Assigned %s -> node %s (skills=%s)",
                        profiles[0].name, node.id[:8], node.required_skills,
                    )
            except Exception as e:
                logger.warning("[PLAN] Teammate assignment failed for node %s: %s",
                               node.id[:8], e)

    # 6. Save the plan via TaskPlanService
    plan_service = _get_plan_service()
    plan_steps = []
    ordered_nodes = sorted(dag.nodes.values(), key=lambda n: list(dag.nodes.keys()).index(n.id))
    for i, node in enumerate(ordered_nodes):
        plan_steps.append({
            "order": i + 1,
            "teammate_id": node.selected_teammate_id or node.teammate or "",
            "objective": node.description,
            "depends_on": [],
            "risk_level": "LOW",
            "requires_approval": node.require_approval,
        })

    await plan_service.save_plan(
        db,
        task_id=task_id,
        title=dag.name or f"Plan for {task.title}",
        description=f"DAG with {len(dag.nodes)} nodes",
        steps=plan_steps,
        confidence=0.8,
    )

    # 7. Create TaskSteps directly (skip review gate for auto-planning)
    for i, node in enumerate(ordered_nodes):
        teammate_id = node.selected_teammate_id or node.teammate or ""
        await mgr.state.create_step(
            db,
            task_id=task_id,
            order=i + 1,
            objective=node.description,
            teammate_id=teammate_id,
        )

    logger.info(
        "[PLAN] Created %d steps for task %s with teammates: %s",
        len(dag.nodes), task_id,
        [n.teammate for n in ordered_nodes if n.teammate],
    )

    # 8. Transition to PLANNING
    task = await mgr.start_planning(db, task_id)
    await db.commit()
    await db.refresh(task)

    return _task_to_response(task)


@router.post("/{task_id}/execute", response_model=TaskDetailResponse)
async def execute_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Transition task: PLANNING → EXECUTING, then run all steps through MAEOS."""
    mgr = _get_manager()
    
    # First transition to EXECUTING
    try:
        task = await mgr.start_execution(db, task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(task)
    
    # Now execute all steps through MAEOS
    try:
        # Get ExecutionRuntime
        runtime = _get_runtime()
        
        # Get executor and wire runtime
        executor = _get_executor()
        executor.set_runtime(runtime)
        
        # Execute the task (runs all pending steps)
        task = await executor.execute_task(db, task)
        await db.commit()
        await db.refresh(task)

        # ── Dispatch TASK_COMPLETED/FAILED with rich context ──
        if task.status in ("COMPLETED", "FAILED"):
            try:
                lifecycle = (
                    TaskLifecycleEvent.TASK_COMPLETED
                    if task.status == "COMPLETED"
                    else TaskLifecycleEvent.TASK_FAILED
                )
                registry = get_task_hook_registry()
                ctx = TaskHookContext(
                    task_id=task.id,
                    task_title=task.title,
                    task_description=task.description,
                    task_status=task.status,
                    channel_id=task.channel_id or "",
                    workspace_id=task.workspace_id or "",
                )
                await registry.dispatch(lifecycle, ctx)
            except Exception as exc:
                logger.debug(f"[ROUTES] Execute event dispatch failed (non-fatal): {exc}")

    except RuntimeError as e:
        logger.error(f"ExecutionRuntime not available: {e}")
        raise HTTPException(status_code=503, detail=f"ExecutionRuntime not available: {e}")
    except Exception as e:
        logger.error(f"Task execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {e}")
    
    return _task_to_detail(task)


@router.post("/{task_id}/pause", response_model=TaskResponse)
async def pause_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Transition task: EXECUTING → PAUSED."""
    mgr = _get_manager()
    return await _transition_task(mgr, db, task_id, mgr.pause)


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Transition task: PAUSED → EXECUTING."""
    mgr = _get_manager()
    return await _transition_task(mgr, db, task_id, mgr.resume)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Transition task: any active state → CANCELLED."""
    mgr = _get_manager()
    return await _transition_task(mgr, db, task_id, mgr.cancel)


@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Transition task: RUNNING → COMPLETED."""
    mgr = _get_manager()
    return await _transition_task(mgr, db, task_id, mgr.complete)


@router.post("/{task_id}/fail", response_model=TaskResponse)
async def fail_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Transition task: RUNNING/PLANNING → FAILED."""
    mgr = _get_manager()
    return await _transition_task(mgr, db, task_id, mgr.fail)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


async def _transition_task(mgr, db, task_id, transition_fn):
    """Execute a status transition and return the response."""
    try:
        task = await transition_fn(db, task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(task)

    # ── Dispatch lifecycle events from route level ──
    # These provide richer context than the internal TaskEventLogger.
    transition_name = transition_fn.__name__
    await _dispatch_task_event(task, transition_name)

    return _task_to_response(task)


async def _dispatch_task_event(task, transition_name: str) -> None:
    """Dispatch a route-level task lifecycle event to the hook registry."""
    try:
        from backend.services.task.task_hooks import (
            TaskLifecycleEvent,
            TaskHookContext,
            get_task_hook_registry,
        )

        event_map = {
            "complete": TaskLifecycleEvent.TASK_COMPLETED,
            "fail": TaskLifecycleEvent.TASK_FAILED,
        }
        lifecycle = event_map.get(transition_name)
        if lifecycle is None:
            return

        registry = get_task_hook_registry()
        ctx = TaskHookContext(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description,
            task_status=task.status,
            channel_id=task.channel_id or "",
            workspace_id=task.workspace_id or "",
        )
        await registry.dispatch(lifecycle, ctx)
    except Exception as e:
        logger.debug(f"[ROUTES] Hook dispatch failed (non-fatal): {e}")


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _steps_loaded(task):
    """Check if task.steps relationship is loaded without triggering lazy load."""
    try:
        insp = sa.inspect(task)
        return not insp.unloaded.intersection({'steps'})
    except Exception:
        return False


def _task_to_response(task) -> TaskResponse:
    files_changed = task.files_changed if isinstance(task.files_changed, list) else (
        json.loads(task.files_changed) if isinstance(task.files_changed, str) and task.files_changed else []
    )
    commands_run = task.commands_run if isinstance(task.commands_run, list) else (
        json.loads(task.commands_run) if isinstance(task.commands_run, str) and task.commands_run else []
    )
    return TaskResponse(
        id=task.id,
        channel_id=task.channel_id,
        workspace_id=task.workspace_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        intent=task.intent,
        created_by=task.created_by,
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        steps_count=len(task.steps) if _steps_loaded(task) and task.steps else 0,
        # Phase 4 delivery fields
        review_status=getattr(task, "review_status", "pending") or "pending",
        git_commit=getattr(task, "git_commit", None),
        files_changed=files_changed or [],
        commands_run=commands_run or [],
        test_result=getattr(task, "test_result", "") or "",
        review_comments=getattr(task, "review_comments", "") or "",
        review_rounds=getattr(task, "review_rounds", 0) or 0,
    )


def _task_to_detail(task) -> TaskDetailResponse:
    base = _task_to_response(task)
    return TaskDetailResponse(
        **base.model_dump(),
        steps=[_step_to_dict(s) for s in (task.steps or [])],
    )


def _step_to_dict(step) -> dict:
    return {
        "id": step.id,
        "task_id": step.task_id,
        "teammate_id": step.teammate_id,
        "order": step.order,
        "objective": step.objective,
        "input_context": step.input_context,
        "output": step.output,
        "status": step.status,
        "maeos_task_id": step.maeos_task_id,
        "error": step.error,
        "retry_count": step.retry_count,
        "created_at": step.created_at.isoformat() if step.created_at else None,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
    }


# ═══════════════════════════════════════════════════════════════
# Step Routes
# ═══════════════════════════════════════════════════════════════


@router.post("/{task_id}/steps", response_model=TaskStepResponse, status_code=201)
async def create_step(
    task_id: str,
    req: CreateStepRequest,
    db: AsyncSession = Depends(get_db),
):
    """Add a step to a task."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Auto-assign order if not specified
    if req.order is None:
        existing = await mgr.state.list_steps(db, task_id)
        next_order = (max((s.order for s in existing), default=0)) + 1
    else:
        next_order = req.order

    step = await mgr.state.create_step(
        db,
        task_id=task_id,
        order=next_order,
        objective=req.objective,
        teammate_id=req.teammate_id,
        requires_approval=req.requires_approval,
    )
    await db.commit()
    await db.refresh(step)
    return _step_to_dict(step)


@router.get("/{task_id}/steps", response_model=list[TaskStepResponse])
async def list_steps(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all steps for a task."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return [_step_to_dict(s) for s in (task.steps or [])]


@router.get("/{task_id}/steps/{step_id}", response_model=TaskStepResponse)
async def get_step(
    task_id: str,
    step_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single step."""
    mgr = _get_manager()
    step = await mgr.state.get_step(db, step_id)
    if not step or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="Step not found")
    return _step_to_dict(step)


@router.patch("/{task_id}/steps/{step_id}", response_model=TaskStepResponse)
async def update_step(
    task_id: str,
    step_id: str,
    req: UpdateStepRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a step's fields."""
    mgr = _get_manager()
    step = await mgr.state.get_step(db, step_id)
    if not step or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="Step not found")

    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    step = await mgr.state.update_step(db, step, **kwargs)
    await db.commit()
    await db.refresh(step)
    return _step_to_dict(step)


@router.get("/{task_id}/progress")
async def get_task_progress(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get execution progress for a task."""
    executor = _get_executor()
    progress = await executor.get_task_progress(db, task_id)
    if not progress["steps"]:
        # Check task exists
        mgr = _get_manager()
        task = await mgr.get_task(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
    return progress


# ═══════════════════════════════════════════════════════════════
# Execution Routes
# ═══════════════════════════════════════════════════════════════


@router.post("/{task_id}/executions")
async def list_executions(
    task_id: str,
    step_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List executions for a given step."""
    mgr = _get_manager()
    step = await mgr.state.get_step(db, step_id)
    if not step or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="Step not found")
    executions = await mgr.state.list_executions(db, step_id)
    return {"executions": [e.to_dict() for e in executions]}


# ═══════════════════════════════════════════════════════════════
# V3.0 Phase B: Task Intelligence Dashboard
# ═══════════════════════════════════════════════════════════════


@router.get("/{task_id}/executions")
async def get_task_executions(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all executions for a task (across all steps)."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    executions = await mgr.state.list_executions_by_task(db, task_id)
    # Convert datetime objects to strings
    for ex in executions:
        for key in ("start_time", "end_time", "created_at"):
            if isinstance(ex.get(key), datetime):
                ex[key] = ex[key].isoformat()
    return {"executions": executions, "total": len(executions)}


@router.get("/{task_id}/results")
async def get_task_results(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all execution results for a task (across all steps)."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    results = await mgr.state.list_results_by_task(db, task_id)
    # Convert datetime objects to strings
    for r in results:
        for key in ("created_at", "updated_at"):
            if isinstance(r.get(key), datetime):
                r[key] = r[key].isoformat()
    return {"results": results, "total": len(results)}


@router.get("/{task_id}/analytics")
async def get_task_analytics(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated analytics for a task."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    analytics = await mgr.state.get_task_analytics(db, task_id)
    # Add task meta
    analytics["task_id"] = task_id
    analytics["task_title"] = task.title
    analytics["task_status"] = task.status
    return analytics


# ═══════════════════════════════════════════════════════════════
# V3.1 Phase B: Memory Workspace API
# ═══════════════════════════════════════════════════════════════


class MemoryItemResponse(BaseModel):
    id: str
    type: str  # "decision" | "conversation" | "reasoning" | "execution" | "revision" | "event"
    content: str
    actor: str = ""
    timestamp: Optional[str] = None
    metadata: dict = {}


class TaskMemoryResponse(BaseModel):
    global_: list[MemoryItemResponse] = []
    workspace: list[MemoryItemResponse] = []
    channel: list[MemoryItemResponse] = []
    task: list[MemoryItemResponse] = []


@router.get("/{task_id}/memory", response_model=TaskMemoryResponse)
async def get_task_memory(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get task memory from all levels: global, workspace, channel, task.

    Returns structured memory items for display in the Memory Workspace UI.
    Task-level memory is derived from execution data, steps, and plan events.
    Other levels return available data or empty arrays.
    """
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # ── Task-level memory: build from execution data ──
    task_memories = []

    # Steps
    for step in (task.steps or []):
        if step.status != "PENDING":
            task_memories.append(MemoryItemResponse(
                id=f"step:{step.id}",
                type="execution",
                content=f"步骤「{step.objective}」{_status_label(step.status)}",
                actor=step.teammate_id or "system",
                timestamp=step.completed_at.isoformat() if step.completed_at else (
                    step.created_at.isoformat() if step.created_at else None
                ),
                metadata={"step_order": step.order, "status": step.status},
            ))

        if step.error:
            task_memories.append(MemoryItemResponse(
                id=f"error:{step.id}",
                type="event",
                content=f"步骤「{step.objective}」出错: {step.error[:200]}",
                actor="system",
                timestamp=step.completed_at.isoformat() if step.completed_at else (
                    step.created_at.isoformat() if step.created_at else None
                ),
                metadata={"step_order": step.order, "error": step.error[:300]},
            ))

    # Executions (via state)
    try:
        executions = await mgr.state.list_executions_by_task(db, task_id)
        for ex in executions:
            if ex.get("teammate_id"):
                task_memories.append(MemoryItemResponse(
                    id=f"exec:{ex['id']}",
                    type="execution",
                    content=f"执行: {ex.get('teammate_id', '?')} 耗时 {ex.get('execution_time_ms', 0)}ms",
                    actor=ex.get("teammate_id", "system"),
                    timestamp=ex.get("end_time") or ex.get("start_time"),
                    metadata={
                        "attempt": ex.get("attempt", 1),
                        "model": ex.get("model_name", ""),
                        "tokens": ex.get("total_tokens", 0),
                    },
                ))
    except Exception:
        pass

    # Plan (via plan_service)
    try:
        svc = _get_plan_service()
        plan = await svc.get_plan(db, task_id)
        if plan and plan.status == "ACTIVE":
            task_memories.append(MemoryItemResponse(
                id=f"plan:{plan.id}",
                type="decision",
                content=f"创建执行计划: {plan.title} (置信度 {plan.confidence})",
                actor="system",
                timestamp=plan.created_at.isoformat() if plan.created_at else None,
                metadata={
                    "confidence": plan.confidence,
                    "risk_level": plan.risk_level,
                    "rationale": plan.rationale[:200],
                },
            ))
    except Exception:
        pass

    # Sort by timestamp descending
    task_memories.sort(key=lambda m: m.timestamp or "", reverse=True)

    # ── Channel-level memory: from task channel ──
    channel_memories = []
    if task.channel_id:
        try:
            from backend.models import Message
            stmt = (
                sa.select(Message)
                .where(Message.channel_id == task.channel_id)
                .order_by(Message.created_at.desc())
                .limit(20)
            )
            result = await db.execute(stmt)
            messages = result.scalars().all()
            for msg in messages:
                channel_memories.append(MemoryItemResponse(
                    id=f"msg:{msg.id}",
                    type="conversation",
                    content=msg.content[:200],
                    actor=msg.author_name or msg.role,
                    timestamp=msg.created_at.isoformat() if msg.created_at else None,
                    metadata={"role": msg.role},
                ))
        except Exception:
            pass

    return TaskMemoryResponse(
        global_=[],  # not implemented yet
        workspace=[],  # not implemented yet
        channel=channel_memories,
        task=task_memories,
    )


def _status_label(status: str) -> str:
    labels = {
        "COMPLETED": "已完成",
        "FAILED": "失败",
        "RUNNING": "执行中",
        "SKIPPED": "已跳过",
        "PENDING": "待处理",
    }
    return labels.get(status, status)


# ═══════════════════════════════════════════════════════════════
# QA-1: Task SSE Event Stream
# ═══════════════════════════════════════════════════════════════


@router.get("/{task_id}/events")
async def stream_task_events(task_id: str):
    """SSE real-time event stream for a task's lifecycle.

    Events: planning_started, team_created, dag_created,
            execution_started, execution_completed.
    """
    broadcaster = get_task_broadcaster()
    sub = broadcaster.subscribe(f"task:{task_id}")

    async def event_stream():
        import json
        import asyncio
        try:
            deadline = asyncio.get_event_loop().time() + 600  # 10 min
            while asyncio.get_event_loop().time() < deadline:
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=30)
                    yield event
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
            yield f"data: {json.dumps({'type': 'stream_end', 'data': {'reason': 'timeout'}})}\n\n"
        finally:
            broadcaster.unsubscribe(f"task:{task_id}", sub)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════════
# Approval Routes (Phase C1)
# ═══════════════════════════════════════════════════════════════


@router.get("/{task_id}/approvals", response_model=list[ApprovalResponse])
async def list_approvals(
    task_id: str,
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List approval requests for a task."""
    svc = _get_approval()
    approvals = await svc.list_approvals(db, task_id=task_id, status=status)
    return [_approval_to_dict(a) for a in approvals]


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single approval request."""
    svc = _get_approval()
    approval = await svc.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return _approval_to_dict(approval)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_approval(
    approval_id: str,
    req: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending approval request → resume the task."""
    svc = _get_approval()
    try:
        approval = await svc.approve(
            db, approval_id,
            approved_by=req.approved_by,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(approval)
    return _approval_to_dict(approval)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_approval(
    approval_id: str,
    req: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending approval request → cancel the task."""
    svc = _get_approval()
    try:
        approval = await svc.reject(
            db, approval_id,
            approved_by=req.approved_by,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(approval)
    return _approval_to_dict(approval)


# ═══════════════════════════════════════════════════════════════
# Approval Helpers
# ═══════════════════════════════════════════════════════════════


def _approval_to_dict(approval) -> dict:
    return {
        "id": approval.id,
        "task_id": approval.task_id,
        "step_id": approval.step_id,
        "status": approval.status,
        "reason": approval.reason or "",
        "requested_at": approval.requested_at.isoformat() if approval.requested_at else None,
        "approved_at": approval.approved_at.isoformat() if approval.approved_at else None,
        "approved_by": approval.approved_by,
    }


# ═══════════════════════════════════════════════════════════════
# Policy Routes (Phase C2)
# ═══════════════════════════════════════════════════════════════


@router.get("/{task_id}/policy", response_model=PolicyResponse)
async def get_task_policy(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the execution policy for a task (auto-creates default if missing)."""
    svc = _get_policy()
    policy = await svc.get_policy(db, task_id)
    return _policy_to_dict(policy)


@router.put("/{task_id}/policy", response_model=PolicyResponse)
async def update_task_policy(
    task_id: str,
    req: UpdatePolicyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update execution policy for a task."""
    svc = _get_policy()
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    policy = await svc.upsert_policy(db, task_id, **kwargs)
    await db.commit()
    await db.refresh(policy)
    return _policy_to_dict(policy)


# ═══════════════════════════════════════════════════════════════
# Policy Helpers
# ═══════════════════════════════════════════════════════════════


def _policy_to_dict(policy) -> dict:
    return {
        "id": policy.id,
        "task_id": policy.task_id,
        "approval_required": policy.approval_required or "0",
        "max_retry": policy.max_retry or 2,
        "max_cost": policy.max_cost or 0,
        "risk_level": policy.risk_level or RiskLevel.LOW,
        "allowed_teammates": policy.get_allowed_teammates(),
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
    }


# ═══════════════════════════════════════════════════════════════
# Plan Routes (Phase C)
# ═══════════════════════════════════════════════════════════════


@router.get("/{task_id}/plan", response_model=PlanResponse)
async def get_task_plan(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the ACTIVE plan for a task (with step proposals)."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    svc = _get_plan_service()
    plan = await svc.get_plan(db, task_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No active plan found")

    return _plan_to_response(plan)


@router.post("/{task_id}/plan/apply", response_model=TaskDetailResponse)
async def apply_task_plan(
    task_id: str,
    req: PlanApplyRequest = PlanApplyRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Convert the ACTIVE plan into TaskStep records and start execution.

    Flow:
      1. Convert plan steps → TaskStepModel records with source=PLANNER
      2. Policy evaluation is enforced unless force=True
      3. Transition task to PLANNING → EXECUTING
      4. Execute all steps through MAEOS
    """
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    svc = _get_plan_service()

    try:
        # Step 1: Convert plan → steps
        created_steps = await svc.convert_plan_to_steps(db, task_id)
    except NoActivePlanError:
        raise HTTPException(status_code=404, detail="No active plan found")
    except ReviewGateBlockedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PolicyBlockedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except EmptyPlanError:
        raise HTTPException(status_code=400, detail="Plan has no steps to apply")
    except PlanConversionError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Step 2: Transition task PLANNING → EXECUTING
    try:
        task = await mgr.start_execution(db, task_id)
    except ValueError as e:
        # May already be in EXECUTING (allow)
        task = await mgr.get_task(db, task_id)

    await db.commit()
    await db.refresh(task)

    # Step 3: Execute through ExecutionRuntime
    executor = _get_executor()
    try:
        runtime = _get_runtime()
        executor.set_runtime(runtime)
        task = await executor.execute_task(db, task)
        await db.commit()
        await db.refresh(task)
    except RuntimeError as e:
        # ExecutionRuntime not available — task stays in EXECUTING, steps are PENDING
        logger.warning(f"ExecutionRuntime not available during plan apply: {e}")
    except Exception as e:
        logger.error(f"Task execution after plan apply failed: {e}")

    return _task_to_detail(task)


# ═══════════════════════════════════════════════════════════════
# Plan Helpers
# ═══════════════════════════════════════════════════════════════


def _plan_to_response(plan) -> PlanResponse:
    import json
    steps = []
    try:
        steps = json.loads(plan.steps_json or "[]")
    except (json.JSONDecodeError, TypeError):
        pass
    return PlanResponse(
        id=plan.id,
        task_id=plan.task_id,
        title=plan.title,
        description=plan.description,
        confidence=plan.confidence,
        rationale=plan.rationale,
        risk_level=plan.risk_level,
        estimated_cost=plan.estimated_cost,
        status=plan.status,
        steps_count=plan._steps_count(),
        steps=steps,
        created_at=plan.created_at.isoformat() if plan.created_at else None,
    )


# ═══════════════════════════════════════════════════════════════
# Plan Review Routes (Phase D)
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/{task_id}/plan/review",
    response_model=PlanReviewResponse,
    status_code=201,
)
async def request_plan_review(
    task_id: str,
    req: PlanReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a review for the ACTIVE plan of a task.

    Creates a PENDING review entry linked to the plan.
    Only ACTIVE plans can be reviewed.
    """
    # Find the task and active plan
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    svc = _get_plan_service()
    plan = await svc.get_plan(db, task_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No active plan found")

    review_svc = _get_review()
    try:
        review = await review_svc.request_review(
            db,
            plan.id,
            reviewer=req.reviewer,
            comment=req.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    await db.refresh(review)
    return _plan_review_to_response(review)


@router.post(
    "/{task_id}/plan/approve",
    response_model=PlanReviewResponse,
)
async def approve_plan_review(
    task_id: str,
    req: PlanReviewActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve the review for the ACTIVE plan of a task.

    After approval the plan can be applied to create TaskSteps.
    """
    # Find the task and active plan
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    svc = _get_plan_service()
    plan = await svc.get_plan(db, task_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No active plan found")

    review_svc = _get_review()
    try:
        review = await review_svc.approve_review(
            db,
            plan.id,
            reviewer=req.reviewer,
            comment=req.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    await db.refresh(review)
    return _plan_review_to_response(review)


@router.post(
    "/{task_id}/plan/reject",
    response_model=PlanReviewResponse,
)
async def reject_plan_review(
    task_id: str,
    req: PlanReviewActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reject the review for the ACTIVE plan of a task.

    A rejected plan cannot be applied unless a new review
    is created and approved.
    """
    # Find the task and active plan
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    svc = _get_plan_service()
    plan = await svc.get_plan(db, task_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No active plan found")

    review_svc = _get_review()
    try:
        review = await review_svc.reject_review(
            db,
            plan.id,
            reviewer=req.reviewer,
            comment=req.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    await db.refresh(review)
    return _plan_review_to_response(review)


# ═══════════════════════════════════════════════════════════════
# V2.7 Phase C: Insights API
# ═══════════════════════════════════════════════════════════════


class InsightResponse(BaseModel):
    id: str
    type: str
    title: str
    content: str
    source_task_id: str
    confidence: float
    created_at: Optional[str]
    metadata: dict = {}


@router.get(
    "/{task_id}/insights",
    response_model=list[InsightResponse],
)
async def list_task_insights(
    task_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List MemoryInsights for a task."""
    mgr = _get_manager()
    task = await mgr.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    from backend.services.memory.memory_intelligence import (
        get_intelligence_service,
    )

    svc = get_intelligence_service()
    insights = await svc.list_insights(task_id=task_id, limit=limit, offset=offset)

    return [
        InsightResponse(
            id=ins.id,
            type=ins.type,
            title=ins.title,
            content=ins.content,
            source_task_id=ins.source_task_id,
            confidence=ins.confidence,
            created_at=ins.created_at.isoformat() if ins.created_at else None,
            metadata=dict(ins.metadata),
        )
        for ins in insights
    ]


# ═══════════════════════════════════════════════════════════════
# Plan Review Helpers
# ═══════════════════════════════════════════════════════════════


def _plan_review_to_response(review) -> PlanReviewResponse:
    return PlanReviewResponse(
        id=review.id,
        plan_id=review.plan_id,
        status=review.status,
        reviewer=review.reviewer or "",
        comment=review.comment or "",
        created_at=review.created_at.isoformat() if review.created_at else None,
    )

