"""
task_executor.py — Task Executor (MAEOS Integration)

Orchestrates sequential execution of TaskSteps through the MAEOS Runtime.

v2.5 Hardening:
  - Retry support via runtime/retry_policy.py
  - Execution tracing via TraceLogger
  - Lifecycle events via TaskEventLogger
  - Cost tracking (input/output tokens, estimated cost)
  - Start/end timestamps per execution

Constraints:
  - All agent execution MUST go through MAEOS (no direct LLM calls)
  - No modification of MAEOS core logic
  - Sequential step execution (Phase B v1)
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskStatus,
    TaskStepStatus,
)
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_context import TaskContextBuilder
from backend.services.task.task_result import (
    TaskResultHandler,
    estimate_cost,
)
from backend.services.task.task_events import TaskEventLogger
from backend.services.task.task_approval_service import TaskApprovalService
from backend.services.task.task_policy import TaskPolicyService
from backend.services.runtime.retry_policy import (
    RetryPolicy,
    BackoffStrategy,
    FailureType,
)
from backend.services.runtime.trace import TraceLogger
from backend.services.runtime.executor import ExecutionRuntime, ExecStatus as RuntimeExecStatus

logger = logging.getLogger("task.executor")


class ApprovalRequiredError(Exception):
    """Raised when a step requires human approval (task is PAUSED)."""
    pass


class PolicyBlockedError(Exception):
    """Raised when a step is blocked by task policy (risk level / teammate / retry)."""
    pass


class TaskExecutor:
    """
    Executes all steps of a Task sequentially through MAEOS.

    Each step is submitted as a separate MAEOS task, waited on,
    and its result is recorded before the next step begins.
    """

    def __init__(self, runtime: Optional[ExecutionRuntime] = None, retry_policy: Optional[RetryPolicy] = None, trigger_id: str = ""):
        self.state = TaskStateManager()
        self.context_builder = TaskContextBuilder()
        self.result_handler = TaskResultHandler()
        self.approval = TaskApprovalService()
        self.policy = TaskPolicyService()
        self._runtime = runtime  # ExecutionRuntime singleton
        self._trigger_id = trigger_id
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=2,
            backoff_strategy=BackoffStrategy.LINEAR,
            base_delay_ms=2000,
        )

    def set_runtime(self, runtime: ExecutionRuntime) -> None:
        """Set the ExecutionRuntime instance (call before execute_task)."""
        self._runtime = runtime

    # ── Main Entry Point ──

    async def execute_task(
        self,
        db: AsyncSession,
        task: TaskModel,
    ) -> TaskModel:
        """
        Execute all PENDING steps of a task sequentially.

        Args:
            db: Database session
            task: The task to execute (must have steps loaded)

        Returns:
            The updated task (COMPLETED or FAILED)

        Raises:
            RuntimeError: If MAEOS is not set
            ValueError: If task is not in EXECUTING state
        """
        if self._runtime is None:
            raise RuntimeError("ExecutionRuntime not set. Call set_runtime() first.")

        if task.status not in (TaskStatus.RUNNING, TaskStatus.EXECUTING):
            raise ValueError(
                f"Task must be in RUNNING (or EXECUTING) state, got {task.status}"
            )

        # Initialize trace + event loggers
        trace_id = str(uuid.uuid4())
        trace = TraceLogger(trace_id=trace_id, task_id=task.id)
        events = TaskEventLogger(task_id=task.id, task=task)

        events.log_started()

        # Get steps ordered by `order`
        steps = await self.state.list_steps(db, task.id)
        pending_steps = [s for s in steps if s.status == TaskStepStatus.PENDING]

        if not pending_steps:
            if not steps:
                # No steps at all → can't complete vacuuously
                logger.warning(f"[EXECUTOR] Task {task.id} has no steps — marking FAILED")
                task = await self.result_handler.handle_task_failure(db, task)
                events.log_failed(reason="No steps planned — cannot execute empty task")
                return task
            logger.info(f"[EXECUTOR] No pending steps for task {task.id}")
            if all(s.status == TaskStepStatus.COMPLETED for s in steps):
                task = await self.result_handler.handle_task_completion(db, task)
                events.log_completed(total_steps=len(steps))
            return task

        # ── DAG ready-batch execution (Plan A) ──
        # Reuses the SAME ExecutionRuntime. Each ready batch is submitted in a
        # fast serial pass (runtime.submit is non-blocking), then waited on
        # concurrently (asyncio.gather) so the runtime's N workers run the LLM
        # calls in parallel. Results are persisted back on this single db
        # session (serial, fast). Steps whose deps are unmet stay PENDING.
        # ponytail: only the slow LLM wait overlaps; DB writes are serial (they
        # were already fast). Per-step policy/approval/retry preserved.
        overall_success = True
        remaining = {s.id: s for s in pending_steps}
        done_ids: set[str] = set()

        while remaining:
            ready = [
                s for s in remaining.values()
                if all(d in done_ids for d in (s.deps or []))
            ]
            if not ready:
                logger.warning(
                    "[EXECUTOR] Task %s has %d step(s) blocked by unmet deps",
                    task.id[:8], len(remaining),
                )
                break

            # Submit pass (fast, serial): policy gate + runtime.submit per step.
            try:
                submitted = [
                    (s, await self._submit_one(db, task, s, trace, events))
                    for s in ready
                ]
            except ApprovalRequiredError:
                logger.info(
                    "[EXECUTOR] Task %s paused for approval at step %s",
                    task.id[:8], ready[0].id[:8],
                )
                overall_success = True  # PAUSED, not failed
                break
            except PolicyBlockedError as e:
                logger.warning("[EXECUTOR] Task %s blocked by policy", task.id[:8])
                overall_success = False
                break

            # Wait pass (slow, parallel): gather ALL ready waits at once.
            # NO DB writes happen inside — each coroutine only does runtime.wait.
            logger.info(
                "[EXECUTOR][GATHER] ENTER batch wait: %d ready step(s): %s",
                len(submitted),
                [s.id[:8] for s, _ in submitted],
            )
            try:
                results = await asyncio.gather(*[
                    self._wait_parallel(rtid) for s, rtid in submitted
                ])
                for (s, _), rt in zip(submitted, results):
                    s._rt_result = rt  # type: ignore[attr-defined]
                logger.info(
                    "[EXECUTOR][GATHER] RETURN: %d result(s), statuses=%s",
                    len(results),
                    [getattr(rt, "status", None) for rt in results],
                )
            except Exception as e:
                logger.error("[EXECUTOR] batch wait failed: %s", e)
                overall_success = False
                break

            # Finalize pass (fast, serial): all DB writes on this one session.
            try:
                for s, rtid in submitted:
                    await self._finalize_step(db, task, s, rtid, trace, events)
            except Exception as e:
                logger.error("[EXECUTOR] batch finalize failed: %s", e)
                overall_success = False
                break

            progressed = False
            for s in ready:
                if s.status == TaskStepStatus.COMPLETED:
                    done_ids.add(s.id)
                    remaining.pop(s.id, None)
                    progressed = True
                elif s.status == TaskStepStatus.FAILED:
                    overall_success = False
                    break  # downstream steps stay PENDING; stop scheduling
            if not overall_success:
                break
            if not progressed:
                break  # safety: no step resolved, avoid infinite loop

        if overall_success:
            task = await self.result_handler.handle_task_completion(db, task)
            events.log_completed(total_steps=len(steps))
        else:
            task = await self.result_handler.handle_task_failure(db, task)
            events.log_failed(reason="Step execution failed after retries")

        trace.log_workflow_complete(
            final_state=task.status,
            total_latency_ms=0,
            total_retries=0,
            result_length=0,
        )
        return task

    # ── Step split: submit (fast, serial) / wait+finalize (parallel) ──

    async def _submit_one(
        self,
        db: AsyncSession,
        task: TaskModel,
        step: TaskStepModel,
        trace: TraceLogger,
        events: TaskEventLogger,
    ) -> str:
        """Policy gate + transition RUNNING + runtime.submit. Returns runtime_task_id.

        Raises ApprovalRequiredError / PolicyBlockedError for the batch driver.
        """
        step_id_short = step.id[:8]
        attempt = 1  # first attempt

        policy_result = await self.policy.evaluate_step(db, task, step)
        if not policy_result.allowed:
            logger.warning(
                f"[EXECUTOR] Step {step_id_short} blocked by policy: "
                f"{policy_result.blocked_reason}"
            )
            if events:
                events.log_policy_blocked(
                    step_id=step.id, step_order=step.order,
                    reason=policy_result.blocked_reason,
                )
            raise PolicyBlockedError(policy_result.blocked_reason)

        if policy_result.requires_approval:
            logger.info(
                f"[EXECUTOR] Step {step_id_short} requires human approval — pausing"
            )
            await self.approval.create_approval(
                db, task, step,
                reason=f"Policy: step {step.order} ({step.objective[:100]})",
                events=events,
            )
            raise ApprovalRequiredError(
                f"Step {step.id} (order={step.order}) requires approval"
            )

        context = await self.context_builder.build_maeos_description(db, task, step)
        step = await self.state.transition_step_status(db, step, TaskStepStatus.RUNNING)
        # ponytail: release transaction so the next step's SELECT on the same
        # session doesn't hang on a dirty connection. expire_on_commit=False
        # keeps ORM objects accessible after commit.
        await db.commit()
        events.log_step_started(
            step_id=step.id, step_order=step.order, attempt=attempt,
            teammate_id=step.teammate_id or "",
        )
        # ponytail: don't pre-resolve the key here — runtime._run_task already
        # loads the teammate and calls resolve_api_key(teammate) with the same
        # workspace-isolated scoping. Passing teammate+workspace_id is enough;
        # a second resolver here was dead-code duplication (and referenced an
        # unimported _load_teammate → NameError that silently dropped the key).
        runtime_task_id = await self._runtime.submit(
            description=context,
            priority=task.priority,
            intent=f"task_step:{task.id}",
            teammate=step.teammate_id or "",
            workspace_id=task.workspace_id or "",
            wait=False,
        )
        trace.log_teammate_dispatch(
            teammate_id=step.teammate_id or "",
            state=TaskStepStatus.RUNNING,
            input_snapshot={"objective": step.objective[:200], "context_len": len(context)},
            attempt=attempt,
        )
        # Stash context on the step object for the wait/finalize pass.
        step._exec_context = context  # type: ignore[attr-defined]
        return runtime_task_id

    async def _wait_parallel(
        self,
        runtime_task_id: str,
    ):
        """Wait on a submitted step. NO DB writes — safe to run concurrently.

        Returns the completed RuntimeTask. The DB-persisting finalize step runs
        serially afterwards (see _finalize_step) so a single AsyncSession is
        never written from two coroutines at once.
        """
        rt = await self._runtime.wait(runtime_task_id, timeout=300.0)
        return rt

    async def _finalize_step(
        self,
        db: AsyncSession,
        task: TaskModel,
        step: TaskStepModel,
        runtime_task_id: str,
        trace: TraceLogger,
        events: TaskEventLogger,
    ) -> None:
        """Serialize DB writes + retry loop for one step. Runs AFTER the parallel
        wait batch. One step at a time on this session — no concurrency here."""
        step_id_short = step.id[:8]
        teammate_id = step.teammate_id or ""
        context = getattr(step, "_exec_context", "")
        attempt = 1
        max_attempts = self.retry_policy.max_retries + 1

        # ── Phase 2.2: SessionTurn per step ──
        _step_turn = None
        if self._trigger_id:
            from backend.services.session.session_hooks import SessionHooks
            _step_hooks = SessionHooks(db)
            _step_turn = await _step_hooks.start_turn(self._trigger_id, teammate_id=teammate_id)
            _step_turn.turn_type = "task"
            await db.flush()

        # ── OrganizationState: step start ──
        if task.run_id:
            _step_state_key = f"step:{step.id}"
            from backend.services.organization.state import OrganizationStateService
            _step_state_svc = OrganizationStateService(db)
            await _step_state_svc.set_state(
                task.run_id, "progress", _step_state_key,
                {"status": "running", "order": step.order, "objective": step.objective[:200]},
            )

        while attempt <= max_attempts:
            logger.info(
                f"[EXECUTOR] Step {step_id_short} (order={step.order}, "
                f"attempt {attempt}/{max_attempts}): {step.objective[:60]}"
            )
            start_time = time.time()

            execution = await self.result_handler.record_execution(
                db, step,
                maeos_task_id=runtime_task_id,
                attempt=attempt,
                trace_id=trace.trace_id,
                teammate_id=teammate_id,
            )

            if _step_turn and _step_turn.execution_id is None:
                _step_turn.execution_id = execution.id
                await db.flush()

            # First wait already done in the parallel batch; reuse its result,
            # but on retry we must wait again (serial — fine, retries are rare).
            runtime_task = getattr(step, "_rt_result", None) if attempt == 1 else None
            if runtime_task is None:
                runtime_task = await self._runtime.wait(runtime_task_id, timeout=300.0)

            end_time = time.time()
            duration_ms = self.result_handler.calculate_duration(start_time, end_time)

            if runtime_task and runtime_task.status == RuntimeExecStatus.COMPLETED:
                result_text = runtime_task.result or ""
                inp_tok, out_tok, tot_tok, cost_micro = estimate_cost(
                    input_text=context, output_text=result_text,
                )
                await self.result_handler.handle_step_success(
                    db, step, result_text, runtime_task_id, duration_ms
                )
                await self._persist_closure(db, task, runtime_task)
                await self.result_handler.update_execution_result(
                    db, execution,
                    output=result_text,
                    execution_time_ms=duration_ms,
                    trace_id=trace.trace_id,
                    input_tokens=inp_tok,
                    output_tokens=out_tok,
                    total_tokens=tot_tok,
                    estimated_cost_value=cost_micro,
                )
                trace.log_teammate_result(
                    teammate_id=teammate_id,
                    state=TaskStepStatus.COMPLETED,
                    output_snapshot={"length": len(result_text), "preview": result_text[:200]},
                    latency_ms=duration_ms,
                    attempt=attempt,
                )
                events.log_step_completed(
                    step_id=step.id, step_order=step.order, attempt=attempt,
                    duration_ms=duration_ms, output_length=len(result_text),
                )
                logger.info(
                    f"[EXECUTOR] Step {step_id_short} COMPLETED in {duration_ms}ms "
                    f"({len(result_text)} chars, {tot_tok} tokens, ${cost_micro / 1_000_000:.6f})"
                )
                if _step_turn:
                    await _step_hooks.close_turn(_step_turn.id, action=TurnAction.RESPONDED,
                        tokens_in=inp_tok, tokens_out=out_tok)
                # ── OrganizationState: step completed ──
                if task.run_id:
                    await _step_state_svc.set_state(
                        task.run_id, "progress", _step_state_key,
                        {"status": "completed", "duration_ms": duration_ms},
                    )
                return

            error_msg = runtime_task.error if runtime_task else "ExecutionRuntime timeout"
            if not error_msg:
                error_msg = "Unknown execution error"

            failure_type = self.retry_policy.classify(error_msg, validation_failed=False)
            decision = self.retry_policy.decide(_ExecUnitProxy(attempt=attempt, error=error_msg))
            trace.log_failure_classified(
                teammate_id=teammate_id,
                state=TaskStepStatus.FAILED,
                failure_type=failure_type.value,
                error=error_msg,
                action=decision.action,
            )

            if decision.action == "retry":
                await self.result_handler.update_execution_result(
                    db, execution, error=error_msg, execution_time_ms=duration_ms,
                )
                step = await self.result_handler.handle_step_failure(db, step, error_msg, runtime_task_id)
                await self.result_handler.update_step_retry_count(db, step, attempt)
                events.log_step_failed(
                    step_id=step.id, step_order=step.order, attempt=attempt,
                    error=error_msg, will_retry=True,
                )
                # ── Phase 27.5: Early replan for tool failures ──
                if failure_type == FailureType.SYSTEM_FAIL and attempt == 1:
                    replan = await self._trigger_replan(db, task, step, error_msg)
                    handled = await self._apply_replan(db, task, step, replan, trace, events, error_msg)
                    if handled:
                        if _step_turn:
                            await _step_hooks.close_turn(_step_turn.id, action=TurnAction.RESPONDED)
                        return
                logger.warning(
                    f"[EXECUTOR] Step {step_id_short} attempt {attempt} FAILED "
                    f"({failure_type.value}). Retrying in {decision.delay_ms}ms..."
                )
                await asyncio.sleep(decision.delay_ms / 1000.0)
                step = await self.state.transition_step_status(db, step, TaskStepStatus.PENDING)
                attempt += 1
                continue

            await self.result_handler.update_execution_result(
                db, execution, error=error_msg, execution_time_ms=duration_ms,
            )
            await self.result_handler.handle_step_failure(db, step, error_msg, runtime_task_id)
            events.log_step_failed(
                step_id=step.id, step_order=step.order, attempt=attempt,
                error=error_msg, will_retry=False,
            )
            # ── Phase 27: TechLead replan before abort ──
            replan = await self._trigger_replan(db, task, step, error_msg)
            if await self._apply_replan(db, task, step, replan, trace, events, error_msg):
                if _step_turn:
                    await _step_hooks.close_turn(_step_turn.id, action=TurnAction.RESPONDED)
                return

            logger.error(f"[EXECUTOR] Step {step_id_short} ABORTED: {error_msg}")
            if _step_turn:
                _step_turn.failure = error_msg[:2000]
                _step_turn.end_time = datetime.now(timezone.utc)
                await db.flush()
            # ── OrganizationState: step failed ──
            if task.run_id:
                await _step_state_svc.set_state(
                    task.run_id, "progress", _step_state_key,
                    {"status": "failed", "error": error_msg[:500]},
                )
            raise RuntimeError(f"Step {step.id} failed (action={decision.action}): {error_msg}")

        if _step_turn:
            _step_turn.failure = f"Step {step.id} failed after {max_attempts} attempts"
            _step_turn.end_time = datetime.now(timezone.utc)
            await db.flush()
        # ── OrganizationState: step failed after retries ──
        if task.run_id and _step_state_key:
            await _step_state_svc.set_state(
                task.run_id, "progress", _step_state_key,
                {"status": "failed", "error": f"Failed after {max_attempts} attempts"},
            )
        raise RuntimeError(f"Step {step.id} failed after {max_attempts} attempts")

    # ── Status Checks ──

    async def _persist_closure(
        self,
        db: AsyncSession,
        task: TaskModel,
        runtime_task,
    ) -> None:
        """Write Engineer/Reviewer runtime output back onto TaskModel.

        Requirement §三: ALL runtime output must live on TaskModel, never only
        in the in-memory RuntimeTask / TaskStep.output. The ORM object is bound
        to this session; the orchestrator commits after execute_task returns.
        """
        rt = runtime_task
        # git_commit / review_status already tracked on RuntimeTask
        if getattr(rt, "git_commit", ""):
            task.git_commit = rt.git_commit
        if getattr(rt, "review_status", "pending") != "pending":
            task.review_status = rt.review_status

        # Engineer structured output (JSON in rt.result)
        try:
            data = json.loads(rt.result or "{}")
        except Exception:
            data = {}
        if isinstance(data, dict):
            if data.get("files_changed"):
                task.files_changed = data["files_changed"]
            if data.get("commands_run"):
                task.commands_run = data["commands_run"]
            if data.get("test_result"):
                task.test_result = data["test_result"][:20000]
            if data.get("summary"):
                # keep a human summary on the task too
                if not task.description or task.description == task.title:
                    pass
            # Reviewer verdict payload
            if data.get("verdict"):
                task.review_status = "approved" if data["verdict"] == "approve" else "rejected"
                blockers = data.get("blockers") or []
                summary = data.get("summary", "")
                task.review_comments = (summary + "\n\nBlockers:\n- " + "\n- ".join(blockers)) if blockers else summary
            elif data.get("blockers") is not None:
                # reviewer output keyed differently
                task.review_comments = str(data.get("summary", ""))
        await db.flush()

    # ── Phase 27.5: Unified replan applicator + Brain fragment writer ──

    async def _apply_replan(
        self, db: AsyncSession, task: TaskModel, step: TaskStepModel,
        replan: dict | None, trace: TraceLogger, events: TaskEventLogger,
        error_msg: str,
    ) -> bool:
        """Apply a TechLead replan decision. Returns True if the step is resolved."""
        if not replan:
            return False
        action = replan.get("action", "")
        if action not in ("retry", "skip", "reassign"):
            return False

        step_id_short = step.id[:8]
        logger.warning(f"[EXECUTOR] Step {step_id_short} — TechLead replan: {action}")

        # Record decision
        task.replan_decisions = (task.replan_decisions or []) + [{
            "step_id": step.id,
            "error": error_msg[:500],
            "decision": {k: v for k, v in replan.items() if k != "reasoning"},
            "reasoning": replan.get("reasoning", ""),
        }]
        task.replan_count = (task.replan_count or 0) + 1

        if replan.get("new_objective"):
            step.objective = replan["new_objective"][:500]
        if replan.get("reassign"):
            step.teammate_id = replan["reassign"]

        await db.flush()

        # ── Skip: mark step SKIPPED, treat as resolved ──
        if action == "skip":
            step = await self.state.transition_step_status(db, step, TaskStepStatus.SKIPPED)
            events.log_step_completed(
                step_id=step.id, step_order=step.order, attempt=1,
                duration_ms=0, output_length=0,
            )
            # ponytail: skip counts as success — downstream deps resolve
            asyncio.ensure_future(self._store_replan_brain(task, replan, action, error_msg))
            return True

        # ── Reassign: teammate change + re-execute ──
        if action == "reassign":
            # Fall through to retry path below — reassign is "retry with new teammate"
            pass

        # ── Retry: re-submit with revised plan ──
        step.status = TaskStepStatus.PENDING
        await db.flush()
        context = await self.context_builder.build_maeos_description(db, task, step)
        new_rtid = await self._runtime.submit(
            description=context,
            priority=task.priority,
            intent=f"task_step:{task.id}",
            teammate=step.teammate_id or "",
            workspace_id=task.workspace_id or "",
            wait=False,
        )
        new_rt = await self._runtime.wait(new_rtid, timeout=300.0)
        if new_rt and new_rt.status == RuntimeExecStatus.COMPLETED:
            step = await self.result_handler.handle_step_success(
                db, step, new_rt.result or "", new_rtid, 0,
            )
            await self._persist_closure(db, task, new_rt)
            logger.info(f"[EXECUTOR] Step {step_id_short} COMPLETED after TechLead replan")
            asyncio.ensure_future(self._store_replan_brain(task, replan, action, error_msg))
            return True
        error_msg = new_rt.error if new_rt else "Replan execution failed"
        logger.warning(f"[EXECUTOR] Step {step_id_short} failed after replan: {error_msg}")
        return False

    async def _store_replan_brain(self, task: TaskModel, replan: dict, action: str, error_msg: str) -> None:
        """Write replan decision as BrainFragment DECISIONS (fire-and-forget)."""
        try:
            from backend.services.brain.fragment_store import get_brain_fragment_store, BrainFragment, BrainFragmentType
            frag = BrainFragment(
                teammate_id=task.created_by or "",
                fragment_type=BrainFragmentType.DECISIONS,
                content=json.dumps({
                    "event": "replan",
                    "task_id": task.id,
                    "step_id": replan.get("step_id", ""),
                    "action": action,
                    "failure_reason": error_msg[:500],
                    "adaptation": {k: v for k, v in replan.items() if k != "reasoning"},
                    "result": "applied" if action != "abort" else "aborted",
                }, ensure_ascii=False),
                source="techlead_replan",
                confidence=0.8,
            )
            await get_brain_fragment_store().store(frag)
        except Exception as e:
            logger.debug("[EXECUTOR] replan brain fragment skipped: %s", e)

    # ── Phase 27: TechLead replan helpers ──

    async def _find_techlead(self, db: AsyncSession):
        """Find the TechLead teammate by role."""
        from sqlalchemy import select
        from backend.models import Teammate
        row = (await db.execute(
            select(Teammate).where(Teammate.role == "techlead")
        )).scalar_one_or_none()
        return row

    async def _trigger_replan(self, db: AsyncSession, task: TaskModel,
                               step: TaskStepModel, error_msg: str) -> dict | None:
        """Call TechLead for a replan decision. Returns dict or None."""
        tl = await self._find_techlead(db)
        if not tl:
            return None

        from sqlalchemy import select as _s
        from backend.models import Teammate as _TM
        tm_rows = (await db.execute(_s(_TM))).scalars().all()
        tms = "\n".join(f"  {t.name} (role={t.role}, id={t.id[:8]})" for t in tm_rows) if tm_rows else "none"

        prompt = (
            f"A step failed. Replan, skip, reassign, or abort.\n\n"
            f"## Task\n{task.title}\n\n"
            f"## Failed Step\n{step.objective}\n\n"
            f"## Error\n{error_msg[:500]}\n\n"
            f"## Available Teammates\n{tms}\n\n"
            f"Respond ONLY with valid JSON, no markdown:\n"
            f'{{"action":"retry","new_objective":"revised step","reassign":"teammate_id","reasoning":"why"}}\n'
            f'{{"action":"skip","reasoning":"step is unnecessary"}}\n'
            f'{{"action":"reassign","reassign":"teammate_id","reasoning":"better teammate for this"}}\n'
            f'Or {{"action":"abort","reasoning":"cannot recover"}}'
        )

        try:
            rt = await self.execute_direct(
                db, task=task,
                description=prompt,
                intent=f"techlead_replan:{task.id}",
                teammate_id=tl.id,
                workspace_id=task.workspace_id or "",
                timeout=60.0,
            )
            if rt and rt.result:
                decision = json.loads(rt.result)
                if isinstance(decision, dict) and decision.get("action"):
                    return decision
        except Exception:
            pass
        return None

    async def execute_direct(
        self,
        db: AsyncSession,
        task: TaskModel,
        *,
        description: str,
        intent: str,
        teammate_id: str,
        workspace_id: str,
        git_commit: str = "",
        timeout: float = 300.0,
    ):
        """Run a single execution through the full pipeline — policy → runtime → trace.

        Used by orchestrator relay paths (reviewer, techlead) that work outside
        the normal step sequence but MUST NOT bypass policy / runtime trace.

        Returns the completed RuntimeTask.
        Raises RuntimeError on failure (after retries).
        """
        if self._runtime is None:
            raise RuntimeError("ExecutionRuntime not set")

        # 1. Policy gate — evaluate with a minimal step-like context
        policy_ok, policy_reason = await self.policy.evaluate_direct(
            db, task, teammate_id=teammate_id, action="task.execute",
        )
        if not policy_ok:
            raise PolicyBlockedError(policy_reason)

        # 2. Runtime submit
        trace_id = str(uuid.uuid4())
        trace = TraceLogger(trace_id=trace_id, task_id=task.id)
        events = TaskEventLogger(task_id=task.id, task=task)

        events.log_started()
        rt_id = await self._runtime.submit(
            description=description,
            priority=task.priority,
            intent=intent,
            teammate=teammate_id,
            workspace_id=workspace_id,
            git_commit=git_commit,
            wait=False,
        )
        trace.log_teammate_dispatch(
            teammate_id=teammate_id,
            state=TaskStepStatus.RUNNING,
            input_snapshot={"description": description[:200]},
            attempt=1,
        )

        # 3. Wait (with retry)
        attempt = 1
        max_attempts = self.retry_policy.max_retries + 1
        while attempt <= max_attempts:
            start_time = time.time()
            rt = await self._runtime.wait(rt_id, timeout=timeout)
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)

            if rt and rt.status == RuntimeExecStatus.COMPLETED:
                trace.log_teammate_result(
                    teammate_id=teammate_id,
                    state=TaskStepStatus.COMPLETED,
                    output_snapshot={"preview": (rt.result or "")[:200]},
                    latency_ms=duration_ms,
                    attempt=attempt,
                )
                events.log_step_completed(
                    step_id="direct", step_order=0, attempt=attempt,
                    duration_ms=duration_ms, output_length=len(rt.result or ""),
                )
                return rt

            error_msg = rt.error if rt else "ExecutionRuntime timeout"
            trace.log_failure_classified(
                teammate_id=teammate_id,
                state=TaskStepStatus.FAILED,
                failure_type="execution_error",
                error=error_msg,
                action="retry" if attempt < max_attempts else "abort",
            )

            if attempt < max_attempts:
                delay = self.retry_policy.base_delay_ms / 1000.0
                await asyncio.sleep(delay)
                attempt += 1
                continue

            raise RuntimeError(f"Direct execution failed: {error_msg}")

        raise RuntimeError("Direct execution exhausted retries")

    async def get_task_progress(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> dict:
        """Get execution progress for a task."""
        steps = await self.state.list_steps(db, task_id)
        total = len(steps)
        completed = sum(1 for s in steps if s.status == TaskStepStatus.COMPLETED)
        failed = sum(1 for s in steps if s.status == TaskStepStatus.FAILED)

        return {
            "task_id": task_id,
            "total_steps": total,
            "completed_steps": completed,
            "failed_steps": failed,
            "pending_steps": total - completed - failed,
            "steps": [s.to_dict() for s in steps],
        }


# ── Internal Proxy for RetryPolicy.decide() ──

class _ExecUnitProxy:
    """
    Minimal adapter so RetryPolicy.decide() can operate on our step data
    without requiring the full runtime.ExecUnit class.
    """
    def __init__(self, attempt: int, error: str):
        self.attempt = attempt
        self.error = error
