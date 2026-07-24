"""OrganizationRunInspector — read-only replay from existing session/state data.

No new models, no execution chain changes. Pure queries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.organization_run import OrganizationRun
from backend.models.organization_state import OrganizationState
from backend.models.session import SessionEvent, SessionTrigger, SessionTurn

logger = logging.getLogger(__name__)


class OrganizationRunInspector:
    """Read-only query layer over OrganizationRun + SessionEvent + OrganizationState."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_timeline(self, run_id: str) -> list[dict]:
        """Return ordered event chain for a run: trigger → events sorted by timestamp."""
        triggers = await self._load_triggers(run_id)
        if not triggers:
            return []

        trigger_ids = [t.id for t in triggers]
        stmt = (
            select(SessionEvent)
            .where(SessionEvent.trigger_id.in_(trigger_ids))
            .order_by(SessionEvent.timestamp)
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        trigger_map = {t.id: t for t in triggers}
        out = []
        for ev in rows:
            trigger = trigger_map.get(ev.trigger_id)
            out.append({
                "event_id": ev.id,
                "trigger_id": ev.trigger_id,
                "trigger_type": trigger.trigger_type if trigger else None,
                "turn_id": ev.turn_id,
                "event_type": ev.event_type,
                "payload": ev.payload or {},
                "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
            })
        return out

    async def get_state_snapshot(self, run_id: str) -> dict:
        """Return current OrganizationState for a run, grouped by state_type."""
        stmt = select(OrganizationState).where(OrganizationState.run_id == run_id)
        rows = (await self.db.execute(stmt)).scalars().all()

        snapshot: dict[str, dict] = {}
        for s in rows:
            if s.state_type not in snapshot:
                snapshot[s.state_type] = {}
            snapshot[s.state_type][s.key] = s.value
        return snapshot

    async def summarize_run(self, run_id: str) -> dict:
        """Aggregate: duration, actions, teammates, failures, run meta."""
        run = await self.db.get(OrganizationRun, run_id)
        if run is None:
            return {"run_id": run_id, "status": "not_found"}

        triggers = await self._load_triggers(run_id)
        trigger_ids = [t.id for t in triggers]

        # Events
        ev_stmt = select(SessionEvent).where(SessionEvent.trigger_id.in_(trigger_ids))
        events = (await self.db.execute(ev_stmt)).scalars().all()
        action_events = [e for e in events if e.event_type and e.event_type.startswith("action.")]
        failures = [e for e in action_events if e.event_type == "action.failed"]

        # Turns → teammates
        turn_stmt = select(SessionTurn).where(SessionTurn.trigger_id.in_(trigger_ids))
        turns = (await self.db.execute(turn_stmt)).scalars().all()
        teammates = list({t.teammate_id for t in turns if t.teammate_id})

        # Duration
        duration: Optional[float] = None
        if run.created_at and run.ended_at:
            start = run.created_at if not run.created_at.tzinfo else run.created_at.replace(tzinfo=None)
            end = run.ended_at if not run.ended_at.tzinfo else run.ended_at.replace(tzinfo=None)
            duration = (end - start).total_seconds()

        return {
            "run_id": run.id,
            "run_type": run.run_type,
            "title": run.title,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "duration_seconds": duration,
            "action_count": len(action_events),
            "failure_count": len(failures),
            "failed_actions": [
                {"event_type": e.event_type, "payload": e.payload, "timestamp": e.timestamp.isoformat() if e.timestamp else None}
                for e in failures
            ],
            "teammates": teammates,
            "trigger_count": len(triggers),
        }

    async def _load_triggers(self, run_id: str) -> list[SessionTrigger]:
        stmt = select(SessionTrigger).where(SessionTrigger.run_id == run_id)
        return list((await self.db.execute(stmt)).scalars().all())
