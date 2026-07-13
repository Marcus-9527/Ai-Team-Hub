"""brain/consolidation.py — Memory Fusion (Phase 12.5)

Memory → Brain consolidation:
  Memory = 短期经验 (EXECUTION, DECISION, EVENT)
  Brain = 长期知识 (brain:* fragments)

当同一 teammate 的 memory 中出现重复模式（同类关键词出现 N 次），
自动合并为一条 long-term lesson/decision/fact 写入 brain fragment。

Ponytail: 基于关键词重叠的简单聚类，不用 ML。
阈值 3+ 同类事件触发 consolidation。
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.services.memory.memory_service import get_memory_service, MemoryService
from backend.services.memory.memory_types import MemoryType
from backend.services.brain.fragment_store import (
    BrainFragmentStore,
    get_brain_fragment_store,
    BrainFragment,
    BrainFragmentType,
)

logger = logging.getLogger("brain.consolidation")

# ── Stop words for keyword extraction ──
_STOP_WORDS = {
    "the", "a", "an", "is", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after",
    "above", "below", "between", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "about", "up", "what", "which", "who",
    "step", "task", "outcome", "duration", "ms", "output",
    "objective", "completed", "failed", "status", "execution",
    # Chinese stop words
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这",
}


def _extract_keywords(text: str, max_keywords: int = 8) -> set[str]:
    """Extract meaningful keywords from text (en+zh)."""
    # Lowercase, split words, filter stop words and short words
    words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) >= 2}


def _keyword_overlap(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two keyword sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


CONSOLIDATION_THRESHOLD = 3       # N similar items → trigger consolidation
OVERLAP_THRESHOLD = 0.3           # Jaccard minimum for "similar"
LOOKBACK_HOURS = 48               # scan memory items from last N hours


class MemoryConsolidationService:
    """Scan recent memory items and consolidate repeated patterns into brain fragments."""

    def __init__(
        self,
        mem_svc: Optional[MemoryService] = None,
        frag_store: Optional[BrainFragmentStore] = None,
    ):
        self._mem_svc = mem_svc or get_memory_service()
        self._store = frag_store or get_brain_fragment_store()

    async def consolidate(self, lookback_hours: int = LOOKBACK_HOURS) -> int:
        """Run one consolidation pass. Returns number of fragments created."""
        # 1. Get recent teammate-scoped memory
        items = await self._mem_svc.get_recent(
            limit=500,
            max_hours=lookback_hours,
        )
        if not items:
            return 0

        # 2. Group by teammate (from metadata) and memory type
        by_teammate: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for item in items:
            tm_id = (item.metadata or {}).get("teammate_id", "")
            if not tm_id:
                continue
            by_teammate[tm_id][item.memory_type].append(item)

        created = 0
        for teammate_id, type_groups in by_teammate.items():
            for mem_type, mem_items in type_groups.items():
                created += await self._consolidate_type(teammate_id, mem_type, mem_items)

        if created:
            logger.info("[Consolidation] created %d brain fragments across %d teammates",
                        created, len(by_teammate))
        return created

    async def _consolidate_type(
        self, teammate_id: str, mem_type: str, items: list,
    ) -> int:
        """Consolidate memory items of one type for one teammate."""
        if len(items) < CONSOLIDATION_THRESHOLD:
            return 0

        # Extract keywords from each item
        keyword_sets = [_extract_keywords(it.content or "") for it in items]

        # Group by pairwise similarity (simple centroid clustering)
        clusters: list[list[int]] = []
        for i in range(len(items)):
            if not keyword_sets[i]:
                continue
            placed = False
            for cluster in clusters:
                # Compare with first item in cluster
                if _keyword_overlap(keyword_sets[i], keyword_sets[cluster[0]]) >= OVERLAP_THRESHOLD:
                    cluster.append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])

        created = 0
        for cluster in clusters:
            if len(cluster) < CONSOLIDATION_THRESHOLD:
                continue
            # Build consolidated fragment
            indices = cluster
            cluster_items = [items[i] for i in indices]

            # Content = summary of repeated patterns
            lines = [f"[Consolidated from {len(cluster_items)} similar experiences]"]
            for it in cluster_items[:5]:  # keep first 5 as examples
                lines.append(f"- {(it.content or '')[:120]}")
            if len(cluster_items) > 5:
                lines.append(f"  ... and {len(cluster_items) - 5} more")

            content = "\n".join(lines)

            # Map memory type → brain fragment type
            ftype = self._mem_type_to_fragment_type(mem_type)
            if ftype is None:
                continue

            # Check if fragment already has similar content (avoid duplicates)
            existing = await self._store.get_latest(teammate_id, ftype.value)
            if existing:
                existing_kw = _extract_keywords(existing.content)
                new_kw = _extract_keywords(content)
                if _keyword_overlap(existing_kw, new_kw) > 0.6:
                    # Too similar to existing — skip
                    continue

            fragment = BrainFragment(
                teammate_id=teammate_id,
                fragment_type=ftype,
                content=content,
                confidence=0.5,  # lower confidence for auto-consolidated
                source="consolidation",
            )
            await self._store.store(fragment)
            created += 1

        return created

    @staticmethod
    def _mem_type_to_fragment_type(mem_type: str) -> Optional[BrainFragmentType]:
        """Map MemoryType to the most relevant BrainFragmentType."""
        mapping = {
            MemoryType.EXECUTION: BrainFragmentType.LESSONS,
            MemoryType.DECISION: BrainFragmentType.DECISIONS,
            MemoryType.TASK: BrainFragmentType.SKILLS,
            MemoryType.EVENT: BrainFragmentType.LESSONS,
        }
        return mapping.get(mem_type)


# Singleton
_svc: Optional[MemoryConsolidationService] = None


def get_consolidation_service() -> MemoryConsolidationService:
    global _svc
    if _svc is None:
        _svc = MemoryConsolidationService()
    return _svc
