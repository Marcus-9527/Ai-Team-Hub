"""
memory_context.py — Phase 4: Three-tier Memory Context Builder.

Maps the three memory scopes (Short-term, Project, Semantic) onto existing
MemoryType values and provides a single entry point for Chat and Task consumers.

Scope → MemoryType mapping:
  Short-term (current conversation context)
      → CHANNEL, EXECUTION (recent, time-bound)
  Project    (structured project facts)
      → WORKSPACE, TASK, DECISION, GLOBAL
  Semantic   (vector/embedding retrieval)
      → RAG via EmbeddingService (files, chunks)

Usage (Chat):
    ctx = await MemoryContext.build_chat_context(channel_id, user_message)
    # ctx.text → compressed memory block for prompt injection
    await MemoryContext.store_turn(channel_id, user_message, response_text)

Usage (Task — existing via PlannerContext):
    # task_planner_context.py already uses MemoryRetriever + MemoryCompressor
    # This module provides a matching interface for Chat.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_retriever import MemoryRetriever, RetrievalQuery
from backend.services.memory.memory_compressor import MemoryCompressor, CompressedContext

logger = logging.getLogger("memory.context")

# ── Scope → MemoryType mapping ──

SHORT_TERM_TYPES = [MemoryType.CHANNEL, MemoryType.EXECUTION]
PROJECT_TYPES = [MemoryType.TEAMMATE, MemoryType.WORKSPACE, MemoryType.TASK, MemoryType.DECISION, MemoryType.GLOBAL]


class MemoryContext:
    """Stateless helper: build compressed memory context + store conversation turns.

    Every method is async and uses the singleton MemoryService/MemoryRetriever.
    """

    def __init__(
        self,
        retriever: Optional[MemoryRetriever] = None,
        compressor: Optional[MemoryCompressor] = None,
    ):
        self._retriever = retriever or MemoryRetriever()
        self._compressor = compressor or MemoryCompressor()

    # ── Build context for chat ────────────────────────────────────

    async def build_chat_context(
        self,
        channel_id: str,
        user_message: str,
        top_k: int = 10,
        max_hours: float = 24.0,
    ) -> CompressedContext:
        """Retrieve + compress Short-term + Project memory for a chat turn.

        Also runs semantic search when user_message contains meaningful content.
        Returns a CompressedContext ready for prompt injection.
        Returns empty context when no relevant memory exists (graceful fallback).
        """
        # Short-term: recent conversation in this channel
        short_term = await self._retriever.retrieve(
            RetrievalQuery(
                source_id=channel_id,
                memory_types=[t.value for t in SHORT_TERM_TYPES],
                top_k=top_k // 2,
                max_hours=max_hours,
            )
        )

        # Project: task/decision history scoped to this channel
        project = await self._retriever.retrieve(
            RetrievalQuery(
                source_id=channel_id,
                memory_types=[t.value for t in PROJECT_TYPES],
                top_k=top_k // 2,
                max_hours=max_hours * 7,  # project memory spans longer
            )
        )

        all_items = short_term.items + project.items
        # ponytail: naive concat + re-sort; a fusion ranker if perf matters
        all_items.sort(key=lambda r: r.score, reverse=True)

        ctx = self._compressor.compress(all_items, max_chars=2000)

        # ── Phase 13: Inject semantic search results ──
        if user_message and len(user_message) > 10:
            semantic_text = await self.retrieve_relevant_memory(
                user_message, channel_id=channel_id, top_k=5,
            )
            if semantic_text:
                if ctx.text:
                    ctx.text += "\n\n[RELEVANT MEMORY]\n" + semantic_text
                else:
                    ctx.text = "[RELEVANT MEMORY]\n" + semantic_text
                ctx.items_used += 1
                ctx.chars_after = len(ctx.text)

        return ctx

    async def build_semantic_context(
        self,
        query: str,
        top_k: int = 5,
        channel_id: Optional[str] = None,
    ) -> str:
        """Retrieve relevant file-chunk context via RAG pipeline.

        Returns a plain-text block of relevant chunks or empty string.
        Uses EmbeddingService under the hood (no vector DB dependency).
        """
        try:
            from backend.services.embedding_service import get_embedding_service, embed_text

            svc = get_embedding_service()
            q_vec = embed_text(query)

            # Load chunks scoped to channel if possible, else global
            from backend.database import async_session
            from backend.services.embedding_service import load_all_chunks_for_user

            async with async_session() as db:
                user_id = channel_id or ""
                chunks = await load_all_chunks_for_user(user_id, db)

            if not chunks:
                return ""

            results = svc.search(q_vec, chunks, top_k=top_k)
            if not results:
                return ""

            lines = ["[Semantic Memory — relevant file context]"]
            for r in results:
                lines.append(f"  - {r['content'][:300]}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Semantic context unavailable: {e}")
            return ""

    # ── Store conversation turn ───────────────────────────────────

    async def semantic_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        source_id: Optional[str] = None,
    ) -> list[MemoryItem]:
        """Vector-similarity search across stored memory items.

        Embeds the query text, searches via MemoryService.semantic_search(),
        optionally scopes to a source_id. Returns up to top_k items.
        """
        svc = get_memory_service()
        q_vec = svc.compute_embedding(query)
        results = await svc.semantic_search(q_vec, top_k=top_k * 2)
        if source_id:
            results = [r for r in results if r.source_id == source_id]
        return results[:top_k]

    async def retrieve_relevant_memory(
        self,
        query: str,
        *,
        channel_id: Optional[str] = None,
        top_k: int = 10,
    ) -> str:
        """Combined semantic + keyword retrieval for prompt injection.

        1. Try semantic search first (needs stored embeddings).
        2. Fall back to keyword-based MemoryRetriever.
        3. Compress into a compact string, or empty string if nothing relevant.

        Returns plain text for direct injection into LLM prompts.
        """
        svc = get_memory_service()
        q_vec = svc.compute_embedding(query)
        semantic = await svc.semantic_search(q_vec, top_k=top_k)

        if not semantic:
            # Fallback: keyword retrieval
            retriever = MemoryRetriever()
            result = await retriever.retrieve(
                RetrievalQuery(
                    source_id=channel_id,
                    keywords=[w for w in query.split() if len(w) > 2] or None,
                    top_k=top_k,
                )
            )
            items = [r.item for r in result.items]
        else:
            items = semantic

        if not items:
            return ""

        compressor = MemoryCompressor(max_chars=1200)
        from backend.services.memory.memory_retriever import RankedItem

        ranked = [RankedItem(item=i, score=1.0) for i in items]
        compressed = compressor.compress(ranked)
        return compressed.text

    async def store_turn(
        self,
        channel_id: str,
        user_message: str,
        response_summary: str,
        teammate_id: str = "",
        memory_type: str = None,
    ) -> None:
        """Persist a chat turn as memory.

        Defaults to CHANNEL-type; pass TEAMMATE to store per-teammate memory
        (e.g. style preferences, corrections, learned behavior).
        """
        svc = get_memory_service()
        content = f"User: {user_message}\nResponse: {response_summary}"[:2000]
        item = MemoryItem(
            memory_type=memory_type or MemoryType.CHANNEL,
            content=content,
            source_id=channel_id,
            relevance_score=0.7,
            metadata={
                "teammate_id": teammate_id,
                "type": "chat_turn",
                "memory_type": memory_type or "channel",
            },
        )
        await svc.store(item)
        logger.debug(f"Stored {item.memory_type} memory for channel {channel_id[:12]}")

    async def store_teammate_memory(
        self,
        teammate_id: str,
        summary: str,
        channel_id: str = "",
    ) -> None:
        """Persist a teammate-level memory (preferences, style, learned patterns)."""
        svc = get_memory_service()
        item = MemoryItem(
            memory_type=MemoryType.TEAMMATE,
            content=summary[:2000],
            source_id=teammate_id,
            relevance_score=0.8,
            metadata={"type": "teammate_learned", "channel_id": channel_id},
        )
        await svc.store(item)
        logger.debug(f"Stored TEAMMATE memory for {teammate_id[:12]}")


# ── Singleton shortcut (lazy init, no global state) ──

_context_instance: Optional[MemoryContext] = None


def get_memory_context() -> MemoryContext:
    global _context_instance
    if _context_instance is None:
        _context_instance = MemoryContext()
    return _context_instance
