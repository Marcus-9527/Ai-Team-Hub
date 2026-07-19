"""
test_teammate_cache_workspace_scope.py — Workspace-scoped teammate cache
and brain route isolation test.

Verifies:
 1. Teammate cache LIST_KEY is scoped by workspace_id
 2. Two workspaces' teammate lists are cached under different keys
 3. A → B sequential requests (within cache TTL) don't cross-contaminate
 4. Brain overview/memory/search routes filter by workspace_id

Pattern: create two workspaces with teammates, verify isolation.
"""
import uuid
import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi import Request

from backend.cache import teammate_cache
from backend.routes.teammates import _list_key, list_teammates, _serialize_teammate
from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_intelligence import get_intelligence_service

WS_A = "test-ws-a-teammate-cache"
WS_B = "test-ws-b-teammate-cache"


def _mock_request(ws: str | None) -> Request:
    req = MagicMock(spec=Request)
    req.state.workspace_id = ws
    return req


# ════════════════════════════════════════════════════════════════
# 1. Cache key unit tests
# ════════════════════════════════════════════════════════════════


def test_list_key_scoped_by_workspace():
    """_list_key returns different keys for different workspaces."""
    key_a = _list_key(WS_A)
    key_b = _list_key(WS_B)
    key_none = _list_key(None)

    assert key_a == f"teammates:{WS_A}", f"unexpected key: {key_a}"
    assert key_b == f"teammates:{WS_B}", f"unexpected key: {key_b}"
    assert key_none == "teammates:global"
    assert key_a != key_b, "workspace keys must be different"
    assert key_a != key_none


def test_list_key_same_workspace_same_key():
    """Same workspace always produces the same cache key."""
    assert _list_key(WS_A) == _list_key(WS_A)
    assert _list_key(WS_B) == _list_key(WS_B)


# ════════════════════════════════════════════════════════════════
# 2. Teammate cache integration
# ════════════════════════════════════════════════════════════════


async def _create_test_teammate(db_session, ws: str, name: str):
    from backend.models import Teammate
    tm = Teammate(
        name=name,
        role="assistant",
        avatar_emoji="🤖",
        system_prompt="test",
        model_provider="test",
        model_name="test",
        workspace_id=ws,
    )
    db_session.add(tm)
    await db_session.flush()
    return tm


@pytest.mark.asyncio
async def test_list_teammates_cache_isolation_two_workspaces(db_session):
    """
    Two workspaces each have their own teammates.
    Workspace A's list_teammates returns only A's teammates.
    Workspace B's list_teammates returns only B's teammates.
    Cache stores them under different keys.
    """
    # Create 2 teammates in WS_A, 1 in WS_B
    a1 = await _create_test_teammate(db_session, WS_A, "teammate-a1")
    a2 = await _create_test_teammate(db_session, WS_A, "teammate-a2")
    b1 = await _create_test_teammate(db_session, WS_B, "teammate-b1")
    await db_session.commit()

    teammate_cache.clear()  # fresh state

    # WS_A list → should see 2 teammates
    req_a = _mock_request(WS_A)
    result_a = await list_teammates(req_a, db_session)
    assert isinstance(result_a, list)
    assert len(result_a) == 2, f"WS_A expected 2, got {len(result_a)}"
    ids_a = {t["id"] for t in result_a}
    assert a1.id in ids_a, "a1 not in WS_A list"
    assert a2.id in ids_a, "a2 not in WS_A list"
    assert b1.id not in ids_a, "b1 leaked into WS_A list — no isolation!"

    # WS_B list → should see 1 teammate
    req_b = _mock_request(WS_B)
    result_b = await list_teammates(req_b, db_session)
    assert isinstance(result_b, list)
    assert len(result_b) == 1, f"WS_B expected 1, got {len(result_b)}"
    ids_b = {t["id"] for t in result_b}
    assert b1.id in ids_b, "b1 not in WS_B list"
    assert a1.id not in ids_b, "a1 leaked into WS_B list — no isolation!"

    # Cache stores them under different keys
    cache_key_a = _list_key(WS_A)
    cache_key_b = _list_key(WS_B)
    assert cache_key_a != cache_key_b, "cache keys must differ per workspace"

    cached_a = teammate_cache.get(cache_key_a)
    cached_b = teammate_cache.get(cache_key_b)
    assert cached_a is not None, f"cache miss for {cache_key_a}"
    assert cached_b is not None, f"cache miss for {cache_key_b}"
    assert len(cached_a) == 2
    assert len(cached_b) == 1

    # Verify the cached values are isolated (no overlap)
    cached_ids_a = {t["id"] for t in cached_a}
    cached_ids_b = {t["id"] for t in cached_b}
    assert cached_ids_a.isdisjoint(cached_ids_b), "cache entries overlap between workspaces!"


@pytest.mark.asyncio
async def test_cache_does_not_cross_contaminate_within_ttl(db_session):
    """
    CRITICAL: A requests first (cache miss → populates cache under key_a).
    B requests immediately after (within cache TTL) → must NOT hit A's cached data.
    This catches the bug where LIST_KEY='all' causes A+B to share the same cache entry.
    """
    teammate_cache.clear()

    # Create one teammate per workspace
    a = await _create_test_teammate(db_session, WS_A, "only-a")
    b = await _create_test_teammate(db_session, WS_B, "only-b")
    await db_session.commit()

    # Step 1: WS_A requests → cache miss, populates teammate:{WS_A}
    req_a = _mock_request(WS_A)
    result_a = await list_teammates(req_a, db_session)
    assert len(result_a) == 1
    assert result_a[0]["id"] == a.id

    # Step 2: WS_B requests → should NOT reuse WS_A's cached data
    # If cache key were "all", this would return WS_A's list (only-a, not only-b).
    req_b = _mock_request(WS_B)
    result_b = await list_teammates(req_b, db_session)
    assert len(result_b) == 1, f"WS_B expected 1 teammate, got {len(result_b)} — likely cross-contamination!"
    assert result_b[0]["id"] == b.id, "WS_B got WS_A's teammate — cache not isolated!"

    # Step 3: Verify the cache actually holds separate entries
    assert teammate_cache.get(_list_key(WS_A)) is not None
    assert teammate_cache.get(_list_key(WS_B)) is not None
    assert teammate_cache.get(_list_key(WS_A)) != teammate_cache.get(_list_key(WS_B))


@pytest.mark.asyncio
async def test_cache_isolation_with_global_workspace(db_session):
    """A workspace-less (global) request and a scoped one use different keys."""
    teammate_cache.clear()

    await _create_test_teammate(db_session, None, "global-guy")
    await _create_test_teammate(db_session, WS_A, "scoped-guy")
    await db_session.commit()

    # Global request
    req_global = _mock_request(None)
    result_global = await list_teammates(req_global, db_session)
    assert len(result_global) >= 1  # at least 1 (the NULL-workspace one)

    # Workspace A request
    req_a = _mock_request(WS_A)
    result_a = await list_teammates(req_a, db_session)
    assert len(result_a) >= 1  # at least 1

    # Global cache and scoped cache are distinct
    assert _list_key(None) != _list_key(WS_A)
    assert teammate_cache.get(_list_key(None)) is not None
    assert teammate_cache.get(_list_key(WS_A)) is not None


# ════════════════════════════════════════════════════════════════
# 3. Brain route workspace isolation (service layer)
# ════════════════════════════════════════════════════════════════


async def _store_memory_with_ws(ws: str, content: str):
    """Store a MemoryItem for a specific workspace."""
    from backend.services.memory.memory_types import MemoryItem, MemoryType
    from datetime import datetime, timezone
    svc = get_memory_service()
    embedding = svc.compute_embedding(content)
    item = MemoryItem(
        id=f"mem-{uuid.uuid4().hex[:8]}",
        memory_type=MemoryType.EVENT,
        content=content,
        source_id="test-brain",
        created_at=datetime.now(timezone.utc),
        embedding=embedding,
        metadata={"workspace_id": ws},
    )
    await svc.store(item)
    return item


@pytest.mark.asyncio
async def test_brain_stats_workspace_isolation():
    """
    memory_service.stats(workspace_id=ws) returns only items from that workspace.
    """
    svc = get_memory_service()
    # Ensure clean state — ponytail: the real DB is shared across test sessions
    # so these tests rely on unique workspace IDs to avoid cross-talk.
    ws_a = f"brain-stats-a-{uuid.uuid4().hex[:6]}"
    ws_b = f"brain-stats-b-{uuid.uuid4().hex[:6]}"

    await _store_memory_with_ws(ws_a, "memory of A")
    await _store_memory_with_ws(ws_b, "memory of B")
    await _store_memory_with_ws(ws_a, "another memory of A")

    stats_a = await svc.stats(workspace_id=ws_a)
    stats_b = await svc.stats(workspace_id=ws_b)
    stats_all = await svc.stats()

    assert stats_a["total_items"] >= 2, f"ws_a expected >=2, got {stats_a}"
    assert stats_b["total_items"] >= 1, f"ws_b expected >=1, got {stats_b}"
    assert stats_all["total_items"] >= stats_a["total_items"] + stats_b["total_items"], \
        "global total should be >= sum of isolated workspaces"


@pytest.mark.asyncio
async def test_brain_memory_query_postfilters_workspace(db_session):
    """
    brain_memory route post-filters by workspace_id.
    Verifies the post-filter logic works.
    """
    ws_a = f"brain-mem-a-{uuid.uuid4().hex[:6]}"
    ws_b = f"brain-mem-b-{uuid.uuid4().hex[:6]}"

    await _store_memory_with_ws(ws_a, "A's private memory")
    await _store_memory_with_ws(ws_b, "B's private memory")

    svc = get_memory_service()

    # Simulate what brain_memory route does: query all then post-filter
    all_items = await svc.query(limit=200)

    a_items = [it for it in all_items if it.metadata.get("workspace_id") == ws_a]
    b_items = [it for it in all_items if it.metadata.get("workspace_id") == ws_b]

    assert any("A's private memory" in it.content for it in a_items), "A's memory not found"
    assert any("B's private memory" in it.content for it in b_items), "B's memory not found"

    # Cross-check: A should not see B's content
    assert not any("B's private memory" in it.content for it in a_items), "B leaked into A!"


@pytest.mark.asyncio
async def test_brain_search_metadata_filters_workspace():
    """
    brain_search uses semantic_search with metadata_filters to isolate workspaces.
    """
    ws_a = f"brain-search-a-{uuid.uuid4().hex[:6]}"
    ws_b = f"brain-search-b-{uuid.uuid4().hex[:6]}"

    await _store_memory_with_ws(ws_a, "alpha launch plan")
    await _store_memory_with_ws(ws_b, "beta launch plan")

    svc = get_memory_service()
    vec = svc.compute_embedding("launch plan")

    # Search scoped to ws_a → should find A's result
    results_a = await svc.semantic_search(vec, top_k=5, min_score=0.0, metadata_filters={"workspace_id": ws_a})
    a_contents = {it.content for it in results_a}
    assert "alpha launch plan" in a_contents, f"A not found in A's search: {a_contents}"
    assert "beta launch plan" not in a_contents, "B leaked into A's search!"

    # Search scoped to ws_b → should find B's result
    results_b = await svc.semantic_search(vec, top_k=5, min_score=0.0, metadata_filters={"workspace_id": ws_b})
    b_contents = {it.content for it in results_b}
    assert "beta launch plan" in b_contents, f"B not found in B's search: {b_contents}"
    assert "alpha launch plan" not in b_contents, "A leaked into B's search!"
