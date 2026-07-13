"""brain/brain_loader.py — BrainLoader (Phase 12.2)

统一 AI 上下文入口：从 brain fragments + memory items 构建完整的 LLM prompt。
用于 chat/task/engineer/reviewer/techlead 全链路。

调用链：
  TeammateRuntimeContext → BrainLoader → build_prompt() → LLM

Ponytail: 核心就是 build_prompt() 一个函数+一个缓存层。
不需要多态 loader 工厂。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services.brain.fragment_store import (
    BrainFragmentStore,
    get_brain_fragment_store,
    BrainFragmentType,
)
from backend.services.memory.memory_service import get_memory_service, MemoryService

logger = logging.getLogger("brain.loader")

# ── Fragment type → section header mapping ──
_FRAGMENT_HEADERS = {
    BrainFragmentType.IDENTITY: "## IDENTITY",
    BrainFragmentType.PERSONALITY: "## PERSONALITY",
    BrainFragmentType.PRINCIPLES: "## PRINCIPLES",
    BrainFragmentType.RESPONSIBILITIES: "## RESPONSIBILITIES",
    BrainFragmentType.SKILLS: "## SKILLS & ABILITIES",
    BrainFragmentType.LESSONS: "## LESSONS LEARNED",
    BrainFragmentType.DECISIONS: "## PAST DECISIONS",
    BrainFragmentType.PREFERENCES: "## PREFERENCES",
}
_RELEVANT_TYPES = list(_FRAGMENT_HEADERS.keys())


class BrainLoader:
    """Build unified AI context from brain fragments + memory.

    Entry point for all prompt construction across the system.
    """

    def __init__(
        self,
        fragment_store: Optional[BrainFragmentStore] = None,
        memory_service: Optional[MemoryService] = None,
    ):
        self._store = fragment_store or get_brain_fragment_store()
        self._mem_svc = memory_service or get_memory_service()

    async def build_prompt(
        self,
        teammate_id: str,
        *,
        recent_memory_limit: int = 10,
        extra_context: str = "",
        query: Optional[str] = None,
    ) -> str:
        """Build the full system prompt for a teammate.

        When a query string is provided, uses semantic recall (embedding
        similarity) instead of keyword-based memory retrieval. The query
        is typically the user's message or task description.

        Returns a string that should be PREPENDED to the teammate's
        existing system_prompt. Can also be used standalone.

        Sections (when present):
          1. IDENTITY
          2. PERSONALITY
          3. PRINCIPLES
          4. RESPONSIBILITIES
          5. SKILLS & ABILITIES
          6. LESSONS LEARNED
          7. PAST DECISIONS
          8. PREFERENCES
          9. RECENT MEMORY / RELEVANT MEMORY (semantic when query provided)
        """
        fragments = await self._store.get_all_by_teammate(teammate_id)
        if not fragments:
            return extra_context

        sections: list[str] = [
            "## YOUR BRAIN — This is your persistent self-knowledge.",
            "These are facts about yourself built from past experience.",
        ]

        # Build a lookup for quick section building
        frag_map: dict[str, str] = {}
        for f in fragments:
            frag_map[f.fragment_type] = f.content

        # Non-empty sections ordered by type priority
        for ftype in _RELEVANT_TYPES:
            content = frag_map.get(ftype.value)
            if not content:
                continue
            header = _FRAGMENT_HEADERS[ftype]
            sections.append(f"\n{header}\n{content}")

        # Memory context — semantic when query provided, keyword otherwise
        if recent_memory_limit > 0:
            if query:
                mem_text = await self.semantic_recall(
                    query,
                    teammate_id=teammate_id,
                    top_k=recent_memory_limit,
                )
                if mem_text:
                    sections.append(f"\n## RELEVANT MEMORY\n{mem_text}")
            else:
                mem_items = await self._mem_svc.query_teammate_memory(
                    teammate_id, limit=recent_memory_limit,
                )
                if mem_items:
                    mem_lines = ["\n## RECENT EXPERIENCE"]
                    for m in mem_items:
                        preview = (m.content or "")[:200].replace("\n", " ")
                        mem_lines.append(f"  - {preview}")
                    sections.append("\n".join(mem_lines))

        prompt = "\n".join(sections)
        if extra_context:
            prompt += f"\n\n{extra_context}"

        return prompt

    async def semantic_recall(
        self,
        query: str,
        *,
        teammate_id: str,
        scope: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.1,
    ) -> str:
        """Semantic recall: embed query → scoped similarity search → formatted text.

        Returns a plain-text block of relevant memories for prompt injection,
        or empty string when nothing matches.

        Scope isolation is enforced via metadata_filters on memory_items:
          - teammate_id (always)
          - scope      (optional: "private" | "workspace" | "channel" | "review")
        """
        if not query or not query.strip():
            return ""

        query_vector = self._mem_svc.compute_embedding(query)
        filters: dict = {"teammate_id": teammate_id}
        if scope:
            filters["scope"] = scope

        items = await self._mem_svc.semantic_search(
            query_vector,
            top_k=top_k,
            min_score=min_score,
            metadata_filters=filters,
        )
        if not items:
            return ""

        lines: list[str] = []
        for m in items:
            preview = (m.content or "")[:300].replace("\n", " ")
            score = m.relevance_score
            lines.append(f"  - [{score:.2f}] {preview}")
        return "\n".join(lines)

    async def build_identity_block(self, teammate_id: str) -> str:
        """Shortcut: return only the IDENTITY + PERSONALITY section as one string."""
        fragments = await self._store.get_all_by_teammate(teammate_id)
        parts = []
        for f in fragments:
            if f.fragment_type == BrainFragmentType.IDENTITY:
                parts.append(f"Identity: {f.content}")
            elif f.fragment_type == BrainFragmentType.PERSONALITY:
                parts.append(f"Personality: {f.content}")
            elif f.fragment_type == BrainFragmentType.PRINCIPLES:
                parts.append(f"Principles: {f.content}")
        return "\n".join(parts)


# Singleton
_loader: Optional[BrainLoader] = None


def get_brain_loader() -> BrainLoader:
    global _loader
    if _loader is None:
        _loader = BrainLoader()
    return _loader
