"""services/brain/context.py — BrainContextAssembler (Phase 7.0)

Single point for fetching all brain context data from services.
Separates data fetching (here) from prompt formatting (BrainLoader).

Phase 14 enhancements:
  - TeammateProfileBuilder integration → profile sections
  - History summary from recent SessionTurns
  - Collaboration pattern from TEAM_PATTERN memories
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
)
from backend.services.brain.profile_builder import TeammateProfileBuilder
from backend.services.memory.memory_service import get_memory_service, MemoryService
from backend.services.memory.memory_types import MemoryType

logger = logging.getLogger("brain.context")


class BrainContextAssembler:
    """Fetch all context data for a teammate.

    Returns a flat dict consumed by BrainLoader._format().
    Phase 14: adds teammate_profile, history_summary, collaboration_pattern.
    """

    def __init__(
        self,
        fragment_store: Optional[BrainFragmentStore] = None,
        memory_service: Optional[MemoryService] = None,
    ):
        self._store = fragment_store or get_brain_fragment_store()
        self._mem_svc = memory_service or get_memory_service()
        self._profile_builder = TeammateProfileBuilder(
            fragment_store=fragment_store, memory_service=memory_service,
        )

    async def assemble(
        self,
        teammate_id: str,
        *,
        workspace_id: str = "",
        query: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        recent_memory_limit: int = 10,
        experience: Optional[list[dict]] = None,
    ) -> dict:
        """Fetch all context data. Returns dict consumed by BrainLoader._format()."""
        fragments = await self._store.get_all_by_teammate(teammate_id)

        # ── Auto-fetch experience from query if not explicitly provided ──
        if experience is None and query and recent_memory_limit > 0:
            from backend.services.organization.experience import OrganizationExperienceService
            try:
                exp_svc = OrganizationExperienceService()
                experience = await exp_svc.find_similar_experience(query, limit=5)
            except Exception:
                experience = []

        # ── Teammate Identity (when db is provided) ──
        identity_data = None
        if db is not None:
            from backend.services.organization.identity import TeammateIdentityService
            id_svc = TeammateIdentityService(db)
            identity_data = await id_svc.get_identity(teammate_id, workspace_id=workspace_id)

        # ── Organization Knowledge (cross-run) ──
        knowledge_items: dict = {}
        if recent_memory_limit > 0:
            for ktype in (MemoryType.PROJECT_KNOWLEDGE, MemoryType.MEMBER_KNOWLEDGE, MemoryType.TEAM_PATTERN):
                items = await self._mem_svc.query(
                    memory_type=ktype, limit=min(recent_memory_limit, 5),
                )
                if items:
                    knowledge_items[ktype.value] = items  # e.g. "PROJECT_KNOWLEDGE"

        # ── Memory context — semantic when query provided, keyword otherwise ──
        recent_memory_text = ""
        recent_memory_is_semantic = False
        if recent_memory_limit > 0:
            if query:
                mem_text = await self.semantic_recall(
                    query, teammate_id=teammate_id, top_k=recent_memory_limit,
                )
                if mem_text:
                    recent_memory_text = mem_text
                    recent_memory_is_semantic = True
            else:
                mem_items = await self._mem_svc.query_teammate_memory(
                    teammate_id, limit=recent_memory_limit,
                )
                if mem_items:
                    lines = [f"  - {(m.content or '')[:200].replace(chr(10), ' ')}" for m in mem_items]
                    recent_memory_text = "\n".join(lines)

        # ── Team / project context (when workspace is known) ──
        team_items: list = []
        proj_items: list = []
        if workspace_id:
            team_items = await self._mem_svc.query_by_scope("team", limit=3)
            proj_items = await self._mem_svc.query_by_scope("project", limit=3)

        # ── Phase 14: Teammate profile (when db is provided) ──
        teammate_profile: dict = {}
        if db is not None:
            teammate_profile = await self._profile_builder.build(
                teammate_id, workspace_id=workspace_id, db=db,
            )

        # ── Phase 14: History summary from recent turns (when db is provided) ──
        history_summary = ""
        if db is not None:
            history_summary = await self._build_history_summary(db, teammate_id)

        # ── Phase 14: Collaboration pattern from TEAM_PATTERN memories ──
        collaboration_pattern = ""
        collab_mems = await self._mem_svc.query(
            memory_type=MemoryType.TEAM_PATTERN, limit=3,
        )
        if collab_mems:
            collab_lines = []
            for m in collab_mems:
                collab_lines.append(f"  - {(m.content or '')[:300].replace(chr(10), ' ')}")
            collaboration_pattern = "\n".join(collab_lines)

        return {
            "fragments": fragments,
            "workspace_id": workspace_id,
            "identity": identity_data,
            "knowledge_items": knowledge_items,
            "recent_memory_text": recent_memory_text,
            "recent_memory_is_semantic": recent_memory_is_semantic,
            "experience": experience or [],
            "team_items": team_items,
            "proj_items": proj_items,
            # Phase 14
            "teammate_profile": teammate_profile,
            "history_summary": history_summary,
            "collaboration_pattern": collaboration_pattern,
        }

    async def _build_history_summary(
        self, db: AsyncSession, teammate_id: str, limit: int = 10,
    ) -> str:
        """Aggregate recent turns into a short history summary."""
        result = await db.execute(
            select(SessionTurn)
            .where(SessionTurn.teammate_id == teammate_id)
            .order_by(SessionTurn.start_time.desc())
            .limit(limit)
        )
        turns = list(result.scalars().all())
        if not turns:
            return ""
        lines = []
        for t in reversed(turns):  # chronological
            action = t.action_type or t.action or "responded"
            outcome = "failed" if t.failure else "ok"
            tokens = (t.tokens_in or 0) + (t.tokens_out or 0)
            ts = t.start_time.strftime("%H:%M") if t.start_time else ""
            lines.append(f"  - [{ts}] {action} ({outcome}, {tokens}t)" if tokens else f"  - [{ts}] {action} ({outcome})")
        return "\n".join(lines)

    async def semantic_recall(
        self,
        query: str,
        *,
        teammate_id: str,
        scope: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.1,
    ) -> str:
        """Semantic recall: embed query → scoped similarity search → formatted text."""
        if not query or not query.strip():
            return ""
        query_vector = self._mem_svc.compute_embedding(query)
        filters: dict = {"teammate_id": teammate_id}
        if scope:
            filters["scope"] = scope
        items = await self._mem_svc.semantic_search(
            query_vector, top_k=top_k, min_score=min_score,
            metadata_filters=filters,
        )
        if not items:
            return ""
        lines = [f"  - [{m.relevance_score:.2f}] {(m.content or '')[:300].replace(chr(10), ' ')}" for m in items]
        return "\n".join(lines)
