"""OrganizationExperienceService — keyword overlap over existing MemoryItems."""

from __future__ import annotations

import logging
from typing import Optional

from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_types import MemoryType

logger = logging.getLogger(__name__)

_EXPERIENCE_TYPES = [
    MemoryType.PROJECT_KNOWLEDGE,
    MemoryType.MEMBER_KNOWLEDGE,
    MemoryType.TEAM_PATTERN,
]


class OrganizationExperienceService:
    """Query past organizational experience via keyword overlap on MemoryItems.

    ponytail: keyword overlap (no embeddings, no AI). Fine at current scale;
    upgrade to tf-idf or embedding if precision matters.
    """

    async def find_similar_experience(
        self,
        goal: str,
        workspace_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict]:
        if not goal or not goal.strip():
            return []

        mem_svc = get_memory_service()
        items = await mem_svc.query_by_types(
            [t.value for t in _EXPERIENCE_TYPES], limit=200,
        )

        keywords = {w.lower() for w in goal.split() if len(w) > 2}
        if not keywords:
            return []

        scored: list[tuple[float, int]] = []
        for item in items:
            content = (item.content or "").lower()
            overlap = sum(1 for kw in keywords if kw in content)
            if overlap > 0:
                scored.append((overlap / len(keywords), item))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        result = []
        for score, item in top:
            meta = item.metadata or {}
            result.append({
                "goal": (item.content or "")[:200],
                "teammate": meta.get("teammate_id", meta.get("teammate", "")),
                "result": meta.get("result", meta.get("outcome", "")),
                "lesson": meta.get("lesson", meta.get("learned", "")),
            })

        return result
