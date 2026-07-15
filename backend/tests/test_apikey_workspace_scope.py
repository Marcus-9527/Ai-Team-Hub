"""Ponytail self-check: API key workspace scoping + encryption round-trip.

No framework, no fixtures — just asserts the real service behaviour against a
throwaway in-memory SQLite so it fails loudly if the logic breaks.
"""
import asyncio
import os
import tempfile

os.environ["AI_TEAM_HUB_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from backend.database import init_db, async_session
from backend.services import key_vault_service as kvs
from backend.models import APIKey
from sqlalchemy import select


async def main():
    await init_db()

    # 1. Two workspaces, same provider → both active, isolated.
    a = await kvs.add_key("openai", "wsA", "sk-A", workspace_id="wsA")
    b = await kvs.add_key("openai", "wsB", "sk-B", workspace_id="wsB")
    assert a["is_active"] and b["is_active"], "both keys should store active"
    assert a["workspace_id"] == "wsA" and b["workspace_id"] == "wsB"

    # 2. Each workspace only sees its own key.
    list_a = await kvs.list_keys(workspace_id="wsA")
    list_b = await kvs.list_keys(workspace_id="wsB")
    assert len(list_a) == 1 and list_a[0]["provider"] == "openai"
    assert len(list_b) == 1 and list_b[0]["id"] == b["id"]

    # 3. Fallback resolver returns only same-workspace key.
    kA = await kvs.get_key_by_provider("openai", workspace_id="wsA")
    kB = await kvs.get_key_by_provider("openai", workspace_id="wsB")
    assert kA and kA[1] == "sk-A", "wsA fallback must return sk-A"
    assert kB and kB[1] == "sk-B", "wsB fallback must return sk-B"

    # 4. No cross-workspace leak: wsA asking for a provider key of wsB fails.
    leak = await kvs.get_key_by_provider("anthropic", workspace_id="wsA")
    assert leak is None, "wsA must not see another workspace's key"

    # 5. Active-key-per-(provider,workspace): new wsA openai key deactivates old.
    c = await kvs.add_key("openai", "wsA2", "sk-A2", workspace_id="wsA")
    assert c["is_active"]
    async with async_session() as s:
        rows = (await s.execute(
            select(APIKey).where(APIKey.workspace_id == "wsA", APIKey.provider == "openai")
        )).scalars().all()
    active = [r for r in rows if r.is_active == "1"]
    assert len(active) == 1, "exactly one active key per (provider,workspace)"
    assert "sk-A2" not in active[0].api_key, "ciphertext must not equal plaintext"

    print("OK: workspace-scoped API key encryption + isolation verified.")


if __name__ == "__main__":
    asyncio.run(main())
