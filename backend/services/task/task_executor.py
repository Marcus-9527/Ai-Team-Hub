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
)
from backend.services.runtime.trace import TraceLogger

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

    def __init__(self, maeos_instance=None, retry_policy: Optional[RetryPolicy] = None):
        self.state = TaskStateManager()
        self.context_builder = TaskContextBuilder()
        self.result_handler = TaskResultHandler()
        self.approval = TaskApprovalService()
        self.policy = TaskPolicyService()
        self._maeos = maeos_instance  # MAEOS singleton
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=2,
            backoff_strategy=BackoffStrategy.LINEAR,
            base_delay_ms=2000,
        )

    def set_maeos(self, maeos_instance) -> None:
        """Set the MAEOS instance (call before execute_task)."""
        self._maeos = maeos_instance

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
        if self._maeos is None:
            raise RuntimeError("MAEOS instance not set. Call set_maeos() first.")

        if task.status != TaskStatus.EXECUTING:
            raise ValueError(
                f"Task must be in EXECUTING state, got {task.status}"
            )

        # Initialize trace + event loggers
        trace_id = str(uuid.uuid4())
        trace = TraceLogger(trace_id=trace_id, task_id=task.id)
        events = TaskEventLogger(task_id=task.id)

        events.log_started()

        # Get steps ordered by `order`
        steps = await self.state.list_steps(db, task.id)
        pending_steps = [s for s in steps if s.status == TaskStepStatus.PENDING]

        if not pending_steps:
            logger.info(f"[EXECUTOR] No pending steps for task {task.id}")
            if all(s.status == TaskStepStatus.COMPLETED for s in steps):
                task = await self.result_handler.handle_task_completion(db, task)
                events.log_completed(total_steps=len(steps))
            return task

        overall_success = True

        for step in pending_steps:
            try:
                await self._execute_single_step(
                    db, task, step, trace=trace, events=events,
                )
            except ApprovalRequiredError:
                # Step requires approval — task is PAUSED, not failed.
                # Break the loop and return the task as-is (PAUSED).
                logger.info(
                    f"[EXECUTOR] Task {task.id} paused for approval "
                    f"at step {step.id} (order={step.order})"
                )
                overall_success = True  # Not a failure
                break
            except PolicyBlockedError as e:
                # Step blocked by policy — mark step FAILED, stop execution.
                logger.warning(
                    f"[EXECUTOR] Task {task.id} blocked by policy "
                    f"at step {step.id} (order={step.order})"
                )
                step = await self.state.transition_step_status(
                    db, step, TaskStepStatus.FAILED
                )
                # Create execution record for the blocked step
                execution = await self.result_handler.record_execution(
                    db, step,
                    maeos_task_id="policy_blocked",
                    attempt=1,
                    trace_id=trace.trace_id,
                    teammate_id=step.teammate_id or "",
                )
                await self.result_handler.update_execution_result(
                    db, execution,
                    error=f"Policy blocked: {str(e)}",
                    execution_time_ms=0,
                )
                overall_success = False
                await self.result_handler.handle_task_failure(db, task)
                break
            except Exception as e:
                logger.error(
                    f"[EXECUTOR] Step {step.id} (order={step.order}) "
                    f"failed after all retries: {e}"
                )
                trace.log_error(
                    state=TaskStepStatus.FAILED,
                    error=str(e),
                    teammate_id=step.teammate_id or "",
                )
                overall_success = False
                break

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

    # ── Single Step Execution with Retries ──

    async def _execute_single_step(
        self,
        db: AsyncSession,
        task: TaskModel,
        step: TaskStepModel,
        trace: TraceLogger,
        events: TaskEventLogger,
    ) -> None:
        """
        Execute one step through MAEOS with retry support.

        Raises on final failure (caller handles task status).
        """
        step_id_short = step.id[:8]
        teammate_id = step.teammate_id or ""
        attempt = 1
        max_attempts = self.retry_policy.max_retries + 1

        # ── Policy Evaluation (Phase C2) ────────────────────────────────
        # Evaluate step against task policy: risk level, retry limit,
        # teammate permission, and approval requirement.
        policy_result = await self.policy.evaluate_step(db, task, step)

        if not policy_result.allowed:
            logger.warning(
                f"[EXECUTOR] Step {step_id_short} (order={step.order}) "
                f"blocked by policy: {policy_result.blocked_reason}"
            )
            if events:
                events.log_policy_blocked(
                    step_id=step.id,
                    step_order=step.order,
                    reason=policy_result.blocked_reason,
                )
            raise PolicyBlockedError(policy_result.blocked_reason)

        if policy_result.requires_approval:
            logger.info(
                f"[EXECUTOR] Step {step_id_short} (order={step.order}) "
                f"requires human approval — pausing task"
            )
            await self.approval.create_approval(
                db, task, step,
                reason=f"Policy: step {step.order} ({step.objective[:100]})",
                events=events,
            )
            raise ApprovalRequiredError(
                f"Step {step.id} (order={step.order}) requires approval"
            )
        # ────────────────────────────────────────────────────────────────

        context = await self.context_builder.build_maeos_description(
            db, task, step
        )

        while attempt <= max_attempts:
            logger.info(
                f"[EXECUTOR] Step {step_id_short} (order={step.order}, "
                f"attempt {attempt}/{max_attempts}): {step.objective[:60]}"
            )

            events.log_step_started(
                step_id=step.id,
                step_order=step.order,
                attempt=attempt,
                teammate_id=teammate_id,
            )

            # 1. Update step → RUNNING
            step = await self.state.transition_step_status(
                db, step, TaskStepStatus.RUNNING
            )

            # 2. Submit to MAEOS
            start_time = time.time()

            maeos_task_id = await self._maeos.submit(
                description=context,
                priority=task.priority,
                intent=f"task_step:{task.id}",
                wait=False,
            )

            trace.log_teammate_dispatch(
                teammate_id=teammate_id,
                state=TaskStepStatus.RUNNING,
                input_snapshot={"objective": step.objective[:200], "context_len": len(context)},
                attempt=attempt,
            )

            # 3. Create execution record with trace fields
            execution = await self.result_handler.record_execution(
                db, step,
                maeos_task_id=maeos_task_id,
                attempt=attempt,
                trace_id=trace.trace_id,
                teammate_id=teammate_id,
            )

            # 4. Wait for MAEOS completion
            maeos_task = await self._maeos.wait(maeos_task_id, timeout=300.0)

            end_time = time.time()
            duration_ms = self.result_handler.calculate_duration(start_time, end_time)

            # 5. Process result
            if maeos_task and maeos_task.status == "COMPLETED":
                result_text = maeos_task.result or ""
                maeos_trace_id = ""
                if hasattr(maeos_task, "trace_report") and maeos_task.trace_report:
                    maeos_trace_id = maeos_task.trace_report.get("trace_id", "")

                # Estimate tokens and cost from output
                inp_tok, out_tok, tot_tok, cost_micro = estimate_cost(
                    input_text=context,
                    output_text=result_text,
                )

                # Update step → COMPLETED
                await self.result_handler.handle_step_success(
                    db, step, result_text, maeos_task_id, duration_ms
                )

                # Update execution record with all trace/cost fields
                await self.result_handler.update_execution_result(
                    db, execution,
                    output=result_text,
                    execution_time_ms=duration_ms,
                    trace_id=maeos_trace_id or trace.trace_id,
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
                    step_id=step.id,
                    step_order=step.order,
                    attempt=attempt,
                    duration_ms=duration_ms,
                    output_length=len(result_text),
                )

                logger.info(
                    f"[EXECUTOR] Step {step_id_short} COMPLETED "
                    f"in {duration_ms}ms ({len(result_text)} chars, "
                    f"{tot_tok} tokens, ${cost_micro / 1_000_000:.6f})"
                )
                return  # Success, exit the retry loop

            else:
                # Step failed — check if we should retry
                error_msg = maeos_task.error if maeos_task else "MAEOS task timeout"
                if not error_msg:
                    error_msg = "Unknown MAEOS execution error"

                # Classify failure and decide action
                failure_type = self.retry_policy.classify(error_msg, validation_failed=False)
                decision = self.retry_policy.decide(
                    _ExecUnitProxy(attempt=attempt, error=error_msg)
                )

                trace.log_failure_classified(
                    teammate_id=teammate_id,
                    state=TaskStepStatus.FAILED,
                    failure_type=failure_type.value,
                    error=error_msg,
                    action=decision.action,
                )

                if decision.action == "retry":
                    # Update execution with partial result
                    await self.result_handler.update_execution_result(
                        db, execution,
                        error=error_msg,
                        execution_time_ms=duration_ms,
                    )

                    # Update step: mark failed, increment retry_count
                    step = await self.result_handler.handle_step_failure(
                        db, step, error_msg, maeos_task_id
                    )
                    await self.result_handler.update_step_retry_count(
                        db, step, attempt
                    )

                    events.log_step_failed(
                        step_id=step.id,
                        step_order=step.order,
                        attempt=attempt,
                        error=error_msg,
                        will_retry=True,
                    )

                    logger.warning(
                        f"[EXECUTOR] Step {step_id_short} attempt {attempt} "
                        f"FAILED ({failure_type.value}). "
                        f"Retrying in {decision.delay_ms}ms..."
                    )

                    # Backoff delay
                    await asyncio.sleep(decision.delay_ms / 1000.0)

                    # Reset step status to PENDING for retry
                    step = await self.state.transition_step_status(
                        db, step, TaskStepStatus.PENDING
                    )
                    attempt += 1
                    continue

                else:
                    # ABORT — no more retries
                    await self.result_handler.update_execution_result(
                        db, execution,
                        error=error_msg,
                        execution_time_ms=duration_ms,
                    )
                    await self.result_handler.handle_step_failure(
                        db, step, error_msg, maeos_task_id
                    )

                    events.log_step_failed(
                        step_id=step.id,
                        step_order=step.order,
                        attempt=attempt,
                        error=error_msg,
                        will_retry=False,
                    )

                    logger.error(
                        f"[EXECUTOR] Step {step_id_short} ABORTED: {error_msg}"
                    )
                    raise RuntimeError(
                        f"Step {step.id} failed (action={decision.action}): {error_msg}"
                    )

        # Exhausted all retries
        raise RuntimeError(
            f"Step {step.id} failed after {max_attempts} attempts"
        )

    # ── Status Checks ──

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
