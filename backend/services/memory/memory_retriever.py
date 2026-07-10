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
from typing import Optional

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import MemoryService, get_memory_service
from backend.services.memory.memory_ranker import MemoryRanker, RankedItem

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
