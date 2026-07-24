"""OrganizationLearningService — post-run pattern extraction.

Reads OrganizationRun → triggers → turns, computes success/failure
patterns and teammate contributions, persists as TEAM_PATTERN and
MEMBER_KNOWLEDGE MemoryItems.  Failure-safe — never raises.

Ponytail: no new ORM, no new MemoryType, no DAG, no AgentLoop change.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import SessionTrigger, SessionTurn

logger = logging.getLogger(__name__)


class OrganizationLearningService:
    """Extract organization-level feedback from a completed run."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def learn_from_run(self, run_id: str) -> None:
        """Read run → compute patterns → persist as TEAM_PATTERN + MEMBER_KNOWLEDGE.

        Failure-safe: all exceptions are caught and logged.
        """
        try:
            await self._do_learn(run_id)
        except Exception:
            logger.exception("OrganizationLearningService failed for run %s", run_id)

    # ── Internal ──────────────────────────────────────────────────

    async def _do_learn(self, run_id: str) -> None:
        # 1. Read OrganizationRun
        run = await self._get_run(self.db, run_id)
        if run is None:
            return

        # 2. Find triggers for this run
        trig_result = await self.db.execute(
            select(SessionTrigger).where(SessionTrigger.run_id == run_id)
        )
        triggers = list(trig_result.scalars().all())
        if not triggers:
            logger.debug("[Learning] run %s has no triggers, skip", run_id[:8])
            return

        # 3. Read SessionTurns for all triggers
        trigger_ids = [t.id for t in triggers]
        turn_result = await self.db.execute(
            select(SessionTurn).where(SessionTurn.trigger_id.in_(trigger_ids))
        )
        turns = list(turn_result.scalars().all())
        if not turns:
            logger.debug("[Learning] run %s has no turns, skip", run_id[:8])
            return

        # 4. Compute patterns
        total = len(turns)
        failed_turns = [t for t in turns if t.failure]
        failed = len(failed_turns)
        success = total - failed

        teammate_stats: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "failed": 0, "actions": []}
        )
        for turn in turns:
            tid = turn.teammate_id
            teammate_stats[tid]["total"] += 1
            if turn.failure:
                teammate_stats[tid]["failed"] += 1
            if turn.action_type:
                teammate_stats[tid]["actions"].append(turn.action_type)

        workspace_id = run.workspace_id or ""

        # 5. Persist TEAM_PATTERN
        from backend.services.memory.memory_service import get_memory_service
        from backend.services.memory.memory_types import MemoryItem, MemoryType

        mem_svc = get_memory_service()

        success_rate = success / max(total, 1)
        pattern_content = (
            f"[run] id={run_id[:8]} type={run.run_type} "
            f"turns={total} success={success} failed={failed} "
            f"teammates={list(teammate_stats.keys())}"
        )

        await mem_svc.store(MemoryItem(
            memory_type=MemoryType.TEAM_PATTERN.value,
            content=pattern_content,
            source_id=run_id,
            relevance_score=success_rate,
            metadata={
                "run_id": run_id,
                "run_type": run.run_type,
                "status": run.status,
                "total_turns": total,
                "successful_turns": success,
                "failed_turns": failed,
                "teammate_ids": list(teammate_stats.keys()),
                "workspace_id": workspace_id,
                "scope": "team",
            },
        ))

        # 6. Per-teammate MEMBER_KNOWLEDGE
        for teammate_id, stats in teammate_stats.items():
            t = stats["total"]
            f = stats["failed"]
            s = t - f
            rate = s / max(t, 1)
            action_types = sorted(set(stats["actions"])) if stats["actions"] else []

            await mem_svc.store(MemoryItem(
                memory_type=MemoryType.MEMBER_KNOWLEDGE.value,
                content=(
                    f"[member] run={run_id[:8]} teammate={teammate_id} "
                    f"turns={t} success={s} failed={f} rate={rate:.2f} "
                    f"actions={action_types}"
                ),
                source_id=teammate_id,
                relevance_score=rate,
                metadata={
                    "teammate_id": teammate_id,
                    "run_id": run_id,
                    "scope": "member",
                    "total_turns": t,
                    "successful_turns": s,
                    "failed_turns": f,
                    "action_types": action_types,
                    "workspace_id": workspace_id,
                },
            ))

        logger.info(
            "[Learning] run %s → %d turns, %d teammates, %d failures",
            run_id[:8], total, len(teammate_stats), failed,
        )

    @staticmethod
    async def _get_run(db: AsyncSession, run_id: str) -> Optional[object]:
        """Fetch OrganizationRun — avoid circular import at module level."""
        from backend.models.organization_run import OrganizationRun
        return await db.get(OrganizationRun, run_id)
