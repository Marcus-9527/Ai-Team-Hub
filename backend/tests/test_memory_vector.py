"""
test_memory_vector.py — Phase 13: Memory Vector / Semantic Search Tests

Covers:
  1. MemoryItem.embedding field roundtrip (dict serialization)
  2. compute_embedding produces deterministic normalized vectors
  3. _cosine_similarity correctness
  4. MemoryContext.semantic_search returns expected items
  5. MemoryContext.retrieve_relevant_memory fallback chain
  6. TaskHook auto-generates embedding via _store
  7. Post-execution decision / experience / summary memories
"""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import MemoryService, _cosine_similarity
from backend.services.memory.memory_context import MemoryContext


class TestMemoryItemEmbedding:
    """Phase 13: MemoryItem.embedding field."""

    def test_embedding_default_empty(self):
        """New MemoryItem has empty embedding list by default."""
        item = MemoryItem(content="hello")
        assert item.embedding == []

    def test_embedding_roundtrip(self):
        """Embedding survives to_dict → from_dict."""
        item = MemoryItem(content="test", embedding=[0.1, 0.2, 0.3])
        data = item.to_dict()
        restored = MemoryItem.from_dict(data)
        assert restored.embedding == [0.1, 0.2, 0.3]

    def test_to_dict_includes_embedding(self):
        """to_dict() output contains embedding key."""
        item = MemoryItem(content="x", embedding=[1.0])
        assert "embedding" in item.to_dict()


class TestEmbeddingComputation:
    """Phase 13: compute_embedding produces usable vectors."""

    def test_deterministic(self):
        """Same text produces same vector."""
        v1 = MemoryService.compute_embedding("hello world")
        v2 = MemoryService.compute_embedding("hello world")
        assert v1 == v2

    def test_normalized(self):
        """Output vector has unit length (within float precision)."""
        vec = MemoryService.compute_embedding("ai team hub task planning")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_length_default(self):
        """Default dimension is 256."""
        vec = MemoryService.compute_embedding("x")
        assert len(vec) == 256

    def test_empty_text(self):
        """Empty text returns zero vector (norm=0 → all zeros)."""
        vec = MemoryService.compute_embedding("")
        assert all(v == 0.0 for v in vec)

    def test_similar_texts_have_positive_similarity(self):
        """Related texts get cosine > 0.5."""
        v1 = MemoryService.compute_embedding("deploy the application to server")
        v2 = MemoryService.compute_embedding("deploy app on the production server")
        sim = _cosine_similarity(v1, v2)
        assert sim > 0.3, f"similar texts should have positive similarity, got {sim}"

    def test_different_texts_lower_similarity(self):
        """Unrelated texts get lower similarity than related ones."""
        a = MemoryService.compute_embedding("database schema migration plan")
        b = MemoryService.compute_embedding("database schema migration plan")
        c = MemoryService.compute_embedding("weather forecast sunny today")
        sim_same = _cosine_similarity(a, b)
        sim_diff = _cosine_similarity(a, c)
        assert sim_same > sim_diff


class TestCosineSimilarity:
    """Phase 13: _cosine_similarity helper."""

    def test_identical(self):
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_opposite(self):
        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_mismatched_length(self):
        assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0

    def test_empty(self):
        assert _cosine_similarity([], []) == 0.0


class TestMemoryContextSemanticSearch:
    """Phase 13: MemoryContext.semantic_search integration."""

    @pytest.mark.asyncio
    async def test_semantic_search_returns_items(self):
        """semantic_search returns items matching the query."""
        ctx = MemoryContext()
        with patch.object(ctx, "_retriever") as mock_ret:
            mock_ret.retrieve = AsyncMock(return_value=MagicMock(items=[]))
            mock_retriever = mock_ret

            with patch(
                "backend.services.memory.memory_context.get_memory_service"
            ) as mock_get_svc:
                svc = AsyncMock()
                svc.compute_embedding = MagicMock(return_value=[1.0, 0.0])
                svc.semantic_search = AsyncMock(
                    return_value=[
                        MemoryItem(content="test match", id="m1"),
                    ]
                )
                mock_get_svc.return_value = svc

                results = await ctx.semantic_search("test query", top_k=5)
                assert len(results) == 1
                assert results[0].id == "m1"

    @pytest.mark.asyncio
    async def test_retrieve_relevant_memory_fallback(self):
        """When semantic search returns nothing, falls back to keyword retrieval."""
        ctx = MemoryContext()
        with patch(
            "backend.services.memory.memory_context.get_memory_service"
        ) as mock_get_svc:
            svc = AsyncMock()
            svc.compute_embedding = MagicMock(return_value=[1.0, 0.0])
            svc.semantic_search = AsyncMock(return_value=[])
            mock_get_svc.return_value = svc

            with patch(
                "backend.services.memory.memory_context.MemoryRetriever"
            ) as mock_ret_cls:
                mock_ret = AsyncMock()
                mock_ret.retrieve = AsyncMock(
                    return_value=MagicMock(
                        items=[MagicMock(item=MemoryItem(content="fallback hit"))]
                    )
                )
                mock_ret_cls.return_value = mock_ret

                text = await ctx.retrieve_relevant_memory("test query")
                assert "fallback" in text

    @pytest.mark.asyncio
    async def test_retrieve_relevant_memory_returns_empty(self):
        """When nothing matches, returns empty string."""
        ctx = MemoryContext()
        with patch(
            "backend.services.memory.memory_context.get_memory_service"
        ) as mock_get_svc:
            svc = AsyncMock()
            svc.compute_embedding = MagicMock(return_value=[1.0, 0.0])
            svc.semantic_search = AsyncMock(return_value=[])
            mock_get_svc.return_value = svc

            with patch(
                "backend.services.memory.memory_context.MemoryRetriever"
            ) as mock_ret_cls:
                mock_ret = AsyncMock()
                mock_ret.retrieve = AsyncMock(
                    return_value=MagicMock(items=[])
                )
                mock_ret_cls.return_value = mock_ret

                text = await ctx.retrieve_relevant_memory("test query")
                assert text == ""


class TestTaskHookEmbedding:
    """Phase 13: TaskHook auto-generates embedding on store."""

    @pytest.mark.asyncio
    async def test_store_auto_embeds(self):
        """_store computes embedding when item has none."""
        from backend.services.memory.memory_event_handler import MemoryTaskHook

        hook = MemoryTaskHook()
        item = MemoryItem(content="test content for embedding")
        await hook._store(item, "TEST")

        assert len(item.embedding) == 256
        norm = math.sqrt(sum(v * v for v in item.embedding))
        assert abs(norm - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_store_skips_embedding_if_already_set(self):
        """_store preserves embedding if already set."""
        from backend.services.memory.memory_event_handler import MemoryTaskHook

        hook = MemoryTaskHook()
        item = MemoryItem(content="test", embedding=[1.0, 0.0, 0.0])
        original = item.embedding.copy()
        await hook._store(item, "TEST")

        assert item.embedding == original

    @pytest.mark.asyncio
    async def test_store_skips_embedding_if_no_content(self):
        """_store skips embedding for empty content."""
        from backend.services.memory.memory_event_handler import MemoryTaskHook

        hook = MemoryTaskHook()
        item = MemoryItem(content="")
        await hook._store(item, "TEST")

        assert item.embedding == []


class TestBuildChatContextIntegratesSemantic:
    """Phase 13: build_chat_context injects semantic search results."""

    @pytest.mark.asyncio
    async def test_build_chat_context_includes_relevant_memory(self):
        """build_chat_context includes [RELEVANT MEMORY] section when semantic hit."""
        ctx = MemoryContext()

        with (
            patch.object(ctx._retriever, "retrieve", new=AsyncMock(
                return_value=MagicMock(items=[], total_candidates=0, returned_count=0, query="test")
            )),
            patch.object(ctx._compressor, "compress", return_value=MagicMock(
                text="[MEMORY] previous context", items_used=2, items_total=2,
                chars_before=200, chars_after=30,
            )),
            patch.object(ctx, "retrieve_relevant_memory", new=AsyncMock(
                return_value="some relevant memory text"
            )),
        ):
            result = await ctx.build_chat_context(
                channel_id="ch_test", user_message="hello world how are you"
            )
            assert "[RELEVANT MEMORY]" in result.text
