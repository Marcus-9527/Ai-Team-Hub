"""\
test_channel_cache_workspace_scope.py — Workspace-scoped channel cache
isolation tests.

Verifies:
 1. Channel cache LIST_KEY is scoped by workspace_id
 2. Two workspaces' channel lists are cached under different keys
 3. A → B sequential requests (within cache TTL) don't cross-contaminate

Pattern: create two workspaces with channels, verify isolation.
"""
import uuid
import pytest
from unittest.mock import MagicMock
from fastapi import Request

from backend.cache import channel_cache
from backend.routes.channels import _list_key, list_channels, _serialize_channel
from backend.models import Channel

WS_A = "test-ws-a-channel-cache"
WS_B = "test-ws-b-channel-cache"


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

    assert key_a == f"channels:{WS_A}", f"unexpected key: {key_a}"
    assert key_b == f"channels:{WS_B}", f"unexpected key: {key_b}"
    assert key_none == "channels:global"
    assert key_a != key_b, "workspace keys must be different"
    assert key_a != key_none


def test_list_key_same_workspace_same_key():
    """Same workspace always produces the same cache key."""
    assert _list_key(WS_A) == _list_key(WS_A)
    assert _list_key(WS_B) == _list_key(WS_B)


# ════════════════════════════════════════════════════════════════
# 2. Channel cache integration
# ════════════════════════════════════════════════════════════════


async def _create_test_channel(db_session, ws: str, name: str):
    ch = Channel(
        name=name,
        description="",
        workspace_id=ws,
    )
    db_session.add(ch)
    await db_session.flush()
    return ch


@pytest.mark.asyncio
async def test_list_channels_cache_isolation_two_workspaces(db_session):
    """
    Two workspaces each have their own channels.
    Workspace A's list_channels returns only A's channels.
    Workspace B's list_channels returns only B's channels.
    Cache stores them under different keys.
    """
    # Create 2 channels in WS_A, 1 in WS_B
    a1 = await _create_test_channel(db_session, WS_A, "channel-a1")
    a2 = await _create_test_channel(db_session, WS_A, "channel-a2")
    b1 = await _create_test_channel(db_session, WS_B, "channel-b1")
    await db_session.commit()

    channel_cache.clear()  # fresh state

    # WS_A list → should see 2 channels
    req_a = _mock_request(WS_A)
    result_a = await list_channels(req_a, db_session)
    assert isinstance(result_a, list)
    assert len(result_a) == 2, f"WS_A expected 2, got {len(result_a)}"
    ids_a = {ch["id"] for ch in result_a}
    assert a1.id in ids_a, "a1 not in WS_A list"
    assert a2.id in ids_a, "a2 not in WS_A list"
    assert b1.id not in ids_a, "b1 leaked into WS_A list — no isolation!"

    # WS_B list → should see 1 channel
    req_b = _mock_request(WS_B)
    result_b = await list_channels(req_b, db_session)
    assert isinstance(result_b, list)
    assert len(result_b) == 1, f"WS_B expected 1, got {len(result_b)}"
    ids_b = {ch["id"] for ch in result_b}
    assert b1.id in ids_b, "b1 not in WS_B list"
    assert a1.id not in ids_b, "a1 leaked into WS_B list — no isolation!"

    # Cache stores them under different keys
    cache_key_a = _list_key(WS_A)
    cache_key_b = _list_key(WS_B)
    assert cache_key_a != cache_key_b, "cache keys must differ per workspace"

    cached_a = channel_cache.get(cache_key_a)
    cached_b = channel_cache.get(cache_key_b)
    assert cached_a is not None, f"cache miss for {cache_key_a}"
    assert cached_b is not None, f"cache miss for {cache_key_b}"
    assert len(cached_a) == 2
    assert len(cached_b) == 1

    # Verify the cached values are isolated (no overlap)
    cached_ids_a = {ch["id"] for ch in cached_a}
    cached_ids_b = {ch["id"] for ch in cached_b}
    assert cached_ids_a.isdisjoint(cached_ids_b), "cache entries overlap between workspaces!"


@pytest.mark.asyncio
async def test_cache_does_not_cross_contaminate_within_ttl(db_session):
    """
    CRITICAL: A requests first (cache miss → populates cache under key_a).
    B requests immediately after (within cache TTL) → must NOT hit A's cached data.
    This catches the bug where LIST_KEY='all' causes A+B to share the same cache entry.
    """
    channel_cache.clear()

    # Create one channel per workspace
    a = await _create_test_channel(db_session, WS_A, "only-a")
    b = await _create_test_channel(db_session, WS_B, "only-b")
    await db_session.commit()

    # Step 1: WS_A requests → cache miss, populates channels:{WS_A}
    req_a = _mock_request(WS_A)
    result_a = await list_channels(req_a, db_session)
    assert len(result_a) == 1
    assert result_a[0]["id"] == a.id

    # Step 2: WS_B requests → should NOT reuse WS_A's cached data
    # If cache key were "all", this would return WS_A's list (only-a, not only-b).
    req_b = _mock_request(WS_B)
    result_b = await list_channels(req_b, db_session)
    assert len(result_b) == 1, \
        f"WS_B expected 1 channel, got {len(result_b)} — likely cross-contamination!"
    assert result_b[0]["id"] == b.id, "WS_B got WS_A's channel — cache not isolated!"

    # Step 3: Verify the cache actually holds separate entries
    assert channel_cache.get(_list_key(WS_A)) is not None
    assert channel_cache.get(_list_key(WS_B)) is not None
    assert channel_cache.get(_list_key(WS_A)) != channel_cache.get(_list_key(WS_B))
