"""
task_orchestrator.py — Auto-chain plan → assign → execute.

PERSISTS DAGDefinition + DAGNode to DB and emits SSE events
at each stage so the frontend can follow progress.

Reuses existing services: PlanningEngine, DAGBuilder, TeammateSelector,
TaskPlanService, TaskManager, TaskExecutor.

Wired from routes/tasks.py as asyncio.create_task so POST /api/tasks
returns immediately (no wait for LLM).
"""
import asyncio
import json
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel, TaskStatus, TaskStepModel,
    DAGDefinitionModel, DAGNodeModel,
)
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_executor import TaskExecutor
from backend.services.task.task_plan_service import TaskPlanService
from backend.services.planner.planning_engine import PlanningEngine, PlanningError
from backend.services.planner.task_analyzer import TaskAnalyzer
from backend.services.planner.dag_builder import DAGBuilder
from backend.services.teammate_intelligence import SkillRegistry, TeammateSelector
from backend.services.task.task_planner_schema import TaskPlan, TaskStepProposal
from backend.services.runtime.executor import ExecutionRuntime
from backend.services.runtime.execution_store import SSEBroadcaster

logger = logging.getLogger("task.orchestrator")

# ── Task-level SSE Broadcaster ──
# Reuses SSEBroadcaster from execution_store. Keyed by task_id.
_task_broadcaster: Optional[SSEBroadcaster] = None


def get_task_broadcaster() -> SSEBroadcaster:
    global _task_broadcaster
    if _task_broadcaster is None:
        _task_broadcaster = SSEBroadcaster()
    return _task_broadcaster


def _sse_event(event_type: str, task_id: str, data: dict) -> None:
    """Fire-and-forget SSE publish. Never blocks the orchestrator."""
    try:
        asyncio.ensure_future(
            get_task_broadcaster().publish(f"task:{task_id}", event_type, data)
        )
    except Exception:
        pass


class TaskOrchestrator:
    """Chain existing services: plan → persist DAG → assign → run."""

    def __init__(self, runtime: Optional[ExecutionRuntime] = None):
        self._runtime = runtime
        self._manager = TaskManager()
        self._plan_service = TaskPlanService()

    async def start_task(self, db: AsyncSession, task_id: str, goal: str):
        """Full pipeline. Task transitions through PENDING→PLANNING→ASSIGNED→RUNNING→done.

        Returns the task with its final status.
        """
        task = None
        try:
            await db.flush()
            task = await self._manager.start_planning(db, task_id)
            await db.commit()

            _sse_event("planning_started", task_id, {"goal": goal[:200]})

            # 1. Generate plan (DAG)
            logger.info("[ORCH-DBG] step1: calling _plan with goal=%s", goal[:60])
            dag = await self._plan(goal, task_id, db)
            logger.info("[ORCH-DBG] step1 done: dag=%s nodes=%d", getattr(dag, 'id', 'None'), len(dag.nodes) if dag else 0)
            if not dag or not dag.nodes:
                logger.info("[ORCH] No plan for %s; task stays at PLANNING", task_id[:8])
                task = await self._manager.get_task(db, task_id)
                return task

            _sse_event("dag_created", task_id, {
                "dag_id": dag.id,
                "node_count": len(dag.nodes),
            })

            # 2. Assign teammates first (modifies dag.nodes in-memory)
            await self._assign_and_save(db, task_id, dag)
            _sse_event("team_created", task_id, {
                "team_count": len(dag.nodes),
            })

            # 3. Persist DAG to DB (after assignment, so selected_teammate_id is saved)
            await self._persist_dag(db, dag, task_id)
            await db.commit()

            # 4. Create TaskSteps & transition to ASSIGNED
            task = await self._create_steps(db, task_id, dag)
            task = await self._manager.start_assigned(db, task.id)
            await db.commit()

            _sse_event("execution_started", task_id, {
                "step_count": len(dag.nodes),
            })

            # 5. Execute (ASSIGNED → RUNNING → COMPLETED/FAILED)
            try:
                task = await asyncio.wait_for(
                    self._execute(db, task), timeout=120.0
                )
            except asyncio.TimeoutError:
                logger.warning("[ORCH] Execution timed out for %s", task_id[:8])
                task = await self._manager.get_task(db, task_id)
                if task and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    task = await self._manager.fail(db, task_id)
                    await db.flush()
            await db.commit()

            _sse_event("execution_completed", task_id, {
                "status": task.status,
                "error": getattr(task, "error", "")[:200],
            })

            # 6. Closure: Engineer → TechLead → Reviewer → (Fix) auto-relay.
            # Only when the task actually ran an engineer step (has a workspace).
            if task.status == TaskStatus.COMPLETED:
                try:
                    await self._techlead_relay(db, task)
                    await db.commit()
                except Exception as e:
                    logger.warning("[ORCH] techlead_relay failed for %s: %s", task_id[:8], e)
                try:
                    await self._review_relay(db, task)
                    await db.commit()
                except Exception as e:
                    logger.warning("[ORCH] review_relay failed for %s: %s", task_id[:8], e)

            return task
        except Exception as e:
            logger.error("[ORCH] start_task %s failed: %s", task_id[:8], e)
            _sse_event("execution_completed", task_id, {
                "status": "FAILED",
                "error": str(e)[:200],
            })
            try:
                task = await self._manager.get_task(db, task_id)
                if task and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    task = await self._manager.fail(db, task_id)
                    await db.flush()
            except Exception:
                pass
            return task

    # ── Private helpers ──────────────────────────────────────────────

    async def _plan(self, goal: str, task_id: str, db: AsyncSession = None):
        """Try PlanningEngine, fallback to keyword analysis + teammate profiles."""
        engine = PlanningEngine()
        try:
            dag = await asyncio.wait_for(
                engine.plan(
                    goal=goal, context={"task_id": task_id}, task_id=task_id,
                ),
                timeout=15.0,
            )
            if dag and dag.nodes:
                return dag
        except (PlanningError, ImportError, RuntimeError, asyncio.TimeoutError) as e:
            logger.warning("[ORCH] PlanningEngine: %s", e)

        # Fallback: keyword → teammates → DAG
        import sys
        print("[ORCH-FB] Starting fallback...", flush=True)
        analyzer = TaskAnalyzer()
        print("[ORCH-FB] Created analyzer", flush=True)
        analysis = analyzer.analyze(goal)
        print(f"[ORCH-FB] Analysis: type={analysis.task_type}", flush=True)
        skills = SkillRegistry.get_skills(analysis.task_type)
        print(f"[ORCH-FB] Skills: {skills}", flush=True)
        profiles = await TeammateSelector.recommend_by_skills(skills, top_n=3, db=db)
        print(f"[ORCH-FB] Profiles: {len(profiles) if profiles else 0}", flush=True)
        if profiles:
            steps = [
                TaskStepProposal(
                    order=i + 1,
                    teammate_id=p.id,
                    objective=f"{goal} — {p.role or p.name}",
                )
                for i, p in enumerate(profiles)
            ]
            plan = TaskPlan(
                task_id=task_id,
                title=f"Plan: {goal[:60]}",
                description=f"Keyword [{analysis.task_type}]",
                steps=steps,
            )
            return DAGBuilder().build(plan)
        return None

    async def _persist_dag(self, db: AsyncSession, dag, task_id: str) -> None:
        """Save DAGDefinitionModel + DAGNodeModel to DB."""
        dag_model = DAGDefinitionModel(
            id=dag.id,
            name=dag.name or f"dag_{task_id[:8]}",
            status="ACTIVE",
        )
        db.add(dag_model)
        await db.flush()

        for node in dag.nodes.values():
            node_model = DAGNodeModel(
                id=node.id,
                dag_id=dag.id,
                description=node.description,
                teammate=node.teammate or "",
                deps=list(node.deps),
                status="PENDING",
                max_retry=node.max_retry,
                retry_count=node.retry_count,
                strategy=node.strategy,
                require_approval="1" if node.require_approval else "0",
                required_skills=list(node.required_skills),
                selected_teammate_id=node.selected_teammate_id or "",
            )
            db.add(node_model)
        await db.flush()
        logger.info("[ORCH] Persisted DAG %s (%d nodes)", dag.id[:8], len(dag.nodes))

    async def _assign_and_save(self, db: AsyncSession, task_id: str, dag):
        """Assign unassigned teammates and persist the plan."""
        for node in dag.nodes.values():
            if node.required_skills and not node.selected_teammate_id and not node.teammate:
                try:
                    profiles = await TeammateSelector.recommend_by_skills(
                        node.required_skills, top_n=1, db=db,
                    )
                    if profiles:
                        node.selected_teammate_id = profiles[0].id
                        node.teammate = profiles[0].name
                except Exception:
                    pass

        ordered = list(dag.nodes.values())
        plan_steps = [
            {
                "order": i + 1,
                "teammate_id": node.selected_teammate_id or node.teammate or "",
                "objective": node.description,
                "depends_on": [],
                "risk_level": "LOW",
                "requires_approval": node.require_approval,
            }
            for i, node in enumerate(ordered)
        ]
        await self._plan_service.save_plan(
            db, task_id=task_id,
            title=dag.name or f"Plan for {task_id[:8]}",
            description=f"DAG with {len(dag.nodes)} nodes",
            steps=plan_steps,
            confidence=0.8,
        )

    async def _create_steps(self, db: AsyncSession, task_id: str, dag):
        """Create TaskStep records from DAG nodes, carrying DAG deps as step deps."""
        node_to_step: dict[str, str] = {}
        for i, node in enumerate(dag.nodes.values()):
            teammate_id = node.selected_teammate_id or node.teammate or ""
            step = await self._manager.state.create_step(
                db, task_id=task_id, order=i + 1,
                objective=node.description, teammate_id=teammate_id,
            )
            node_to_step[node.id] = step.id
        # Resolve DAG node deps → step deps.
        all_steps = await self._manager.state.list_steps(db, task_id)
        steps_by_node: dict[str, TaskStepModel] = {}
        for node, step in zip(dag.nodes.values(), all_steps):
            steps_by_node[node.id] = step
        for node in dag.nodes.values():
            step = steps_by_node[node.id]
            deps = [node_to_step[d] for d in node.deps if d in node_to_step]
            if deps and deps != list(step.deps or []):
                step.deps = deps  # type: ignore[attr-defined]
        await db.flush()
        return await self._manager.get_task(db, task_id)

    async def _execute(self, db: AsyncSession, task: TaskModel) -> TaskModel:
        """Transition to RUNNING and run through TaskExecutor.

        COMMIT before runtime: the async session's write lock must be
        released so the sync DBExecutionStore (used inside the runtime
        scheduler) can write without blocking the event loop.
        """
        task = await self._manager.start_execution(db, task.id)
        await db.commit()
        if self._runtime is None:
            self._runtime = ExecutionRuntime(max_workers=4)
        executor = TaskExecutor(runtime=self._runtime)
        task = await executor.execute_task(db, task)
        await db.commit()
        return task

    # ── Phase 8: TechLead synthesis relay ──

    async def _techlead_relay(self, db: AsyncSession, task: TaskModel) -> None:
        """After execution, if a TechLead teammate exists, synthesize step results."""
        ws_id = task.workspace_id or ""
        if not ws_id:
            return
        tl = await self._pick_teammate(db, "techlead")
        if tl is None:
            logger.info("[ORCH] No techlead teammate — skipping synthesis for %s", task.id[:8])
            return
        # Collect step outputs
        steps = (await self._manager.state.list_steps(db, task.id)) if hasattr(self._manager, 'state') else []
        if not steps:
            return
        outputs = [{"order": s.order, "objective": s.objective, "output": (s.output or "")[:500], "teammate_id": s.teammate_id}
                   for s in steps if s.output]
        if not outputs:
            return
        # Fire-and-forget synthesis memory
        synthesis_text = json.dumps({"task": task.title, "steps": outputs}, ensure_ascii=False)[:2000]
        asyncio.ensure_future(self._store_review_memory(
            tl.id, task, "synthesis", synthesis_text, round_no=0))
        _sse_event("techlead_synthesis", task.id, {"step_count": len(outputs)})

    # ── Closure: Engineer → Reviewer → Fix relay ──
    # ponytail: no new scheduler/FSM. The orchestrator already owns the
    # lifecycle; we just append a reviewer leg + a child fix task when rejected.

    MAX_REVIEW_ROUNDS = 3

    async def _review_relay(self, db: AsyncSession, task: TaskModel) -> None:
        """After Engineer completes, auto-trigger Reviewer; on reject, spawn a
        fix task assigned to the original engineer (bounded by MAX_REVIEW_ROUNDS)."""
        from sqlalchemy import select
        from backend.models import Teammate

        # Only relay if the task was actually engineered (has a workspace + a
        # reviewer-capable teammate available). Otherwise leave it COMPLETED.
        ws_id = task.workspace_id or ""
        if not ws_id:
            return

        reviewer = await self._pick_teammate(db, role="reviewer")
        if reviewer is None:
            logger.info("[ORCH] No reviewer teammate — skipping review relay for %s", task.id[:8])
            return

        # Ensure the runtime is alive before relaying (it is created in _execute,
        # but guard here so the relay works even if _execute was skipped).
        if self._runtime is None:
            self._runtime = ExecutionRuntime(max_workers=4)
        if not getattr(self._runtime, "_started", False):
            await self._runtime.start()

        engineer = None
        eng_steps = [s for s in (task.steps or []) if s.teammate_id]
        if eng_steps:
            engineer = await self._load_teammate_by_id(db, eng_steps[-1].teammate_id)

        rounds = int(task.review_rounds or 0)
        while rounds < self.MAX_REVIEW_ROUNDS:
            rounds += 1
            # Run reviewer through TaskExecutor (policy → runtime → trace).
            executor = TaskExecutor(runtime=self._runtime)
            try:
                rt = await executor.execute_direct(
                    db,
                    task,
                    description=(task.description or task.title),
                    intent=f"review:{task.id}",
                    teammate_id=reviewer.id,
                    workspace_id=ws_id,
                    git_commit=task.git_commit or "",
                    timeout=120.0,
                )
            except Exception as e:
                logger.warning("[ORCH] Reviewer execution failed for %s: %s", task.id[:8], e)
                break

            verdict = "reject"
            comments = ""
            if rt:
                try:
                    data = json.loads(rt.result or "{}")
                    verdict = "approve" if data.get("verdict") == "approve" else "reject"
                    comments = data.get("summary", "")
                    blockers = data.get("blockers") or []
                    if blockers:
                        comments += "\n\nBlockers:\n- " + "\n- ".join(blockers)
                except Exception:
                    verdict = "reject" if getattr(rt, "review_status", "pending") == "rejected" else "approve"

            task.review_rounds = rounds
            task.review_status = "approved" if verdict == "approve" else "rejected"
            task.review_comments = comments
            await db.flush()
            _sse_event("reviewed", task.id, {"round": rounds, "verdict": verdict})

            # Review experience: persist verdict under the reviewer's scope.
            # ponytail: one direct write, fire-and-forget (non-fatal).
            asyncio.ensure_future(self._store_review_memory(reviewer.id, task, verdict, comments, round_no=rounds))

            # ── Phase 20: REVIEW_REJECTED via HookRegistry ──
            if verdict == "reject" and engineer:
                asyncio.ensure_future(self._fire_review_rejected(
                    db, task, engineer.id, comments, rounds,
                ))

            if verdict == "approve":
                logger.info("[ORCH] Task %s APPROVED at round %d", task.id[:8], rounds)
                return

            # Rejected → create a child fix task, assigned to the original engineer.
            logger.info("[ORCH] Task %s REJECTED (round %d) → spawning fix task", task.id[:8], rounds)
            fix = await self._spawn_fix_task(db, task, engineer, reviewer, comments, round_no=rounds)
            _sse_event("fix_task_created", task.id, {"child_task_id": fix.id, "round": rounds})
            # Child fix task is created and (optionally) executed asynchronously by
            # the caller's background loop. Here we record the edge and stop this
            # relay; the child re-enters start_task on its own.
            return

        # Exhausted rounds — leave task REJECTED (human to intervene).
        task.review_status = "rejected"
        await db.flush()
        logger.warning("[ORCH] Task %s exhausted %d review rounds — left REJECTED", task.id[:8], self.MAX_REVIEW_ROUNDS)

    async def _spawn_fix_task(self, db, parent, engineer, reviewer, comments, round_no: int):
        """Create a child fix task: parent_task + dependency edge, assigned to
        the original engineer. Reuses TaskManager.create_task (no new factory)."""
        title = f"[Fix#{round_no}] {parent.title}"
        fix = await self._manager.create_task(
            db,
            title=title,
            description=(
                f"Reviewer rejected the previous delivery.\n\n"
                f"Original task: {parent.description or parent.title}\n\n"
                f"Review comments:\n{comments}\n\n"
                f"Fix the blockers above and re-deliver."
            ),
            channel_id=parent.channel_id,
            workspace_id=parent.workspace_id,
            priority=parent.priority,
            intent=f"fix:{parent.id}",
            created_by="system",
        )
        # DAG hierarchy fields (requirement §一)
        fix.parent_task_id = parent.id
        fix.dependency = [parent.id]
        # link back on the parent
        parent.child_task_ids = list(parent.child_task_ids or []) + [fix.id]
        await db.flush()
        await db.commit()

        # Auto-run the fix task through the same orchestrator (reusing runtime).
        asyncio.create_task(self._run_child(db_session_factory(), fix.id, fix.intent))
        return fix

    async def _run_child(self, db_factory, task_id: str, goal: str) -> None:
        """Background runner for a child fix task — same pipeline as the parent."""
        from backend.database import async_session
        async with async_session() as db:
            try:
                orch = TaskOrchestrator(runtime=self._runtime)
                await orch.start_task(db, task_id, goal)
                await db.commit()
            except Exception as e:
                logger.warning("[ORCH] child fix task %s failed: %s", task_id[:8], e)

    async def _pick_teammate(self, db: AsyncSession, role: str):
        """Return the first teammate whose role matches (role-specific)."""
        from sqlalchemy import select
        from backend.models import Teammate
        from backend.services.runtime.teammate_runner import detect_role
        res = await db.execute(select(Teammate))
        for t in res.scalars().all():
            d = t.to_dict()
            if detect_role(d) == role:
                return type("T", (), d)()
        return None

    async def _store_review_memory(self, reviewer_id: str, task, verdict: str, comments: str, round_no: int = 0) -> None:
        """Persist a reviewer verdict as a review-scoped teammate memory (fire-and-forget)."""
        try:
            from backend.services.memory.memory_service import get_memory_service
            from backend.services.memory.memory_types import MemoryItem, MemoryType
            svc = get_memory_service()
            await svc.store(MemoryItem(
                memory_type=MemoryType.DECISION,
                content=f"[Review round {round_no}] {task.title}: {verdict}\n{comments}"[:2000],
                source_id=task.id,
                relevance_score=0.7,
                metadata={
                    "event": "REVIEW_VERDICT",
                    "task_id": task.id,
                    "verdict": verdict,
                    "teammate_id": reviewer_id,
                    "scope": "review",
                },
            ))
        except Exception as e:
            logger.debug("[ORCH] review memory skipped (non-fatal): %s", e)

    async def _fire_review_rejected(self, db, task, engineer_id: str, comments: str, round_no: int) -> None:
        """Fire REVIEW_REJECTED event to HookRegistry (replaces direct _reflect_rejection)."""
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
                extra={
                    "teammate_id": engineer_id,
                    "comments": comments,
                    "round_no": round_no,
                },
            )
            await registry.dispatch(TaskLifecycleEvent.REVIEW_REJECTED, ctx)
        except Exception as e:
            logger.debug("[ORCH] REVIEW_REJECTED dispatch failed (non-fatal): %s", e)

    async def _load_teammate_by_id(self, db: AsyncSession, teammate_id: str):
        from sqlalchemy import select
        from backend.models import Teammate
        res = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
        obj = res.scalar_one_or_none()
        return type("T", (), obj.to_dict())() if obj else None


def db_session_factory():
    """Lazy import to avoid circular import at module load."""
    from backend.database import async_session
    return async_session

