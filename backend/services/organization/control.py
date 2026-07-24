"""OrganizationControl — run pause/resume/cancel + status query.

No new models, no execution chain changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.organization_run import OrganizationRun
from backend.models.organization_state import OrganizationState


class OrganizationControl:
    """Run lifecycle controls — pause, resume, cancel, status query."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_status(self, run_id: str) -> dict:
        """Current run status with action, progress, and latest event."""
        run = await self.db.get(OrganizationRun, run_id)
        if run is None:
            return {"run_id": run_id, "status": "not_found"}

        result: dict = {"run_id": run.id, "status": run.status}

        # current_action + progress state
        state_result = await self.db.execute(
            select(OrganizationState).where(
                OrganizationState.run_id == run_id,
                OrganizationState.state_type.in_(["current_action", "progress"]),
            )
        )
        states: dict[str, dict] = {}
        for s in state_result.scalars().all():
            states[s.state_type] = s.value or {}
        result["current_action"] = states.get("current_action")
        result["progress_state"] = states.get("progress")

        # Latest session event for this run
        from backend.models.session import SessionEvent, SessionTrigger
        ev = (
            await self.db.execute(
                select(SessionEvent)
                .join(SessionTrigger, SessionEvent.trigger_id == SessionTrigger.id)
                .where(SessionTrigger.run_id == run_id)
                .order_by(SessionEvent.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        result["latest_event"] = {
            "event_type": ev.event_type,
            "payload": ev.payload or {},
            "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
        } if ev else None

        return result

    async def pause_run(self, run_id: str) -> Optional[OrganizationRun]:
        """Pause → status='paused', emit run.paused."""
        run = await self.db.get(OrganizationRun, run_id)
        if run is None:
            return None
        run.status = "paused"
        await self.db.flush()
        await self._emit_control_event(run_id, "run.paused")
        return run

    async def resume_run(self, run_id: str) -> Optional[OrganizationRun]:
        """Resume → status='running', emit run.resumed."""
        run = await self.db.get(OrganizationRun, run_id)
        if run is None:
            return None
        run.status = "running"
        await self.db.flush()
        await self._emit_control_event(run_id, "run.resumed")
        return run

    async def cancel_run(self, run_id: str) -> Optional[OrganizationRun]:
        """Cancel → status='cancelled' + ended_at, emit run.cancelled."""
        run = await self.db.get(OrganizationRun, run_id)
        if run is None:
            return None
        run.status = "cancelled"
        run.ended_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self._emit_control_event(run_id, "run.cancelled")
        return run

    # ── Internal ──

    async def _emit_control_event(self, run_id: str, event_type: str) -> None:
        """Emit a run-scoped event via the latest trigger for this run."""
        from backend.models.session import SessionTrigger
        from backend.services.session.session_hooks import SessionHooks

        trig = (
            await self.db.execute(
                select(SessionTrigger)
                .where(SessionTrigger.run_id == run_id)
                .order_by(SessionTrigger.trigger_time.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if trig is None:
            return  # ponytail: no trigger → no event, no-op
        hooks = SessionHooks(self.db)
        await hooks.emit_event(trig.id, event_type=event_type, payload={"run_id": run_id})
