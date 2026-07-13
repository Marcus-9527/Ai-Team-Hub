"""
test_memory_context.py — Phase 4: MemoryContext Unit Tests

Covers:
  1. MemoryContext.create() with default deps
  2. build_chat_context — retrieval + compression pipeline
  3. store_turn — chat turn persistence
  4. build_semantic_context — RAG fallback
  5. Singleton get_memory_context()
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.memory.memory_context import MemoryContext, get_memory_context
from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_retriever import RetrievalResult, RankedItem, RetrievalQuery
from backend.services.memory.memory_compressor import CompressedContext


class TestMemoryContext:
    """Phase 4: MemoryContext — chat memory integration."""

    @pytest.fixture
    def mock_retriever(self):
        """A MemoryRetriever whose retrieve() returns known items."""
        ret = AsyncMock()
        ret.retrieve = AsyncMock(return_value=RetrievalResult(
            items=[],
            total_candidates=0,
            returned_count=0,
            query="test",
        ))
        return ret

    @pytest.fixture
    def mock_compressor(self):
        """A MemoryCompressor that returns a fixed compressed block."""
        comp = MagicMock()
        comp.compress = MagicMock(return_value=CompressedContext(
            text="[MEMORY] Previous discussion: test",
            items_used=2,
            items_total=2,
            chars_before=200,
            chars_after=30,
        ))
        return comp

    def test_create_with_defaults(self):
        """Can instantiate without args; uses singleton services."""
        ctx = MemoryContext()
        assert ctx._retriever is not None
        assert ctx._compressor is not None

    @pytest.mark.asyncio
    async def test_build_chat_context_returns_empty_on_no_memory(self, mock_retriever, mock_compressor):
        """When no memory exists, returns empty CompressedContext."""
        ctx = MemoryContext(retriever=mock_retriever, compressor=mock_compressor)
        result = await ctx.build_chat_context(channel_id="ch_test", user_message="hello")
        assert isinstance(result, CompressedContext)

    @pytest.mark.asyncio
    async def test_build_chat_context_calls_retrieve_twice(self):
        """Verifies two retrievals (short-term + project) are made."""
        retriever = AsyncMock()
        retriever.retrieve = AsyncMock(return_value=RetrievalResult(
            items=[], total_candidates=0, returned_count=0, query="test",
        ))
        compressor = MagicMock()
        compressor.compress = MagicMock(return_value=CompressedContext(
            text="[MEMORY] test", items_used=0, items_total=0, chars_before=0, chars_after=0,
        ))

        ctx = MemoryContext(retriever=retriever, compressor=compressor)
        await ctx.build_chat_context(channel_id="ch_1", user_message="hi")

        assert retriever.retrieve.call_count == 2

    @pytest.mark.asyncio
    async def test_store_turn_persists_memory_item(self):
        """store_turn should store a CHANNEL-type MemoryItem."""
        mock_svc = AsyncMock()
        mock_svc.store = AsyncMock(return_value="mem_1")

        with patch("backend.services.memory.memory_context.get_memory_service", return_value=mock_svc):
            ctx = MemoryContext()
            await ctx.store_turn(
                channel_id="ch_test",
                user_message="hi",
                response_summary="hello back",
            )

        mock_svc.store.assert_called_once()
        item = mock_svc.store.call_args[0][0]
        assert item.memory_type == MemoryType.CHANNEL
        assert item.source_id == "ch_test"

    @pytest.mark.asyncio
    async def test_build_semantic_context_returns_empty_on_no_chunks(self):
        """build_semantic_context returns empty string when no chunks exist."""
        ctx = MemoryContext()
        result = await ctx.build_semantic_context(query="test query")
        assert result == ""

    def test_singleton_get_memory_context(self):
        """get_memory_context returns same instance on repeated call."""
        a = get_memory_context()
        b = get_memory_context()
        assert a is b
