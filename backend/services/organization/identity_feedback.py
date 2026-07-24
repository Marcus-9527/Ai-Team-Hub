"""IdentityFeedbackService — post-run identity evolution.

After a run finishes, extract performance signals from SessionTurn/SessionEvent
and persist as MEMBER_KNOWLEDGE MemoryItems.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import SessionTrigger, SessionTurn

logger = logging.getLogger(__name__)


class IdentityFeedbackService:
    """Post-run identity updater. Failure-safe."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def process_run(self, run_id: str) -> None:
        """Read run output, compute per-teammate stats, persist as MEMBER_KNOWLEDGE."""
        # Find triggers for this run
        trig_result = await self.db.execute(
            select(SessionTrigger).where(SessionTrigger.run_id == run_id)
        )
        triggers = list(trig_result.scalars().all())
        if not triggers:
            return

        trigger_ids = [t.id for t in triggers]

        # Count SessionTurns grouped by teammate
        turn_result = await self.db.execute(
            select(SessionTurn).where(SessionTurn.trigger_id.in_(trigger_ids))
        )
        stats: dict[str, dict[str, int]] = defaultdict(lambda: {"completed": 0, "failed": 0})
        for turn in turn_result.scalars():
            tid = turn.teammate_id
            if turn.failure:
                stats[tid]["failed"] += 1
            else:
                stats[tid]["completed"] += 1

        if not stats:
            return

        # Persist as MEMBER_KNOWLEDGE
        from backend.services.memory.memory_types import MemoryItem, MemoryType
        from backend.services.memory.memory_service import get_memory_service

        mem_svc = get_memory_service()
        for teammate_id, s in stats.items():
            total = s["completed"] + s["failed"]
            rate = s["completed"] / total if total > 0 else 0.0
            content = (
                f"[performance] completed={s['completed']} "
                f"failed={s['failed']} rate={rate:.2f}"
            )
            await mem_svc.store(MemoryItem(
                memory_type=MemoryType.MEMBER_KNOWLEDGE.value,
                content=content,
                source_id=teammate_id,
                relevance_score=rate,
                metadata={"scope": "member", "teammate_id": teammate_id},
            ))
