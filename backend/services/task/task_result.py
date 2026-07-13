"""
task_result.py — Task Result Handler

Persists execution results, updates step and task status based on
MAEOS execution outcomes. Records execution metrics (duration, output, trace).

v2.5 Hardening additions:
  - Trace fields: start_time, end_time, teammate_id, model_name
  - Cost tracking: input_tokens, output_tokens, total_tokens, estimated_cost
  - Helper for token estimation from output text
"""

import logging
import time
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskExecutionModel,
    TaskStatus,
    TaskStepStatus,
)
from backend.services.task.task_state import TaskStateManager

# Default cost rates per 1K tokens (in micro-dollars µ$)
# These are rough estimates; real values depend on the provider/model.
DEFAULT_COST_INPUT_USD_PER_1K = 0.001   # $0.001 / 1K input tokens
DEFAULT_COST_OUTPUT_USD_PER_1K = 0.002  # $0.002 / 1K output tokens

logger = logging.getLogger("task.result")


def _usd_to_microdollars(usd: float) -> int:
    """Convert USD to micro-dollars ( µ$) for integer storage."""
    return int(usd * 1_000_000)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars of text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def parse_task_output(result_text: str) -> dict:
    """
    Parse a RuntimeTask result into the structured TaskOutput shape:
        {"summary", "files_changed", "commands_run", "git_commit", "test_result"}

    If the result is JSON (engineer workflow), use it directly; otherwise wrap
    the plain text as a summary. Never raises — falls back to a summary.
    """
    if not result_text:
        return {
            "summary": "", "files_changed": [], "commands_run": [],
            "git_commit": "", "test_result": "",
        }
    try:
        data = json.loads(result_text)
        if isinstance(data, dict) and "summary" in data:
            return {
                "summary": data.get("summary", ""),
                "files_changed": data.get("files_changed", []) or [],
                "commands_run": data.get("commands_run", []) or [],
                "git_commit": data.get("git_commit", "") or "",
                "test_result": data.get("test_result", "") or "",
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        "summary": result_text, "files_changed": [], "commands_run": [],
        "git_commit": "", "test_result": "",
    }


def estimate_cost(
    input_text: str = "",
    output_text: str = "",
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost_per_input_1k: float = DEFAULT_COST_INPUT_USD_PER_1K,
    cost_per_output_1k: float = DEFAULT_COST_OUTPUT_USD_PER_1K,
) -> tuple[int, int, int, int]:
    """
    Estimate token usage and cost.

    Returns (input_tokens, output_tokens, total_tokens, estimated_cost_µ$).
    """
    inp = input_tokens if input_tokens is not None else estimate_tokens(input_text)
    out = output_tokens if output_tokens is not None else estimate_tokens(output_text)
    total = inp + out

    cost_usd = (inp / 1000) * cost_per_input_1k + (out / 1000) * cost_per_output_1k
    cost_usd = max(cost_usd, 0.0)
    cost_micro = _usd_to_microdollars(cost_usd)

    return inp, out, total, cost_micro


class TaskResultHandler:
    """Handles execution result persistence and status updates."""

    def __init__(self):
        self.state = TaskStateManager()

    # ── Execution Recording ──

    async def record_execution(
        self,
        db: AsyncSession,
        step: TaskStepModel,
        maeos_task_id: str,
        attempt: int = 1,
        trace_id: Optional[str] = None,
        teammate_id: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> TaskExecutionModel:
        """Create a TaskExecution record for a step attempt."""
        now = datetime.now(timezone.utc)
        return await self.state.create_execution(
            db,
            task_step_id=step.id,
            attempt=attempt,
            maeos_task_id=maeos_task_id,
            trace_id=trace_id or "",
            start_time=now,
            teammate_id=teammate_id or "",
            model_name=model_name or "",
        )

    async def update_execution_result(
        self,
        db: AsyncSession,
        execution: TaskExecutionModel,
        *,
        output: str = "",
        error: str = "",
        execution_time_ms: int = 0,
        token_usage: int = 0,
        cost: int = 0,
        trace_id: Optional[str] = None,
        # New hardening fields
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_value: int = 0,
        end_time: Optional[datetime] = None,
    ) -> TaskExecutionModel:
        """Update execution record with results from MAEOS."""
        return await self.state.update_execution(
            db,
            execution,
            output_snapshot=output[:10000] if output else "",
            error=error[:2000] if error else "",
            execution_time_ms=execution_time_ms,
            token_usage=token_usage,
            cost=cost,
            trace_id=trace_id or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost_value,
            end_time=end_time or datetime.now(timezone.utc),
        )

    async def record_execution_with_cost(
        self,
        db: AsyncSession,
        execution: TaskExecutionModel,
        *,
        output: str = "",
        error: str = "",
        execution_time_ms: int = 0,
        trace_id: Optional[str] = None,
        input_text: str = "",
        # Optional manual token overrides
        input_tokens_manual: Optional[int] = None,
        output_tokens_manual: Optional[int] = None,
    ) -> TaskExecutionModel:
        """
        One-call update with automatic cost estimation from text.

        Estimates tokens from input/output text, computes cost,
        and updates all trace/cost fields in one shot.
        """
        inp_tok, out_tok, tot_tok, cost_micro = estimate_cost(
            input_text=input_text,
            output_text=output,
            input_tokens=input_tokens_manual,
            output_tokens=output_tokens_manual,
        )
        return await self.update_execution_result(
            db, execution,
            output=output,
            error=error,
            execution_time_ms=execution_time_ms,
            trace_id=trace_id,
            input_tokens=inp_tok,
            output_tokens=out_tok,
            total_tokens=tot_tok,
            estimated_cost_value=cost_micro,
        )

    # ── Step Result Handling ──

    async def handle_step_success(
        self,
        db: AsyncSession,
        step: TaskStepModel,
        maeos_result: str,
        maeos_task_id: str,
        execution_time_ms: int,
    ) -> TaskStepModel:
        """
        Handle a successful step execution.

        Updates step with output, marks as RUNNING then COMPLETED.
        Returns the updated step.
        """
        # Persist MAEOS result to the step
        step = await self.state.update_step(
            db,
            step,
            output=maeos_result,
            maeos_task_id=maeos_task_id,
        )
        # Transition to RUNNING then COMPLETED
        step = await self.state.transition_step_status(
            db, step, TaskStepStatus.RUNNING
        )
        return await self.state.transition_step_status(
            db, step, TaskStepStatus.COMPLETED
        )

    async def handle_step_failure(
        self,
        db: AsyncSession,
        step: TaskStepModel,
        error: str,
        maeos_task_id: Optional[str] = None,
    ) -> TaskStepModel:
        """
        Handle a failed step execution.

        Updates step with error info, marks as RUNNING then FAILED.
        Returns the updated step.
        """
        step = await self.state.update_step(
            db,
            step,
            error=error[:2000],
            maeos_task_id=maeos_task_id or "",
        )
        # Transition through RUNNING to FAILED
        step = await self.state.transition_step_status(
            db, step, TaskStepStatus.RUNNING
        )
        return await self.state.transition_step_status(
            db, step, TaskStepStatus.FAILED
        )

    async def update_step_retry_count(
        self,
        db: AsyncSession,
        step: TaskStepModel,
        retry_count: int,
    ) -> TaskStepModel:
        """Update step retry count."""
        return await self.state.update_step(
            db, step, retry_count=retry_count,
        )

    # ── Task Result Handling ──

    async def handle_task_completion(
        self,
        db: AsyncSession,
        task: TaskModel,
    ) -> TaskModel:
        """Mark task as COMPLETED after all steps are done."""
        return await self.state.transition_task_status(
            db, task, TaskStatus.COMPLETED
        )

    async def handle_task_failure(
        self,
        db: AsyncSession,
        task: TaskModel,
    ) -> TaskModel:
        """Mark task as FAILED when a step fails (non-recoverable)."""
        # Task must go through RUNNING first
        if task.status != TaskStatus.RUNNING:
            task = await self.state.transition_task_status(
                db, task, TaskStatus.RUNNING
            )
        return await self.state.transition_task_status(
            db, task, TaskStatus.FAILED
        )

    # ── Helpers ──

    def calculate_duration(
        self,
        start_time: float,
        end_time: Optional[float] = None,
    ) -> int:
        """Calculate execution duration in milliseconds."""
        if end_time is None:
            end_time = time.time()
        return int((end_time - start_time) * 1000)
