"""OrganizationRunService — CRUD for OrganizationRun, no lifecycle hooks."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.organization_run import OrganizationRun


class OrganizationRunService:
    """Minimal CRUD for OrganizationRun. Caller owns commit/flush."""

    @staticmethod
    async def create_run(
        db: AsyncSession,
        *,
        run_type: str,
        source_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> OrganizationRun:
        run = OrganizationRun(
            run_type=run_type,
            source_id=source_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            title=title,
        )
        db.add(run)
        await db.flush()
        return run

    @staticmethod
    async def close_run(
        db: AsyncSession,
        run_id: str,
        *,
        status: str = "completed",
    ) -> None:
        from datetime import datetime, timezone

        run = await db.get(OrganizationRun, run_id)
        if run is None:
            return
        run.status = status
        run.ended_at = datetime.now(timezone.utc)
        await db.flush()

    @staticmethod
    async def get_run(db: AsyncSession, run_id: str) -> Optional[OrganizationRun]:
        return await db.get(OrganizationRun, run_id)

    @staticmethod
    async def get_run_context(
        db: AsyncSession,
        run_id: str,
    ) -> dict:
        """Return a flat context dict for a run — goal, history stub, channel, members."""
        run = await db.get(OrganizationRun, run_id)
        if run is None:
            return {}

        ctx: dict = {
            "run_id": run.id,
            "run_type": run.run_type,
            "title": run.title or "",
            "channel_id": run.channel_id or "",
            "workspace_id": run.workspace_id or "",
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }

        # ── Channel members ──
        if run.channel_id:
            from sqlalchemy import select
            from backend.models.chat import Channel as ChannelModel

            ch_result = await db.execute(
                select(ChannelModel).where(ChannelModel.id == run.channel_id)
            )
            ch = ch_result.scalar_one_or_none()
            if ch:
                ctx["members"] = ch.teammate_ids or []
                ctx["channel_name"] = ch.name or ""

        # ── Trigger / session data (chat) ──
        if run.run_type == "chat" and run.source_id:
            from backend.models.session import SessionTrigger, SessionTurn

            trigger = await db.get(SessionTrigger, run.source_id)
            if trigger:
                ctx["trigger_type"] = trigger.trigger_type
                ctx["trigger_time"] = trigger.trigger_time.isoformat() if trigger.trigger_time else None
                # recent turns
                turn_result = await db.execute(
                    select(SessionTurn)
                    .where(SessionTurn.trigger_id == run.source_id)
                    .order_by(SessionTurn.start_time)
                    .limit(10)
                )
                turns = list(turn_result.scalars().all())
                ctx["recent_turns"] = [
                    {"teammate_id": t.teammate_id, "action": t.action, "failure": t.failure}
                    for t in turns
                ]

        # ── Task data ──
        if run.run_type == "task" and run.source_id:
            from backend.models.task import TaskModel

            task = await db.get(TaskModel, run.source_id)
            if task:
                ctx["task_id"] = task.id
                ctx["task_status"] = task.status
                ctx["goal"] = task.intent or task.title or ""
                ctx["steps_count"] = len(task.steps or [])

        return ctx


# ── Unified exports ──
from .runtime import OrganizationRuntime
from .engine import OrganizationLoop, OrganizationDecisionEngine
from .context import OrganizationContext, OrganizationContextBuilder
from .registry import CapabilityRegistry, OrganizationStateService
from .state import OrganizationStateManager
from .execution import OrganizationExecutor
from .action_runtime import OrganizationActionRuntime
from .router import OrganizationActionRouter
from .task_adapter import TaskActionAdapter
