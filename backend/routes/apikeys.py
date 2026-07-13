"""
API Key management routes — Key Vault architecture.

All keys are encrypted at rest (Fernet).
No endpoint ever returns a decrypted key.
All operations go through key_vault_service.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.middleware.auth import require_admin
from backend.services import key_vault_service as kvs
from backend.models import Teammate
from backend.cache import teammate_cache

logger = logging.getLogger("apikeys")

router = APIRouter(
    prefix="/api/apikeys",
    tags=["apikeys"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
async def list_apikeys():
    """List all API keys (safe metadata only)."""
    return await kvs.list_keys()


@router.post("")
async def create_apikey(data: dict):
    """Add a new API key. Encrypted at rest."""
    provider = data.get("provider")
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    raw_key = data.get("api_key")
    if not raw_key:
        raise HTTPException(status_code=400, detail="api_key is required")
    label = data.get("label", provider)
    base_url = data.get("base_url", "")

    result = await kvs.add_key(
        provider=provider,
        label=label,
        raw_key=raw_key,
        base_url=base_url,
    )
    # Propagate the new key to teammates that have no key yet, so a freshly
    # configured key actually reaches the channels (P1 #1 root cause).
    await _bind_key_to_unkeyed_teammates(result["id"])
    return result


async def _bind_key_to_unkeyed_teammates(key_id: str) -> int:
    """Bind a newly added/rotated key to every teammate lacking one.

    ponytail: single active key per provider is the model; auto-binding it to
    all unkeyed teammates is the minimal "workspace key inherits to channel"
    behaviour the UI implies. Skip teammates that already have a key.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Teammate).where(Teammate.api_key_ref.is_(None))
        )
        targets = result.scalars().all()
        for tm in targets:
            tm.api_key_ref = key_id
            teammate_cache.invalidate(tm.id)
        if targets:
            await session.commit()
            teammate_cache.invalidate("all")
        return len(targets)


@router.delete("/{apikey_id}")
async def delete_apikey(apikey_id: str):
    """Delete (revoke) an API key."""
    success = await kvs.revoke_key(apikey_id)
    if not success:
        raise HTTPException(status_code=404, detail="API Key not found")
    return {"ok": True, "id": apikey_id, "status": "revoked"}


# ── Key Vault Enterprise Endpoints ──


@router.get("/test/{apikey_id}")
async def test_apikey(apikey_id: str):
    """Check if a key exists and is active. Never returns the key itself."""
    return await kvs.test_key(apikey_id)


@router.post("/rotate")
async def rotate_apikey(data: dict):
    """Rotate an API key: deactivate old → create new with same provider/label."""
    key_id = data.get("key_id")
    new_key = data.get("api_key")
    if not key_id or not new_key:
        raise HTTPException(status_code=400, detail="key_id and api_key are required")

    result = await kvs.rotate_key(key_id, new_key)
    if not result:
        raise HTTPException(status_code=404, detail="API Key not found")
    return result


@router.post("/revoke")
async def revoke_apikey(data: dict):
    """Revoke an API key by ID."""
    key_id = data.get("key_id")
    if not key_id:
        raise HTTPException(status_code=400, detail="key_id is required")
    success = await kvs.revoke_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API Key not found")
    return {"ok": True, "id": key_id, "status": "revoked"}
