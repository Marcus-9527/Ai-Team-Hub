"""TaskActionAdapter — map Task lifecycle phases to OrganizationAction events.

Wraps TaskOrchestrator's phase boundaries (plan, review, execute, verify,
complete) with action.created/started/completed/failed events via
OrganizationActionRuntime.emit_action_event().

Timing:
  emit_start(PLAN)   → action.created + action.started
  … orchestrator._plan() runs …
  emit_end(PLAN)     → action.completed (or action.failed on error)

Keeps event timing aligned with real phase boundaries.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.organization.actions import OrganizationAction
from backend.services.organization.action_runtime import OrganizationActionRuntime


class TaskActionAdapter:
    """Emit action.* events for each task lifecycle phase.

    Usage inside TaskOrchestrator::

        adapter = TaskActionAdapter(db, trigger_id, run_id)
        await adapter.emit_start(OrganizationAction.PLAN)
        # ... actual planning work ...
        await adapter.emit_end(OrganizationAction.PLAN)
    """

    def __init__(
        self,
        db: AsyncSession,
        trigger_id: str = "",
        run_id: str = "",
    ):
        self.db = db
        self.trigger_id = trigger_id
        self.run_id = run_id
        self._runtime = OrganizationActionRuntime(db)

    async def emit_start(self, action: OrganizationAction, **extra) -> None:
        """Emit action.created + action.started for *action*."""
        await self._runtime.emit_action_event(
            "created", trigger_id=self.trigger_id, run_id=self.run_id,
            action_type=action.value, extra=extra,
        )
        await self._runtime.emit_action_event(
            "started", trigger_id=self.trigger_id, run_id=self.run_id,
            action_type=action.value, extra=extra,
        )

    async def emit_end(
        self, action: OrganizationAction, *, error: str = "", **extra,
    ) -> None:
        """Emit action.completed (or action.failed if *error* is set)."""
        phase = "failed" if error else "completed"
        extra_inner = dict(extra)
        if error:
            extra_inner["error"] = error
        await self._runtime.emit_action_event(
            phase, trigger_id=self.trigger_id, run_id=self.run_id,
            action_type=action.value, extra=extra_inner,
        )
