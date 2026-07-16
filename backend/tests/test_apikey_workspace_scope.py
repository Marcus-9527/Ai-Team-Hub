"""
test_apikey_workspace_scope.py — Workspace-scoped API key isolation test.

Ensures _apply_db_key_to_kwargs filters by workspace_id, so workspace A's
automation tasks never silently use workspace B's API key.

Pattern: create two workspaces, each with its own active key, then verify
_resolve_workspace_key returns the correct key for each workspace.
"""

import pytest

pytestmark = [pytest.mark.asyncio]


async def _create_test_key(db_session, workspace_id: str, label: str, key_body: str):
    """Insert a test key into apikeys table (plaintext, not encrypted — for test)."""
    from backend.models import APIKey
    from backend.crypto import encrypt_value
    encrypted = encrypt_value(key_body)
    key = APIKey(
        workspace_id=workspace_id,
        provider="openrouter",
        label=label,
        api_key=encrypted,
        is_active="1",
        base_url=None,
    )
    db_session.add(key)
    await db_session.flush()
    return key.id


async def test_resolve_workspace_key_isolates_scopes():
    """
    Two workspaces each have an active key.
    _resolve_workspace_key(ws_a) returns ws_a's key.
    _resolve_workspace_key(ws_b) returns ws_b's key.
    They are NOT the same key.
    """
    from backend.database import async_session
    from backend.routes.maeos import _resolve_workspace_key

    WS_A = "test-ws-a-000000000001"
    WS_B = "test-ws-b-000000000002"
    KEY_A = "sk-test-workspace-a-real-key-xxxxxxxxxxx"
    KEY_B = "sk-test-workspace-b-real-key-yyyyyyyyyyy"

    async with async_session() as sess:
        await _create_test_key(sess, WS_A, "test-key-a", KEY_A)
        await _create_test_key(sess, WS_B, "test-key-b", KEY_B)
        await sess.commit()

    try:
        result_a = await _resolve_workspace_key(WS_A)
        result_b = await _resolve_workspace_key(WS_B)

        # Both workspaces have their own keys
        assert result_a.get("api_key"), f"ws_a resolves no key: {result_a}"
        assert result_b.get("api_key"), f"ws_b resolves no key: {result_b}"

        # They are different keys
        assert result_a["api_key"] != result_b["api_key"], \
            "Workspace A and B resolved to the same API key — no isolation!"

        # Each matches the expected key
        assert result_a["api_key"] == KEY_A, \
            f"ws_a expected {KEY_A[:12]}... got {result_a['api_key'][:12]}..."
        assert result_b["api_key"] == KEY_B, \
            f"ws_b expected {KEY_B[:12]}... got {result_b['api_key'][:12]}..."

        # Both preserve provider
        assert result_a.get("provider") == "openrouter"
        assert result_b.get("provider") == "openrouter"

        print(f"  ✓ ws_a key: {result_a['api_key'][:12]}...")
        print(f"  ✓ ws_b key: {result_b['api_key'][:12]}...")
        print(f"  ✓ Keys are isolated per workspace")

    finally:
        # Cleanup test keys
        from sqlalchemy import delete
        from backend.models import APIKey
        async with async_session() as sess:
            await sess.execute(
                delete(APIKey).where(APIKey.workspace_id.in_([WS_A, WS_B]))
            )
            await sess.commit()


async def test_apply_db_key_to_kwargs_no_workspace_returns_one_key():
    """
    Without workspace_id, _apply_db_key_to_kwargs returns some active key
    (MAEOS singleton init path — unchanged behavior).
    """
    from backend.routes.maeos import _apply_db_key_to_kwargs
    kwargs = {}
    await _apply_db_key_to_kwargs(kwargs)
    assert kwargs.get("api_key"), "No key resolved without workspace_id"
    # This should return the real key (the only active one after E2E key cleanup)
    print(f"  ✓ Global key resolved: {kwargs['api_key'][:12]}...")
    assert len(kwargs["api_key"]) > 50, "Global fallback key is too short (test key?!)"


async def test_workspace_without_key_raises_error():
    """
    A workspace that has no active key should raise ValueError,
    not silently borrow another workspace's key.
    """
    from backend.routes.maeos import _resolve_workspace_key
    with pytest.raises(ValueError, match="no active API key configured"):
        await _resolve_workspace_key("nonexistent-workspace-id-xxx")
    print("  ✓ No-key workspace raises ValueError, not silent fallback")
