"""
test_apikey_workspace_scope.py — Workspace-scoped API key isolation test.

Ensures resolve_workspace_api_key filters by workspace_id, so workspace A's
automation tasks never silently use workspace B's API key.

Pattern: create two workspaces, each with its own active key, then verify
resolve_workspace_api_key returns the correct key for each workspace.
"""

import pytest

pytestmark = [pytest.mark.asyncio]


async def _create_test_key(db_session, workspace_id: str, label: str, key_body: str):
    """Insert a test key into apikeys table (plaintext, not encrypted — for test)."""
    from backend.models import APIKey
    from backend.security.crypto import encrypt_value
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
    resolve_workspace_api_key(ws_a) returns ws_a's key.
    resolve_workspace_api_key(ws_b) returns ws_b's key.
    They are NOT the same key.
    """
    from backend.services.runtime.teammate_runner import resolve_workspace_api_key
    from backend.database import async_session

    WS_A = "test-ws-a-000000000001"
    WS_B = "test-ws-b-000000000002"
    KEY_A = "«redacted:sk-…A»"
    KEY_B = "«redacted:sk-…B»"

    async with async_session() as sess:
        await _create_test_key(sess, WS_A, "test-key-a", KEY_A)
        await _create_test_key(sess, WS_B, "test-key-b", KEY_B)
        await sess.commit()

    try:
        result_a = await resolve_workspace_api_key(WS_A)
        result_b = await resolve_workspace_api_key(WS_B)

        assert result_a is not None, "ws_a resolves no key"
        assert result_b is not None, "ws_b resolves no key"

        api_key_a, _, provider_a = result_a
        api_key_b, _, provider_b = result_b

        # They are different keys
        assert api_key_a != api_key_b, \
            "Workspace A and B resolved to the same API key — no isolation!"

        # Each matches the expected key
        assert api_key_a == KEY_A, \
            f"ws_a expected {KEY_A[:12]}... got {api_key_a[:12]}..."
        assert api_key_b == KEY_B, \
            f"ws_b expected {KEY_B[:12]}... got {api_key_b[:12]}..."

        # Both preserve provider
        assert provider_a == "openrouter"
        assert provider_b == "openrouter"

        print(f"  ✓ ws_a key: {api_key_a[:12]}...")
        print(f"  ✓ ws_b key: {api_key_b[:12]}...")
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
    DEFENSIVE TEST (production still calls _apply_db_key_to_kwargs with
    workspace_id=None at maeos.py). It verifies that when no legacy global
    key (workspace_id IS NULL) exists, the resolver FAILS SAFE — raises
    ValueError and injects NO key — instead of silently borrowing a scoped
    workspace's key.
    """
    from backend.routes.maeos import _apply_db_key_to_kwargs
    kwargs = {}
    with pytest.raises(ValueError, match="No active API key found for scope 'legacy-global'"):
        await _apply_db_key_to_kwargs(kwargs)
    assert not kwargs.get("api_key"), "Resolver injected a key despite no legacy key — unsafe fallback!"
    print("  ✓ No legacy key → fails safe, no key injected")


async def test_workspace_without_key_raises_error():
    """
    A workspace that has no active key should raise ValueError
    (via _apply_db_key_to_kwargs wrapper), not silently borrow another
    workspace's key.
    """
    from backend.routes.maeos import _apply_db_key_to_kwargs
    kwargs = {}
    with pytest.raises(ValueError, match="No active API key found for scope 'nonexistent-workspace-id-xxx'"):
        await _apply_db_key_to_kwargs(kwargs, workspace_id="nonexistent-workspace-id-xxx")
    print("  ✓ No-key workspace raises ValueError, not silent fallback")
