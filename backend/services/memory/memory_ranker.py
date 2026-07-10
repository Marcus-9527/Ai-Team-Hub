"""Memory Intelligence Layer — Memory Ranker.

Multi-factor relevance ranking for MemoryItems.

Factors:
  - Type priority (EXECUTION > DECISION > TASK > ...)
  - Recency (newer = higher score)
  - Content match (keyword overlap with query)
  - Boost multipliers (per-type overrides)

Output: sorted list of RankedItem with final scores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from backend.services.memory.memory_types import MemoryItem, MemoryType

logger = logging.getLogger("memory.ranker")

# ── Default weights ─────────────────────────────────────────────

# Base score from type priority mapping
TYPE_BASE_SCORES: dict[str, float] = {
    MemoryType.EXECUTION: 0.9,
    MemoryType.DECISION: 0.85,
    MemoryType.TASK: 0.7,
    MemoryType.CHANNEL: 0.6,
    MemoryType.WORKSPACE: 0.5,
    MemoryType.EVENT: 0.3,
    MemoryType.GLOBAL: 0.2,
}

RECENCY_HALF_LIFE_HOURS = 24.0  # score drops by half every 24h
KEYWORD_MATCH_BONUS = 0.3


@dataclass
class RankedItem:
    """A MemoryItem with its computed rank score."""

    item: MemoryItem
    score: float = 0.0

    # Score breakdown (for debugging / tuning)
    type_score: float = 0.0
    recency_score: float = 0.0
    keyword_score: float = 0.0
    boost_multiplier: float = 1.0


# ═════════════════════════════════════════════════════════════════
# MemoryRanker
# ═════════════════════════════════════════════════════════════════


class MemoryRanker:
    """Computes multi-factor relevance scores for MemoryItems.

    Use:
        ranker = MemoryRanker()
        ranked = ranker.rank(items, query=query)
    """

    def __init__(
        self,
        type_scores: Optional[dict[str, float]] = None,
        recency_half_life: float = RECENCY_HALF_LIFE_HOURS,
        keyword_bonus: float = KEYWORD_MATCH_BONUS,
    ):
        self._type_scores = {**TYPE_BASE_SCORES, **(type_scores or {})}
        self._recency_half_life = recency_half_life
        self._keyword_bonus = keyword_bonus

    # ── Public API ─────────────────────────────────────────────

    def rank(
        self,
        items: list[MemoryItem],
        *,
        query: Any = None,
    ) -> list[RankedItem]:
        """Rank items by multi-factor relevance.

        Args:
            items: MemoryItems to rank.
            query: Optional RetrievalQuery for keyword matching and boosts.

        Returns:
            List of RankedItem sorted by score (descending).
        """
        if not items:
            return []

        # Extract query info
        keywords = self._get_keywords(query)
        boost_types = self._get_boost_types(query)

        ranked: list[RankedItem] = []

        for item in items:
            type_score = self._type_scores.get(item.memory_type, 0.1)
            recency_score = self._compute_recency(item)
            keyword_score = self._compute_keyword_match(item, keywords)
            boost = boost_types.get(item.memory_type, 1.0) if boost_types else 1.0

            final = (type_score + recency_score + keyword_score) * boost

            ranked.append(RankedItem(
                item=item,
                score=round(final, 4),
                type_score=type_score,
                recency_score=round(recency_score, 4),
                keyword_score=round(keyword_score, 4),
                boost_multiplier=boost,
            ))

        # Sort descending by score
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked

    # ── Scoring internals ──────────────────────────────────────

    def _compute_recency(self, item: MemoryItem) -> float:
        """Compute recency score [0, 1] with exponential decay.

        Score = 2^(-hours_ago / half_life)

        Recent items → near 1.0. Old items → near 0.0.
        """
        now = datetime.now(timezone.utc)
        created = item.created_at or now

        # Handle naive vs aware
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        hours_ago = (now - created).total_seconds() / 3600.0
        if hours_ago < 0:
            hours_ago = 0.0

        return 2.0 ** (-hours_ago / self._recency_half_life)

    def _compute_keyword_match(
        self,
        item: MemoryItem,
        keywords: list[str],
    ) -> float:
        """Compute keyword overlap score [0, 1]."""
        if not keywords:
            return 0.0

        content_lower = item.content.lower()
        meta_str = str(item.metadata).lower()
        combined = content_lower + " " + meta_str

        matches = sum(1 for kw in keywords if kw.lower() in combined)
        if matches == 0:
            return 0.0

        # Scale: 0.3 * (matches / total_keywords), capped at keyword_bonus
        ratio = matches / len(keywords)
        return min(self._keyword_bonus, ratio * self._keyword_bonus * 2)

    @staticmethod
    def _get_keywords(query: Any) -> list[str]:
        """Extract keywords from query object (duck-typing)."""
        keywords: list[str] = []
        if hasattr(query, "keywords") and query.keywords:
            keywords = list(query.keywords)
        if hasattr(query, "context_hint") and query.context_hint:
            hint_words = query.context_hint.replace(",", " ").replace(".", " ").split()
            keywords.extend(w for w in hint_words if len(w) > 3)
        return list(set(keywords))

    @staticmethod
    def _get_boost_types(query: Any) -> dict[str, float]:
        """Extract type boosts from query."""
        if hasattr(query, "boost_types") and query.boost_types:
            return dict(query.boost_types)
        return {}
