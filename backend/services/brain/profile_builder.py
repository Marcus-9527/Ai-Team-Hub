"""services/brain/profile_builder.py — TeammateProfileBuilder (Ponytail ultra)

Aggregates existing data (BrainFragment / MemoryItem / SessionTurn) into
a flat teammate profile dict. No new storage.

ponytail: pure aggregation class, no new tables, no new models.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import SessionTurn
from backend.services.brain.fragment_store import (
    BrainFragmentStore,
    get_brain_fragment_store,
    BrainFragmentType,
)
from backend.services.memory.memory_service import get_memory_service, MemoryService
from backend.services.memory.memory_types import MemoryType

logger = logging.getLogger("brain.profile_builder")


class TeammateProfileBuilder:
    """Aggregate existing data → teammate personality/work_style/preferences/expertise.

    No new storage. Reads from BrainFragmentStore + MemoryService + SessionTurn.
    All source data already exists in memory_items / session_turns tables.
    """

    def __init__(
        self,
        fragment_store: Optional[BrainFragmentStore] = None,
        memory_service: Optional[MemoryService] = None,
    ):
        self._store = fragment_store or get_brain_fragment_store()
        self._mem_svc = memory_service or get_memory_service()

    async def build(
        self,
        teammate_id: str,
        *,
        workspace_id: str = "",
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """Build a teammate profile from existing data sources.

        Returns dict with keys:
          personality, work_style, preferences, expertise
        """
        fragments = await self._store.get_all_by_teammate(
            teammate_id, workspace_id=workspace_id,
        )
        frag_map = {f.fragment_type: f.content for f in fragments}

        personality = frag_map.get(BrainFragmentType.PERSONALITY.value, "")
        preferences = frag_map.get(BrainFragmentType.PREFERENCES.value, "")
        skills = frag_map.get(BrainFragmentType.SKILLS.value, "")
        principles = frag_map.get(BrainFragmentType.PRINCIPLES.value, "")
        identity = frag_map.get(BrainFragmentType.IDENTITY.value, "")

        # ── Work style: combine personality + principles ──
        parts = [p for p in [personality, principles] if p]
        work_style = " | ".join(parts) if parts else ""

        # ── Expertise from skills fragment + recent turn action_types ──
        expertise_parts: list[str] = []
        if skills:
            expertise_parts.extend(s.strip() for s in skills.split(",") if s.strip())
        if identity:
            # ponytail: single-line identity summary as expertise hint
            first_line = identity.split("\n")[0][:200]
            expertise_parts.append(first_line)

        # ponytail: O(n) scan limited to 20 turns — fine at local scale
        if db is not None:
            recent_turns = await self._recent_turns_for_teammate(
                db, teammate_id, limit=20,
            )
            seen: set[str] = set()
            for t in recent_turns:
                for attr in ("action_type", "turn_type"):
                    val = getattr(t, attr, None) or ""
                    if val and val not in seen:
                        seen.add(val)
                        expertise_parts.append(f"experienced_in:{val}")

        return {
            "personality": personality,
            "work_style": work_style,
            "preferences": preferences,
            "expertise": list(dict.fromkeys(expertise_parts)),  # dedupe, preserve order
        }

    async def _recent_turns_for_teammate(
        self, db: AsyncSession, teammate_id: str, limit: int = 20,
    ) -> list[SessionTurn]:
        result = await db.execute(
            select(SessionTurn)
            .where(SessionTurn.teammate_id == teammate_id)
            .order_by(SessionTurn.start_time.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
