"""Memory Intelligence Layer — Memory Retriever.

Retrieves relevant MemoryItems for a given context query.
Bridges MemoryService (storage) → MemoryRanker (scoring).

Flow:
  1. Accept a retrieval query (scope, type hints, keywords)
  2. Fetch candidates from MemoryService
  3. Pass through MemoryRanker for scoring
  4. Return sorted, ranked results
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import MemoryService, get_memory_service


# ═════════════════════════════════════════════════════════════════
# RankedItem (moved from memory_ranker.py — convergence)
# ═════════════════════════════════════════════════════════════════


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


# ── Default weights ──

TYPE_BASE_SCORES: dict[str, float] = {
    MemoryType.EXECUTION: 0.9,
    MemoryType.DECISION: 0.85,
    MemoryType.TASK: 0.7,
    MemoryType.CHANNEL: 0.6,
    MemoryType.WORKSPACE: 0.5,
    MemoryType.EVENT: 0.3,
    MemoryType.GLOBAL: 0.2,
}

RECENCY_HALF_LIFE_HOURS = 24.0
KEYWORD_MATCH_BONUS = 0.3


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

    # ── Public API ──

    def rank(
        self,
        items: list[MemoryItem],
        *,
        query: Any = None,
    ) -> list[RankedItem]:
        if not items:
            return []
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
                item=item, score=round(final, 4),
                type_score=type_score, recency_score=round(recency_score, 4),
                keyword_score=round(keyword_score, 4), boost_multiplier=boost,
            ))
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked

    def _compute_recency(self, item: MemoryItem) -> float:
        now = datetime.now(timezone.utc)
        created = item.created_at or now
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        hours_ago = max(0.0, (now - created).total_seconds() / 3600.0)
        return 2.0 ** (-hours_ago / self._recency_half_life)

    def _compute_keyword_match(self, item: MemoryItem, keywords: list[str]) -> float:
        if not keywords:
            return 0.0
        combined = f"{item.content.lower()} {str(item.metadata).lower()}"
        matches = sum(1 for kw in keywords if kw.lower() in combined)
        if matches == 0:
            return 0.0
        return min(self._keyword_bonus, (matches / len(keywords)) * self._keyword_bonus * 2)

    @staticmethod
    def _get_keywords(query: Any) -> list[str]:
        keywords: list[str] = []
        if hasattr(query, "keywords") and query.keywords:
            keywords = list(query.keywords)
        if hasattr(query, "context_hint") and query.context_hint:
            hint_words = query.context_hint.replace(",", " ").replace(".", " ").split()
            keywords.extend(w for w in hint_words if len(w) > 3)
        return list(set(keywords))

    @staticmethod
    def _get_boost_types(query: Any) -> dict[str, float]:
        if hasattr(query, "boost_types") and query.boost_types:
            return dict(query.boost_types)
        return {}

logger = logging.getLogger("memory.retriever")

# ── Constants ───────────────────────────────────────────────────

DEFAULT_TOP_K = 20
MAX_CANDIDATES = 200


# ═════════════════════════════════════════════════════════════════
# Retrieval Query
# ═════════════════════════════════════════════════════════════════


@dataclass
class RetrievalQuery:
    """Query parameters for memory retrieval.

    At least one of (scope, type_hints, keywords) should be set,
    otherwise get_recent() is used as fallback.

    At the scope level, the caller specifies what slice of memory
    is relevant (e.g. a particular task or channel). Type hints
    narrow which MemoryType buckets to pull from (e.g. EXECUTION +
    DECISION for planning context).
    """

    # ── Scope filters ──
    source_id: Optional[str] = None         # task_id, channel_id, workspace_id
    memory_types: Optional[list[str]] = None  # filter by MemoryType values
    exclude_types: Optional[list[str]] = None  # exclude these types

    # ── Semantic hints (future: embedding search) ──
    keywords: Optional[list[str]] = None    # keyword match candidates
    context_hint: str = ""                  # free-text context description

    # ── Limits ──
    top_k: int = DEFAULT_TOP_K
    max_hours: Optional[float] = None       # time window

    # ── Scoring overrides ──
    boost_types: Optional[dict[str, float]] = None  # type → multiplier


# ═════════════════════════════════════════════════════════════════
# Retrieval Result
# ═════════════════════════════════════════════════════════════════


@dataclass
class RetrievalResult:
    """Result of a memory retrieval query."""

    items: list[RankedItem] = field(default_factory=list)
    total_candidates: int = 0
    returned_count: int = 0
    query: str = ""  # human-readable summary of the query


# ═════════════════════════════════════════════════════════════════
# MemoryRetriever
# ═════════════════════════════════════════════════════════════════


class MemoryRetriever:
    """Retrieves, filters, and ranks MemoryItems for a given query.

    Stateless (all state lives in MemoryService). Thread-safe.
    """

    def __init__(
        self,
        memory_service: Optional[MemoryService] = None,
        ranker: Optional[MemoryRanker] = None,
    ):
        self._service = memory_service or get_memory_service()
        self._ranker = ranker or MemoryRanker()

    # ── Public API ─────────────────────────────────────────────

    async def retrieve(
        self,
        query: RetrievalQuery,
    ) -> RetrievalResult:
        """Execute a retrieval query and return ranked results."""
        candidates = await self._fetch_candidates(query)

        if not candidates:
            return RetrievalResult(
                items=[],
                total_candidates=0,
                returned_count=0,
                query=self._summarize_query(query),
            )

        # Rank
        ranked = self._ranker.rank(candidates, query=query)

        # Apply top_k
        top_k = max(1, min(query.top_k, len(ranked)))
        ranked = ranked[:top_k]

        # Re-score with final scores
        result = RetrievalResult(
            items=ranked,
            total_candidates=len(candidates),
            returned_count=len(ranked),
            query=self._summarize_query(query),
        )

        logger.debug(
            f"Retrieved {len(ranked)}/{len(candidates)} items "
            f"for query: {result.query}"
        )
        return result

    async def retrieve_for_context(
        self,
        *,
        source_id: str,
        memory_types: Optional[list[str]] = None,
        context_hint: str = "",
        top_k: int = DEFAULT_TOP_K,
        max_hours: Optional[float] = None,
    ) -> RetrievalResult:
        """Convenience: retrieve memory as context for PlannerContextBuilder.

        Args:
            source_id: The task/channel/workspace to scope to.
            memory_types: Which memory types to include (default: all).
            context_hint: Free-text description of what context is needed.
            top_k: Max items to return.
            max_hours: Time window filter.

        Returns:
            Ranked retrieval result suitable for compression.
        """
        query = RetrievalQuery(
            source_id=source_id,
            memory_types=memory_types,
            context_hint=context_hint,
            top_k=top_k,
            max_hours=max_hours,
        )
        return await self.retrieve(query)

    # ── Internals ──────────────────────────────────────────────

    async def _fetch_candidates(self, query: RetrievalQuery) -> list[MemoryItem]:
        """Fetch candidate items from MemoryService based on query filters."""
        candidates: list[MemoryItem] = []

        if query.source_id:
            # Fetch by source + each requested type
            if query.memory_types:
                for mt in query.memory_types:
                    batch = await self._service.query(
                        memory_type=mt,
                        source_id=query.source_id,
                        limit=MAX_CANDIDATES,
                    )
                    candidates.extend(batch)
            else:
                # Fetch all types for this source
                batch = await self._service.query(
                    source_id=query.source_id,
                    limit=MAX_CANDIDATES,
                )
                candidates.extend(batch)
        elif query.memory_types:
            # Fetch by type only
            candidates = await self._service.query_by_types(
                query.memory_types,
                limit=MAX_CANDIDATES,
            )
        else:
            # Broad recent query
            candidates = await self._service.get_recent(
                limit=min(MAX_CANDIDATES, query.top_k * 5),
                max_hours=query.max_hours,
            )

        # Apply exclude_types
        if query.exclude_types:
            ex_set = set(query.exclude_types)
            candidates = [c for c in candidates if c.memory_type not in ex_set]

        # Apply max_hours as secondary filter (for source-scoped queries)
        if query.max_hours is not None and query.source_id:
            from datetime import datetime, timezone, timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(hours=query.max_hours)
            candidates = [
                c for c in candidates
                if c.created_at and c.created_at >= cutoff
            ]

        # Keyword pre-filter (quick text match on content)
        if query.keywords:
            kw_lower = [k.lower() for k in query.keywords]
            candidates = [
                c for c in candidates
                if any(kw in c.content.lower() for kw in kw_lower)
            ]

        return candidates

    @staticmethod
    def _summarize_query(query: RetrievalQuery) -> str:
        """Human-readable query summary for logging / debugging."""
        parts = []
        if query.source_id:
            parts.append(f"source={query.source_id[:16]}")
        if query.memory_types:
            parts.append(f"types={','.join(query.memory_types)}")
        if query.keywords:
            parts.append(f"keywords={','.join(query.keywords)}")
        if query.max_hours:
            parts.append(f"window={query.max_hours}h")
        return " | ".join(parts) or "recent"
