"""test_semantic_memory.py — Phase 18: Semantic Memory Tests

Covers:
  1. Semantic recall returns relevant items (similar content)
  2. Unrelated items not returned (low similarity filtered out)
  3. Scope isolation (metadata_filters prevent cross-scope leakage)
  4. BrainLoader.build_prompt with query uses semantic recall
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import MemoryService
from backend.services.brain.brain_loader import BrainLoader

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────

def _make_memory(content: str, teammate_id: str = "tm_a", scope: str = "private",
                 **kwargs) -> MemoryItem:
    """Create a MemoryItem with embedding pre-computed for testing."""
    emb = MemoryService.compute_embedding(content)
    return MemoryItem(
        content=content,
        embedding=emb,
        source_id=teammate_id,
        metadata={"teammate_id": teammate_id, "scope": scope, **kwargs},
        memory_type=kwargs.pop("memory_type", MemoryType.EXECUTION),
        relevance_score=kwargs.pop("relevance_score", 0.8),
    )


# ═════════════════════════════════════════════════════════════════
# 1. Relevant memory recall
# ═════════════════════════════════════════════════════════════════


async def test_semantic_recall_returns_relevant_items():
    """semantic_recall returns memories with similar content to the query."""
    items = [
        _make_memory("deploy application to production server", "tm_a"),
        _make_memory("database schema migration for user table", "tm_a"),
        _make_memory("weather is nice today in the park", "tm_a"),
    ]
    svc = AsyncMock(spec=MemoryService)
    svc.compute_embedding = MemoryService.compute_embedding
    svc.semantic_search = AsyncMock(return_value=[items[0], items[1]])

    loader = BrainLoader(memory_service=svc)
    result = await loader.semantic_recall(
        "deploy the app to server",
        teammate_id="tm_a",
        top_k=5,
    )

    assert "deploy" in result
    assert "schema" in result or "migration" in result


# ═════════════════════════════════════════════════════════════════
# 2. Unrelated items not recalled
# ═════════════════════════════════════════════════════════════════


async def test_unrelated_items_not_recalled():
    """semantic_recall returns empty for totally unrelated query."""
    svc = AsyncMock(spec=MemoryService)
    svc.compute_embedding = MemoryService.compute_embedding
    svc.semantic_search = AsyncMock(return_value=[])

    loader = BrainLoader(memory_service=svc)
    result = await loader.semantic_recall(
        "quantum physics theory of relativity",
        teammate_id="tm_a",
        top_k=5,
    )
    assert result == ""


async def test_semantic_search_metadata_filters_excludes_low_similarity():
    """metadata_filters passed through to semantic_search correctly."""
    svc = AsyncMock(spec=MemoryService)
    svc.compute_embedding = MemoryService.compute_embedding
    svc.semantic_search = AsyncMock(return_value=[])

    loader = BrainLoader(memory_service=svc)
    _ = await loader.semantic_recall(
        "unrelated query here",
        teammate_id="tm_a",
        scope="private",
        min_score=0.5,
    )
    # Verify the call included the right metadata_filters
    args, kwargs = svc.semantic_search.await_args
    assert kwargs.get("metadata_filters") == {
        "teammate_id": "tm_a",
        "scope": "private",
    }
    assert kwargs.get("min_score") == 0.5


# ═════════════════════════════════════════════════════════════════
# 3. Scope isolation
# ═════════════════════════════════════════════════════════════════


async def test_scope_isolation_tm_a_not_leaked_to_tm_b():
    """semantic_recall for teammate A does not return teammate B's memories."""
    items_a = [
        _make_memory("deploy application to server", "tm_a", "private"),
    ]
    items_b = [
        _make_memory("deploy application to server", "tm_b", "private"),
    ]

    svc_a = AsyncMock(spec=MemoryService)
    svc_a.compute_embedding = MemoryService.compute_embedding
    svc_a.semantic_search = AsyncMock(return_value=items_a)

    svc_b = AsyncMock(spec=MemoryService)
    svc_b.compute_embedding = MemoryService.compute_embedding
    svc_b.semantic_search = AsyncMock(return_value=items_b)

    loader_a = BrainLoader(memory_service=svc_a)
    loader_b = BrainLoader(memory_service=svc_b)

    result_a = await loader_a.semantic_recall(
        "deploy server", teammate_id="tm_a",
    )
    result_b = await loader_b.semantic_recall(
        "deploy server", teammate_id="tm_b",
    )

    assert "deploy" in result_a
    assert "deploy" in result_b

    # Verify each call was made with the correct teammate_id filter
    args_a, kwargs_a = svc_a.semantic_search.await_args
    assert kwargs_a["metadata_filters"]["teammate_id"] == "tm_a"

    args_b, kwargs_b = svc_b.semantic_search.await_args
    assert kwargs_b["metadata_filters"]["teammate_id"] == "tm_b"


async def test_scope_private_does_not_include_workspace():
    """Items with scope='workspace' excluded when scope='private' requested."""
    svc = AsyncMock(spec=MemoryService)
    svc.compute_embedding = MemoryService.compute_embedding
    # Simulate only workspace-scoped items existing
    svc.semantic_search = AsyncMock(return_value=[])

    loader = BrainLoader(memory_service=svc)
    result = await loader.semantic_recall(
        "deploy server",
        teammate_id="tm_a",
        scope="private",
    )
    # If semantic_search returned empty (no private items), result should be empty
    # Verify the scope filter was passed correctly
    _, kwargs = svc.semantic_search.await_args
    assert kwargs["metadata_filters"] == {"teammate_id": "tm_a", "scope": "private"}
    assert result == ""


# ═════════════════════════════════════════════════════════════════
# 4. BrainLoader.build_prompt with query uses semantic recall
# ═════════════════════════════════════════════════════════════════


async def test_build_prompt_semantic_recall_integration():
    """build_prompt with query= uses semantic_recall instead of keyword query."""
    from backend.services.brain.fragment_store import BrainFragment, BrainFragmentType

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.IDENTITY,
            content="I am a test teammate",
            source="manual",
        ),
    ]

    svc = AsyncMock(spec=MemoryService)
    svc.compute_embedding = MemoryService.compute_embedding
    svc.semantic_search = AsyncMock(
        return_value=[
            _make_memory("found from semantic recall", "tm_a"),
        ]
    )
    # query_teammate_memory should NOT be called when query is provided
    svc.query_teammate_memory = AsyncMock(return_value=[])

    loader = BrainLoader(fragment_store=mock_store, memory_service=svc)
    prompt = await loader.build_prompt("tm_a", query="test query", recent_memory_limit=5)

    assert "found from semantic recall" in prompt
    assert "## RELEVANT MEMORY" in prompt
    # query_teammate_memory should not have been called
    svc.query_teammate_memory.assert_not_called()


async def test_build_prompt_without_query_uses_keyword_fallback():
    """build_prompt without query= falls back to keyword-based recall."""
    from backend.services.brain.fragment_store import BrainFragment, BrainFragmentType

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.IDENTITY,
            content="I am a test teammate",
            source="manual",
        ),
    ]

    svc = AsyncMock(spec=MemoryService)
    svc.compute_embedding = MemoryService.compute_embedding
    svc.semantic_search = AsyncMock(return_value=[])
    svc.query_teammate_memory = AsyncMock(return_value=[])

    loader = BrainLoader(fragment_store=mock_store, memory_service=svc)
    prompt = await loader.build_prompt("tm_a", recent_memory_limit=5)

    # semantic_search should not have been called without query=
    svc.semantic_search.assert_not_called()
    svc.query_teammate_memory.assert_called_once()
    assert "## RECENT EXPERIENCE" not in prompt  # empty memory
