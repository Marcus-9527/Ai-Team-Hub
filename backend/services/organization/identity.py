"""TeammateIdentityService — identity aggregator from existing data.

Reads: Teammate model (role), CapabilityRegistry (capabilities),
BrainFragment (skills, behaviors), MemoryItem (collaboration style),
SessionTurn (performance). No new models, no new storage.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.chat import Teammate
from backend.models.session import SessionTurn

logger = logging.getLogger(__name__)


class TeammateIdentityService:
    """Read-only aggregator for teammate identity."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_identity(
        self,
        teammate_id: str,
        workspace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        role = "assistant"
        tm = await self.db.get(Teammate, teammate_id)
        if tm:
            role = tm.role or "assistant"

        # Capabilities from registry defaults
        from backend.services.organization.registry import DEFAULT_ROLE_CAPABILITIES
        capabilities = list(DEFAULT_ROLE_CAPABILITIES.get(role, []))

        # Skills + behaviors via BrainFragmentStore
        from backend.services.brain.fragment_store import (
            get_brain_fragment_store, BrainFragmentType,
        )
        store = get_brain_fragment_store()
        fragments = await store.get_all_by_teammate(teammate_id)
        skills = [f.content for f in fragments if f.fragment_type == BrainFragmentType.SKILLS.value]
        learned = [
            f.content for f in fragments
            if f.fragment_type in (
                BrainFragmentType.BEHAVIOR_SUGGESTION.value,
                BrainFragmentType.LESSONS.value,
            )
        ]

        # Performance from SessionTurn stats
        row = (await self.db.execute(
            select(
                func.count().label("total"),
                func.sum(case((SessionTurn.failure == None, 1), else_=0)).label("completed"),
                func.sum(case((SessionTurn.failure != None, 1), else_=0)).label("failed"),
                func.count(func.distinct(SessionTurn.trigger_id)).label("recent_runs"),
            ).where(SessionTurn.teammate_id == teammate_id)
        )).one()
        perf = {
            "total_actions": row.total or 0,
            "completed": row.completed or 0,
            "failed": row.failed or 0,
            "recent_runs": row.recent_runs or 0,
        }

        # Collaboration style + performance trend from MEMBER_KNOWLEDGE
        from backend.services.memory.memory_types import MemoryType
        from backend.services.memory.memory_service import get_memory_service
        mem_svc = get_memory_service()
        collab = []

        # Collaboration style: recent MemoryItems across all teammates
        for mt in (MemoryType.MEMBER_KNOWLEDGE, MemoryType.TEAM_PATTERN):
            for m in await mem_svc.query(memory_type=mt.value, limit=3):
                if m.content:
                    collab.append(m.content[:200])

        # Performance trend: per-teammate MEMBER_KNOWLEDGE items (latest 2 for delta)
        perf_items = await mem_svc.query(
            memory_type=MemoryType.MEMBER_KNOWLEDGE.value,
            source_id=teammate_id, limit=2,
        )
        performance_trend = {"current": {"success_rate": 0.0}, "trend": {"completed": 0, "failed": 0}}
        if perf_items:
            import re
            rates = []
            for item in reversed(perf_items):
                m = re.search(r"completed=(\d+) failed=(\d+) rate=([\d.]+)", item.content)
                if m:
                    c, f, r = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    rates.append({"success_rate": round(r, 2), "completed": c, "failed": f})
            if rates:
                performance_trend["current"] = {"success_rate": rates[-1]["success_rate"]}
                if len(rates) >= 2:
                    d = {"completed": rates[-1]["completed"] - rates[-2]["completed"],
                         "failed": rates[-1]["failed"] - rates[-2]["failed"]}
                else:
                    d = {"completed": rates[-1]["completed"], "failed": rates[-1]["failed"]}
                performance_trend["trend"] = d

        return {
            "id": teammate_id,
            "role": role,
            "capabilities": capabilities,
            "skills": skills,
            "learned_behaviors": learned,
            "recent_performance": perf,
            "collaboration_style": collab,
            "performance_trend": performance_trend,
        }
