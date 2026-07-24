"""OrganizationRuntime — central run lifecycle + action routing.

Routes run lifecycle and delegates execution to OrganizationExecutor.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.organization.context import OrganizationContextBuilder
from backend.services.organization.action_runtime import OrganizationActionRuntime
from backend.services.organization.actions import OrganizationAction, ALL_ACTIONS

logger = logging.getLogger(__name__)


class OrganizationRuntime:
    """Lifecycle hub for OrganizationRun — delegates execution to OrganizationExecutor."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.action_runtime = OrganizationActionRuntime(db)
        self.executor = self.action_runtime.router.executor  # convenience alias

    # ── Run lifecycle ──

    async def start_run(self, *, run_type: str, source_id: str, workspace_id: str = "", channel_id: str = "", title: str = ""):
        """Create an OrganizationRun. Returns the run (caller links trigger)."""
        from backend.services.organization import OrganizationRunService
        run = await OrganizationRunService.create_run(
            self.db, run_type=run_type, source_id=source_id,
            workspace_id=workspace_id, channel_id=channel_id, title=title,
        )
        return run

    async def finish_run(self, run_id: str, *, status: str = "completed", trigger_id: Optional[str] = None) -> None:
        """Close an OrganizationRun. Emits run.completed if trigger_id given."""
        from backend.services.organization import OrganizationRunService
        await OrganizationRunService.close_run(self.db, run_id, status=status)
        from backend.services.memory.consolidator import get_consolidator
        await get_consolidator().consolidate_run(run_id)
        # Post-run identity feedback (failure-safe)
        try:
            from backend.services.organization.identity_feedback import IdentityFeedbackService
            await IdentityFeedbackService(self.db).process_run(run_id)
        except Exception:
            logger.exception("IdentityFeedback failed for run %s", run_id)
        # Post-run learning (failure-safe)
        try:
            from backend.services.organization.learning import OrganizationLearningService
            await OrganizationLearningService(self.db).learn_from_run(run_id)
        except Exception:
            logger.exception("OrganizationLearning failed for run %s", run_id)
        if trigger_id:
            await self._emit_run_event(trigger_id, "run.completed", run_id, extra={"status": status})

    # ── Chat input routing (lifecycle wrapping) ──

    async def handle_input(
        self, *, run_id: str, trigger_id: str, teammates: list[dict], user_message: str,
        channel_id: str = "", shared_attachment_context: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """Route chat input through OrganizationActionRuntime → OrganizationExecutor → OrganizationLoop.

        Writes current_action to OrganizationState before/after dispatching.
        Yields SSE chunks — caller wraps them in StreamingResponse.
        """
        svc = self._state_svc()
        ctx = await OrganizationContextBuilder(self.db).build(run_id)

        await svc.set_state(run_id, "current_action", "main", {"action_type": "pending", "status": "deciding"}, trigger_id=trigger_id)
        try:
            async for chunk in self.action_runtime.respond(
                ctx=ctx, user_input=user_message, trigger_id=trigger_id,
                run_id=run_id, teammates=teammates, channel_id=channel_id,
                shared_attachment_context=shared_attachment_context,
            ):
                yield chunk
            await svc.update_state(run_id, "progress", "main", {"responded": True}, trigger_id=trigger_id)
            await svc.update_state(run_id, "current_action", "main", {"action_type": "respond", "status": "completed"}, trigger_id=trigger_id)
        except Exception:
            await svc.update_state(run_id, "current_action", "main", {"action_type": "respond", "status": "failed"}, trigger_id=trigger_id)
            raise

    # ── Task execution delegation ──

    async def dispatch_delegate(self, *, trigger_id: str, run_id: str, task_id: str, goal: str) -> None:
        """DELEGATE action → OrganizationActionRuntime → OrganizationLoop → old service."""
        await self.action_runtime.execute_action(
            OrganizationAction.DELEGATE,
            trigger_id=trigger_id, run_id=run_id, task_id=task_id, goal=goal,
        )

    async def dispatch_execute(self, *, db_session: AsyncSession, task) -> None:
        """EXECUTE action → OrganizationActionRuntime → OrganizationLoop → old service."""
        await self.action_runtime.execute_action(
            OrganizationAction.EXECUTE,
            db_session=db_session, task=task,
        )

    async def get_task_progress(self, task_id: str) -> dict:
        """Get execution progress — delegates to OrganizationExecutor."""
        return await self.executor.get_progress(task_id)

    async def run_task(self, task_id: str, goal: str, *, channel_id: str = "", workspace_id: str = "", title: str = "") -> None:
        """Unified task orchestration.

        Sets up trigger + OrganizationRun, then delegates through
        OrganizationActionRuntime → OrganizationLoop → old service.
        """
        from backend.services.session.session_hooks import SessionHooks
        from backend.models.session import TriggerType
        from backend.services.task.task_manager import TaskManager

        hooks = SessionHooks(self.db)
        trigger = await hooks.open_trigger(
            channel_id=channel_id, user_msg_id="",
            workspace_id=workspace_id, trigger_type=TriggerType.TASK,
            task_id=task_id,
        )

        # Link or create OrganizationRun
        mgr = TaskManager()
        task_obj = await mgr.get_task(self.db, task_id)
        run_id = task_obj.run_id if task_obj else ""
        if not run_id:
            org_run = await self.start_run(
                run_type="task", source_id=task_id,
                channel_id=channel_id, workspace_id=workspace_id,
                title=title or f"Task: {(task_obj.title if task_obj else goal)[:100]}",
            )
            run_id = org_run.id
        trigger.run_id = run_id
        await self.emit_run_event(trigger.id, "run.created", run_id)

        # Delegate through action_runtime with lifecycle events
        await self.action_runtime.execute_action(
            OrganizationAction.DELEGATE,
            trigger_id=trigger.id, run_id=run_id, task_id=task_id, goal=goal,
        )

    # ── Event helpers ──

    async def emit_run_event(self, trigger_id: str, event_type: str, run_id: str, **extra: str) -> None:
        """Emit a run-scoped lifecycle event (run.created, run.completed)."""
        await self._emit_run_event(trigger_id, event_type, run_id, extra=extra)

    async def execute_action(self, *, trigger_id: str, turn_id: Optional[str] = None, action_type: OrganizationAction, teammate_id: str = "", payload: Optional[dict] = None) -> None:
        """Record an action as a SessionEvent."""
        from backend.services.session.session_hooks import SessionHooks
        hooks = SessionHooks(self.db)
        await hooks.emit_event(trigger_id, turn_id=turn_id, event_type=f"action.{action_type.value}", payload={"action_type": action_type.value, "teammate_id": teammate_id, **(payload or {})})

    # ── Internal ──

    def _state_svc(self):
        from backend.services.organization.registry import OrganizationStateService
        return OrganizationStateService(self.db)

    async def _emit_run_event(self, trigger_id: str, event_type: str, run_id: str, extra: Optional[dict] = None) -> None:
        from backend.services.session.session_hooks import SessionHooks
        hooks = SessionHooks(self.db)
        payload: dict = {"run_id": run_id}
        if extra:
            payload.update(extra)
        await hooks.emit_event(trigger_id, event_type=event_type, payload=payload)


# ── Re-export for route convenience (avoids routes importing teammate_runner) ──
from backend.services.runtime.teammate_runner import resolve_workspace_api_key  # noqa: E402, F401
