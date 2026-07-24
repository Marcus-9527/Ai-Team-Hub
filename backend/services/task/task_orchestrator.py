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
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel, TaskStatus, TaskStepModel,
    DAGDefinitionModel, DAGNodeModel,
    TaskRunModel, TaskRunStatus,
)
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_executor import TaskExecutor
from backend.services.task.task_plan_service import TaskPlanService
from backend.services.planner.planning_engine import PlanningEngine, PlanningError
from backend.services.planner.task_analyzer import TaskAnalyzer
from backend.services.dag.builder import DAGBuilder
from backend.services.teammate_intelligence import SkillRegistry, TeammateSelector
from backend.services.task.task_planner_schema import TaskPlan, TaskStepProposal
from backend.services.runtime.executor import ExecutionRuntime

logger = logging.getLogger("task.orchestrator")

# ── Task-level SSE Broadcaster ──
# Reuses SSEBroadcaster from execution_store. Single instance shared across
# the entire runtime (observability + task lifecycle events). Keyed by task_id.
from backend.services.runtime.execution_store import get_sse_broadcaster
from backend.services.organization.actions import OrganizationAction
from backend.services.organization.task_adapter import TaskActionAdapter


def _sse_event(event_type: str, task_id: str, data: dict) -> None:
    """Fire-and-forget SSE publish. Never blocks the orchestrator."""
    try:
        asyncio.ensure_future(
            get_sse_broadcaster().publish(f"task:{task_id}", event_type, data)
        )
    except Exception:
        pass


class TaskOrchestrator:
    """Chain existing services: plan → persist DAG → assign → run."""

    def __init__(self, runtime: Optional[ExecutionRuntime] = None):
        self._runtime = runtime
        self._manager = TaskManager()
        self._plan_service = TaskPlanService()
        self._adapter: Optional[TaskActionAdapter] = None

    async def start_task(self, db: AsyncSession, task_id: str, goal: str, trigger_id: str = ""):
        """Full pipeline. Task transitions through PENDING→PLANNING→ASSIGNED→RUNNING→done.

        Returns the task with its final status.
        """
        self._trigger_id = trigger_id
        self._adapter = TaskActionAdapter(db, trigger_id=trigger_id)
        task = None
        try:
            await db.flush()
            task = await self._manager.start_planning(db, task_id)
            await db.commit()

            _sse_event("planning_started", task_id, {"goal": goal[:200]})

            # 1. Generate plan (DAG)
            logger.info("[ORCH-DBG] step1: calling _plan with goal=%s", goal[:60])
            dag = await self._plan(goal, task_id, task.workspace_id, db)
            logger.info("[ORCH-DBG] step1 done: dag=%s nodes=%d", getattr(dag, 'id', 'None'), len(dag.nodes) if dag else 0)
            if not dag or not dag.nodes:
                logger.info("[ORCH] No plan for %s; task stays at PLANNING", task_id[:8])
                task = await self._manager.get_task(db, task_id)
                return task

            _sse_event("dag_created", task_id, {
                "dag_id": dag.id,
                "node_count": len(dag.nodes),
            })

            # 1.5 TechLead review (Phase 25) — analysis, risk, teammate recs
            await self._techlead_review(db, task, dag, goal)

            # Phase 27: Create TaskRun for this execution cycle
            task_run = await self._create_run(db, task)

            # 2. Assign teammates first (modifies dag.nodes in-memory)
            await self._assign_and_save(db, task, dag)
            _sse_event("team_created", task_id, {
                "team_count": len(dag.nodes),
            })

            # fail-fast: 任何节点没分到队友就直接 FAILED 并写明原因，
            # 不要带着空 teammate_id 进入执行层（卡到 120s 超时还看不到原因）。
            # ponytail: 一处检查覆盖所有 start_task 调用方。
            unassigned = [
                n for n in dag.nodes.values()
                if not (n.selected_teammate_id or n.teammate)
            ]
            if unassigned:
                task = await self._manager.get_task(db, task_id)
                reason = (
                    f"无法分配队友：{len(unassigned)}/{len(dag.nodes)} 个步骤没有可用队友"
                    f"（队友列表为空、全部离线或认领锁冲突）。"
                )
                task.error = reason
                await db.flush()
                task = await self._manager.fail(db, task_id)
                await db.commit()
                _sse_event("execution_completed", task_id, {
                    "status": "FAILED",
                    "error": reason,
                })
                return task

            # 3. Persist DAG to DB (after assignment, so selected_teammate_id is saved)
            await self._persist_dag(db, dag, task_id)
            await db.commit()

            # 4. Create TaskSteps & transition to ASSIGNED
            task = await self._create_steps(db, task_id, dag, task_run.id)
            task = await self._manager.start_assigned(db, task.id)
            await db.commit()

            _sse_event("execution_started", task_id, {
                "step_count": len(dag.nodes),
            })

            # 5. Execute (ASSIGNED → RUNNING → COMPLETED/FAILED)
            await self._adapter.emit_start(OrganizationAction.EXECUTE, task_id=task_id)
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
                await self._adapter.emit_end(OrganizationAction.EXECUTE, error="Execution timed out")
            else:
                await self._adapter.emit_end(OrganizationAction.EXECUTE)
            await db.commit()

            _sse_event("execution_completed", task_id, {
                "status": task.status,
                "error": getattr(task, "error", "")[:200],
            })

            # 6a. Phase 27: emit replan events if TechLead adapted the plan
            if getattr(task, "replan_decisions", None):
                for i, rd in enumerate(task.replan_decisions):
                    _sse_event("replan_decision", task_id, {
                        "index": i,
                        "step_id": rd.get("step_id", ""),
                        "reasoning": rd.get("reasoning", ""),
                        "total_replans": len(task.replan_decisions),
                    })

            # 6b. Closure: Engineer → TechLead → Reviewer → (Fix) auto-relay.
            # Only when the task actually ran an engineer step (has a workspace).
            if task.status == TaskStatus.COMPLETED:
                try:
                    await self._techlead_relay(db, task)
                    await db.commit()
                except Exception as e:
                    logger.warning("[ORCH] techlead_relay failed for %s: %s", task_id[:8], e)
                try:
                    await self._adapter.emit_start(OrganizationAction.REVIEW, task_id=task_id)
                    await self._review_relay(db, task)
                    await self._adapter.emit_end(OrganizationAction.REVIEW)
                    await db.commit()
                except Exception as e:
                    await self._adapter.emit_end(OrganizationAction.REVIEW, error=str(e)[:200])
                    logger.warning("[ORCH] review_relay failed for %s: %s", task_id[:8], e)

            # Phase 27: Finalize TaskRun
            try:
                task_run = await db.get(TaskRunModel, task.current_run_id)
                if task_run:
                    self._finalize_run(task, task_run)
                    await db.flush()
            except Exception:
                pass

            # Phase 2.2: COMPLETE action
            await self._adapter.emit_start(OrganizationAction.COMPLETE, task_id=task_id)
            await self._adapter.emit_end(OrganizationAction.COMPLETE)

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
                # Phase 27: Finalize TaskRun on error
                run_id = getattr(task, 'current_run_id', None)
                if run_id:
                    task_run = await db.get(TaskRunModel, run_id)
                    if task_run:
                        task_run.status = TaskRunStatus.FAILED
                        task_run.completed_at = datetime.now(timezone.utc)
                        task_run.error = str(e)[:2000]
                        await db.flush()
            except Exception:
                pass
            return task

    # ── Private helpers ──────────────────────────────────────────────

    async def _plan(self, goal: str, task_id: str, workspace_id: str = "", db: AsyncSession = None):
        """Try PlanningEngine, fallback to keyword analysis + teammate profiles."""
        await self._adapter.emit_start(OrganizationAction.PLAN)

        engine = PlanningEngine()

        # Resolve workspace-scoped API key using the caller's db session
        # (avoid opening a new session inside the planning engine → SQLite deadlock).
        api_key = ""
        provider = "openrouter"
        if workspace_id and db is not None:
            from backend.services.runtime.teammate_runner import resolve_workspace_api_key
            resolved = await resolve_workspace_api_key(workspace_id, db_session=db)
            if resolved:
                api_key, _, provider = resolved
                provider = provider or "openrouter"
                logger.info("[ORCH] resolved key for ws=%s (len=%d prov=%s)",
                             workspace_id[:12], len(api_key), provider)
            if not api_key:
                await self._adapter.emit_end(
                    OrganizationAction.PLAN,
                    error="Workspace has no active API key configured",
                )
                raise RuntimeError(
                    f"Workspace {workspace_id[:12]}... has no active API key configured."
                )

        try:
            dag = await asyncio.wait_for(
                engine.plan(
                    goal=goal, context={"task_id": task_id}, task_id=task_id,
                    api_key=api_key,
                    provider=provider,
                ),
                timeout=15.0,
            )
            if dag and dag.nodes:
                await self._adapter.emit_end(OrganizationAction.PLAN)
                return dag
        except (PlanningError, ImportError, RuntimeError, ValueError, asyncio.TimeoutError) as e:
            logger.warning("[ORCH] PlanningEngine: %s", e)

        # Fallback: keyword → teammates → DAG
        import sys
        print("[ORCH-FB] Starting fallback...", flush=True)
        analyzer = TaskAnalyzer()
        print("[ORCH-FB] Created analyzer", flush=True)
        analysis = await asyncio.to_thread(analyzer.analyze, goal)
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
            dag = DAGBuilder().build(plan)
            await self._adapter.emit_end(OrganizationAction.PLAN)
            return dag
        await self._adapter.emit_end(OrganizationAction.PLAN)
        return None

    async def _persist_dag(self, db: AsyncSession, dag, task_id: str) -> None:
        """Save DAGDefinitionModel + DAGNodeModel to DB."""
        dag_model = DAGDefinitionModel(
            id=dag.id,
            name=dag.name or f"dag_{task_id[:8]}",
            status="ACTIVE",
            task_id=task_id,
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

    async def _assign_and_save(self, db: AsyncSession, task: TaskModel, dag):
        """Assign unassigned teammates and persist the plan.

        Phase 24: TeammateSelector → TaskClaim lock → assignment.
        Phase 26: TechLead recommendation override → selector support + validation.
        ponytail: every node MUST end up with a teammate. If DB has no
        teammates (or all offline / all claims lost) the round-robin fallback
        can't assign anyone — start_task fails fast on that (see after
        _assign_and_save), so we don't carry an empty teammate_id into the
        runtime and hang at PLANNING.
        """
        task_id = task.id
        # Lazy-load all teammates once, for the round-robin fallback.
        from sqlalchemy import select
        from backend.models import Teammate as _TM
        all_tm = (await db.execute(select(_TM))).scalars().all()
        tm_cycle = iter(all_tm) if all_tm else iter(())

        # Phase 24: claim manager for lock-based assignment
        from backend.services.autonomous.task_claim import get_claim_manager
        claim_mgr = get_claim_manager()

        # Phase 26: parse TechLead teammate recommendations
        # Format: [{"step": 1, "teammate": "name", "confidence": 0.85, ...}]
        # Resolve all recommendations upfront: step (1-based) → (teammate_id, confidence)
        tl_map: dict[int, tuple[str, float]] = {}
        if task.techlead_decision:
            for r in task.techlead_decision.get("teammate_recommendations", []):
                step_idx = r.get("step")
                if not step_idx or step_idx < 1 or step_idx > len(dag.nodes.values()):
                    continue
                tm = (await db.execute(
                    select(_TM).where(_TM.name == r.get("teammate", ""))
                )).scalar_one_or_none()
                if tm:
                    # Phase 26.5: offline guard — skip override so selector falls back
                    from backend.services.autonomous.teammate_state import get_state_manager
                    _st = await get_state_manager().get(tm.id)
                    if _st and _st.state.value == "offline":
                        logger.info("[ORCH] TL rec '%s' offline — fallback", tm.name)
                        continue
                    tl_map[step_idx] = (tm.id, r.get("confidence", 0.5))
                else:
                    logger.info("[ORCH] TL rec '%s' for step %d not found — fallback",
                                r.get("teammate"), step_idx)

        # C: await the TASK_CREATED claim competition here, before assigning.
        # ponytail: the wakeup handler only *triggers* it (fire-and-forget);
        # we await the same helper so we don't bet on which background task
        # reaches claim() first. Execution still runs exactly once via
        # _background_orchestrate.
        from backend.services.autonomous.task_claim_subscriber import (
            run_claim_competition,
        )
        await run_claim_competition(task_id)

        from backend.services.autonomous.task_claim import get_claim_manager
        claim_mgr = get_claim_manager()

        for i, node in enumerate(dag.nodes.values()):
            if node.selected_teammate_id or node.teammate:
                continue
            try:
                # A: honor an existing claim for this task before the selector.
                # ponytail: claim is per-task (not per-node); first claimant
                # wins the whole task. If a teammate already holds the claim,
                # pin every unassigned node to them and skip selector/self-claim.
                claims = await claim_mgr.get_claims(task_id)
                claimed = [c for c in claims if c.status == "claimed"]
                if claimed:
                    owner = claimed[0].teammate_id
                    logger.info("[ORCH] existing claim on %s → owner %s",
                                task_id[:8], owner[:8])
                    node.selected_teammate_id = owner
                    node.teammate = owner
                    continue

                # Phase 26: check TechLead recommendation for this step
                tl_rec_id = tl_map.get(i + 1)

                kwargs: dict = {"top_n": 3, "db": db}
                if tl_rec_id:
                    kwargs["techlead_override"] = tl_rec_id

                if node.required_skills:
                    profiles = await TeammateSelector.recommend_by_skills(
                        node.required_skills, **kwargs,
                    )
                else:
                    profiles = await TeammateSelector.recommend_by_skills([], **kwargs)

                if profiles:
                    # Phase 24: claim-based lock — first claimant wins
                    for p in profiles:
                        ok, _ = await claim_mgr.claim(
                            task_id, p.id, p.name,
                            f"auto-assign via selector",
                        )
                        if ok:
                            node.selected_teammate_id = p.id
                            node.teammate = p.name
                            break
                if node.selected_teammate_id:
                    continue

                # ponytail: no skill match (or no skills) → any teammate
                nxt = next(tm_cycle, None)
                if nxt is None and all_tm:
                    tm_cycle = iter(all_tm)
                    nxt = next(tm_cycle, None)
                if nxt:
                    # Phase 24: round-robin fallback also goes through claim
                    ok, _ = await claim_mgr.claim(task_id, nxt.id, nxt.name, "round-robin fallback")
                    if ok:
                        node.selected_teammate_id = nxt.id
                        node.teammate = nxt.name
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

    async def _create_steps(self, db: AsyncSession, task_id: str, dag, run_id: str = ""):
        """Create TaskStep records from DAG nodes, carrying DAG deps as step deps."""
        node_to_step: dict[str, str] = {}
        for i, node in enumerate(dag.nodes.values()):
            teammate_id = node.selected_teammate_id or node.teammate or ""
            step = await self._manager.state.create_step(
                db, task_id=task_id, order=i + 1,
                objective=node.description, teammate_id=teammate_id,
            )
            # Phase 27: associate step with run
            if run_id:
                step.run_id = run_id
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
        """Transition to RUNNING and run through TaskExecutor."""
        task = await self._manager.start_execution(db, task.id)
        await db.commit()
        if self._runtime is None:
            self._runtime = ExecutionRuntime(max_workers=4)
        executor = TaskExecutor(runtime=self._runtime, trigger_id=self._trigger_id)
        task = await executor.execute_task(db, task)
        await db.commit()
        return task

    # ── Phase 25: TechLead review (post-plan, before assign) ──

    async def _techlead_review(self, db: AsyncSession, task: TaskModel, dag, goal: str) -> None:
        """Call TechLead to review the DAG plan: analysis, risk, teammate recs.

        Saves structured decision to task.techlead_decision (JSON).
        Non-blocking: failures are logged, not fatal.
        """
        tl = await self._pick_teammate(db, "techlead")
        if tl is None:
            logger.info("[ORCH] No techlead teammate — skipping review for %s", task.id[:8])
            return

        # Build prompt with DAG context
        nodes_text = "\n".join(
            f"{i+1}. {n.description}" for i, n in enumerate(dag.nodes.values())
        )

        # Load available teammates for recommendation context
        from sqlalchemy import select
        from backend.models import Teammate
        tm_rows = (await db.execute(select(Teammate))).scalars().all()
        teammates_text = "\n".join(
            f"  {t.name} (role={t.role}, id={t.id[:8]})" for t in tm_rows
        )

        prompt = (
            f"You are TechLead reviewing a task plan.\n\n"
            f"## Task Goal\n{goal}\n\n"
            f"## Planned Steps\n{nodes_text}\n\n"
            f"## Available Teammates\n{teammates_text}\n\n"
            f"Respond ONLY with valid JSON. No markdown, no code fences:\n"
            f"{{\n"
            f'  "analysis": "brief task analysis",\n'
            f'  "confidence": 0.85,\n'
            f'  "risk_level": "LOW",\n'
            f'  "risk_factors": ["list", "risk", "factors"],\n'
            f'  "teammate_recommendations": [\n'
            f'    {{"step": 1, "teammate": "name", "confidence": 0.85, "reasoning": "why"}}\n'
            f'  ],\n'
            f'  "overall_reasoning": "summary of selection reasoning"\n'
            f"}}"
        )

        # ── Phase 2.2: action timeline for techlead review ──
        await self._adapter.emit_start(OrganizationAction.REVIEW)

        executor = TaskExecutor(runtime=self._runtime)
        try:
            rt = await executor.execute_direct(
                db, task=task,
                description=prompt,
                intent=f"techlead_review:{task.id}",
                teammate_id=tl.id,
                workspace_id=task.workspace_id or "",
                timeout=60.0,
            )
            if rt and rt.result:
                decision = json.loads(rt.result)
                if isinstance(decision, dict):
                    task.techlead_decision = decision
                    _sse_event("techlead_review", task.id, decision)
                    logger.info("[ORCH] TechLead review saved for %s", task.id[:8])
                    # Phase 26: HIGH risk → auto-require reviewer via policy
                    if decision.get("risk_level") == "HIGH":
                        try:
                            from backend.services.task.task_policy import TaskPolicyService
                            await TaskPolicyService().upsert_policy(
                                db, task.id, approval_required="1",
                            )
                            logger.info("[ORCH] TechLead HIGH risk → policy approval_required for %s", task.id[:8])
                        except Exception:
                            pass
            await self._adapter.emit_end(OrganizationAction.REVIEW)
        except Exception as e:
            await self._adapter.emit_end(OrganizationAction.REVIEW, error=str(e)[:500])
            logger.warning("[ORCH] TechLead review failed for %s: %s", task.id[:8], e)

    # ── Phase 25: TechLead synthesis relay (post-execution) ──

    async def _techlead_relay(self, db: AsyncSession, task: TaskModel) -> None:
        """After execution: write Brain fragment + task summary + SSE event."""
        ws_id = task.workspace_id or ""
        if not ws_id:
            return
        tl = await self._pick_teammate(db, "techlead")
        if tl is None:
            logger.info("[ORCH] No techlead teammate — skipping synthesis for %s", task.id[:8])
            return
        steps = (await self._manager.state.list_steps(db, task.id)) if hasattr(self._manager, 'state') else []
        if not steps:
            return
        outputs = [{"order": s.order, "objective": s.objective, "output": (s.output or "")[:500], "teammate_id": s.teammate_id}
                   for s in steps if s.output]
        if not outputs:
            return

        synthesis = {"title": task.title, "status": task.status, "steps": outputs}
        synthesis_json = json.dumps(synthesis, ensure_ascii=False)

        # 1) Write Brain fragment (DECISIONS) — TechLead's persistent self-knowledge
        try:
            from backend.services.brain.fragment_store import get_brain_fragment_store, BrainFragment, BrainFragmentType
            frag = BrainFragment(
                teammate_id=tl.id,
                fragment_type=BrainFragmentType.DECISIONS,
                content=f"Task synthesis [{task.id[:8]}]: {synthesis_json[:2000]}",
                source="techlead_relay",
            )
            asyncio.ensure_future(get_brain_fragment_store().store(frag))
        except Exception:
            pass

        # 2) Write human-readable summary on the task itself
        try:
            lines = []
            for s in outputs:
                preview = (s["output"] or "")[:200].replace("\n", " ")
                lines.append(f"Step {s['order']} ({s['teammate_id'][:8]}): {preview}")
            task.techlead_summary = "\n".join(lines)[:5000]
        except Exception:
            task.techlead_summary = synthesis_json[:2000]

        # 3) SSE event
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


    # ── Phase 27: TaskRun lifecycle ──

    async def _create_run(self, db: AsyncSession, task: TaskModel) -> TaskRunModel:
        """Create a new TaskRun and link it to the task."""
        from sqlalchemy import select, func
        result = await db.execute(
            select(func.max(TaskRunModel.run_number)).where(
                TaskRunModel.task_id == task.id
            )
        )
        max_run = result.scalar() or 0
        task_run = TaskRunModel(
            task_id=task.id,
            run_number=max_run + 1,
            status=TaskRunStatus.PENDING,
            started_at=datetime.now(timezone.utc),
        )
        db.add(task_run)
        await db.flush()
        task.current_run_id = task_run.id
        await db.flush()
        _sse_event("run_created", task.id, {
            "run_id": task_run.id,
            "run_number": task_run.run_number,
        })
        return task_run

    def _finalize_run(self, task: TaskModel, task_run: TaskRunModel) -> None:
        """Update TaskRun status based on task outcome."""
        task_run.completed_at = datetime.now(timezone.utc)
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            task_run.status = (
                TaskRunStatus.COMPLETED
                if task.status == TaskStatus.COMPLETED
                else TaskRunStatus.FAILED
            )
        if task.error:
            task_run.error = task.error[:2000]


def _utc_timestamp() -> datetime:
    """ISO-8601 timestamp for log messages."""
    return datetime.now(timezone.utc)


def db_session_factory():
    """Lazy import to avoid circular import at module load."""
    from backend.database import async_session
    return async_session
