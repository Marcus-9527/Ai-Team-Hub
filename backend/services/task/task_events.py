"""
task_events.py — Task Lifecycle Event Logger

Emits structured lifecycle events for task and step state transitions.
Also dispatches events to the TaskHookRegistry for side-effect hooks
(Memory, notifications, analytics, etc.).

Events:
  CREATED        — Task created (CREATED status)
  STARTED        — Execution started (EXECUTING status)
  STEP_STARTED   — A step began execution (RUNNING)
  STEP_COMPLETED — A step completed successfully
  STEP_FAILED    — A step failed (with retry info)
  FAILED         — Task failed overall
  COMPLETED      — Task completed successfully
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("task.events")


@dataclass
class TaskEvent:
    """A single task lifecycle event."""
    event_type: str        # CREATED, STARTED, STEP_STARTED, etc.
    task_id: str
    step_id: str = ""
    step_order: int = 0
    timestamp: float = 0.0
    attempt: int = 0
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_log(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


class TaskEventLogger:
    """Structured event logger for task lifecycle."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._events: list[TaskEvent] = []

    def _emit(self, event_type: str, **kwargs) -> TaskEvent:
        event = TaskEvent(
            event_type=event_type,
            task_id=self.task_id,
            **kwargs,
        )
        self._events.append(event)
        logger.info(f"[TASK-EVENT] {event.to_log()}")

        # ── Dispatch to TaskHookRegistry (async fire-and-forget) ──
        # This hooks task lifecycle events into side-effect handlers
        # such as the Memory Event Handler (V3.1 Phase A).
        self._dispatch_to_hooks(event)

        return event

    def _dispatch_to_hooks(self, event: TaskEvent) -> None:
        """Forward this event to the global TaskHookRegistry (async, best-effort)."""
        try:
            from backend.services.task.task_hooks import (
                TaskLifecycleEvent,
                TaskHookContext,
                get_task_hook_registry,
            )

            mapping = {
                "CREATED": TaskLifecycleEvent.TASK_CREATED,
                "COMPLETED": TaskLifecycleEvent.TASK_COMPLETED,
                "FAILED": TaskLifecycleEvent.TASK_FAILED,
                "STEP_COMPLETED": TaskLifecycleEvent.STEP_COMPLETED,
                "EXECUTION_COMPLETED": TaskLifecycleEvent.EXECUTION_COMPLETED,
            }

            lifecycle = mapping.get(event.event_type)
            if lifecycle is None:
                return  # not a mapped event type

            # Build context from available TaskEvent fields
            ctx = TaskHookContext(
                task_id=event.task_id,
                step_id=event.step_id,
                step_order=event.step_order,
                step_objective=event.data.get("objective", ""),
                step_output=event.data.get("output", ""),
                step_error=event.data.get("error", ""),
                execution_id=event.data.get("execution_id", ""),
                execution_outcome=event.data.get("outcome", ""),
                execution_duration_ms=event.data.get("duration_ms", 0),
                execution_total_tokens=event.data.get("total_tokens", 0),
                execution_teammate_id=event.data.get("teammate_id", ""),
                extra=dict(event.data),
            )

            import asyncio

            registry = get_task_hook_registry()
            asyncio.ensure_future(registry.dispatch(lifecycle, ctx))

        except Exception as e:
            logger.debug(f"[TASK-EVENT] Hook dispatch failed (non-fatal): {e}")

    def log_created(self) -> TaskEvent:
        return self._emit("CREATED", data={"status": "CREATED"})

    def log_started(self) -> TaskEvent:
        return self._emit("STARTED", data={"status": "EXECUTING"})

    def log_step_started(
        self,
        step_id: str,
        step_order: int,
        attempt: int = 1,
        teammate_id: str = "",
    ) -> TaskEvent:
        return self._emit(
            "STEP_STARTED",
            step_id=step_id,
            step_order=step_order,
            attempt=attempt,
            data={"teammate_id": teammate_id},
        )

    def log_step_completed(
        self,
        step_id: str,
        step_order: int,
        attempt: int = 1,
        duration_ms: int = 0,
        output_length: int = 0,
    ) -> TaskEvent:
        return self._emit(
            "STEP_COMPLETED",
            step_id=step_id,
            step_order=step_order,
            attempt=attempt,
            data={
                "duration_ms": duration_ms,
                "output_length": output_length,
            },
        )

    def log_step_failed(
        self,
        step_id: str,
        step_order: int,
        attempt: int = 1,
        error: str = "",
        will_retry: bool = False,
    ) -> TaskEvent:
        return self._emit(
            "STEP_FAILED",
            step_id=step_id,
            step_order=step_order,
            attempt=attempt,
            data={"error": error[:500], "will_retry": will_retry},
        )

    def log_failed(self, reason: str = "") -> TaskEvent:
        return self._emit("FAILED", data={"reason": reason[:500]})

    def log_completed(self, total_steps: int = 0) -> TaskEvent:
        return self._emit(
            "COMPLETED",
            data={"total_steps": total_steps},
        )

    # ── Approval Events (Phase C1) ──

    def log_approval_required(
        self,
        step_id: str,
        step_order: int,
        approval_id: str = "",
        reason: str = "",
    ) -> TaskEvent:
        return self._emit(
            "APPROVAL_REQUIRED",
            step_id=step_id,
            step_order=step_order,
            data={"approval_id": approval_id, "reason": reason},
        )

    def log_approved(
        self,
        step_id: str,
        step_order: int,
        approval_id: str = "",
        approved_by: str = "",
    ) -> TaskEvent:
        return self._emit(
            "APPROVED",
            step_id=step_id,
            step_order=step_order,
            data={"approval_id": approval_id, "approved_by": approved_by},
        )

    def log_rejected(
        self,
        step_id: str,
        step_order: int,
        approval_id: str = "",
        reason: str = "",
    ) -> TaskEvent:
        return self._emit(
            "REJECTED",
            step_id=step_id,
            step_order=step_order,
            data={"approval_id": approval_id, "reason": reason},
        )

    # ── Policy Events (Phase C2) ──

    def log_policy_blocked(
        self,
        step_id: str = "",
        step_order: int = 0,
        reason: str = "",
    ) -> TaskEvent:
        return self._emit(
            "POLICY_BLOCKED",
            step_id=step_id,
            step_order=step_order,
            data={"reason": reason},
        )

    def log_cost_limit_reached(
        self,
        step_id: str = "",
        step_order: int = 0,
        estimated_cost: float = 0.0,
        max_cost: float = 0.0,
    ) -> TaskEvent:
        return self._emit(
            "COST_LIMIT_REACHED",
            step_id=step_id,
            step_order=step_order,
            data={"estimated_cost": estimated_cost, "max_cost": max_cost},
        )

    # ── V3.0 Phase B: Task Intelligence Dashboard Events ──

    def log_execution_started(
        self,
        step_id: str,
        step_order: int,
        execution_id: str = "",
        attempt: int = 1,
        teammate_id: str = "",
    ) -> TaskEvent:
        return self._emit(
            "EXECUTION_STARTED",
            step_id=step_id,
            step_order=step_order,
            attempt=attempt,
            data={
                "execution_id": execution_id,
                "teammate_id": teammate_id,
            },
        )

    def log_execution_completed(
        self,
        step_id: str,
        step_order: int,
        execution_id: str = "",
        attempt: int = 1,
        outcome: str = "",
        duration_ms: int = 0,
        total_tokens: int = 0,
    ) -> TaskEvent:
        return self._emit(
            "EXECUTION_COMPLETED",
            step_id=step_id,
            step_order=step_order,
            attempt=attempt,
            data={
                "execution_id": execution_id,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "total_tokens": total_tokens,
            },
        )

    def log_execution_failed(
        self,
        step_id: str,
        step_order: int,
        execution_id: str = "",
        attempt: int = 1,
        error: str = "",
    ) -> TaskEvent:
        return self._emit(
            "EXECUTION_FAILED",
            step_id=step_id,
            step_order=step_order,
            attempt=attempt,
            data={
                "execution_id": execution_id,
                "error": error[:500],
            },
        )

    def log_plan_created(
        self,
        step_id: str,
        step_order: int,
        plan_summary: str = "",
        steps_count: int = 0,
    ) -> TaskEvent:
        return self._emit(
            "PLAN_CREATED",
            step_id=step_id,
            step_order=step_order,
            data={
                "plan_summary": plan_summary[:200],
                "steps_count": steps_count,
            },
        )

    def log_approval_completed(
        self,
        step_id: str,
        step_order: int,
        approval_id: str = "",
        result: str = "",
        reviewer: str = "",
    ) -> TaskEvent:
        return self._emit(
            "APPROVAL_COMPLETED",
            step_id=step_id,
            step_order=step_order,
            data={
                "approval_id": approval_id,
                "result": result,
                "reviewer": reviewer,
            },
        )

    def log_execution_quality_updated(
        self,
        step_id: str,
        step_order: int,
        execution_id: str = "",
        overall_quality: float = 0.0,
    ) -> TaskEvent:
        return self._emit(
            "EXECUTION_QUALITY_UPDATED",
            step_id=step_id,
            step_order=step_order,
            data={
                "execution_id": execution_id,
                "overall_quality": overall_quality,
            },
        )

    def get_events(self) -> list[dict]:
        return [asdict(e) for e in self._events]
