"""
Key Vault Service — secure API key management layer.

Architecture:
  All API key operations go through this service.
  Keys are encrypted at rest (DB), decrypted only in memory at call time.
  Never logged, never returned in API responses, never stored in global variables.

Flow:
  Request → KeyVaultService → decrypt in memory → LLM call → discard
"""
import hashlib
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models import APIKey
from backend.cache import apikey_cache
from backend.security.crypto import encrypt_value, decrypt_value

logger = logging.getLogger("key_vault_service")


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw key (for validation / dedup, never exposed)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()[:16]


async def add_key(
    provider: str,
    label: str,
    raw_key: str,
    base_url: str = "",
    db: Optional[AsyncSession] = None,
) -> dict:
    """Store a new encrypted API key. Returns metadata (never the key itself).

    Only ONE active key per provider (single-user mode).
    If an active key exists for this provider, it is deactivated.
    """
    async with async_session() as session:
        # Deactivate existing active keys for this provider
        result = await session.execute(
            select(APIKey).where(APIKey.provider == provider, APIKey.is_active == "1")
        )
        existing = result.scalars().all()
        for k in existing:
            k.is_active = "0"

        encrypted = encrypt_value(raw_key)
        key_hash = _hash_key(raw_key)

        new_key = APIKey(
            provider=provider,
            label=label,
            api_key=encrypted,
            key_hash=key_hash,
            base_url=base_url or None,
            is_active=True,
        )
        session.add(new_key)
        await session.commit()
        await session.refresh(new_key)

        # Invalidate cache for this provider
        apikey_cache.invalidate(new_key.id)
        apikey_cache.invalidate_prefix(f"provider:{provider}")

        logger.info("Key added: provider=%s label=%s id=%s (active)", provider, label, new_key.id)
        return {
            "id": new_key.id,
            "provider": new_key.provider,
            "label": new_key.label,
            "base_url": new_key.base_url,
            "is_active": new_key.is_active == "1",
            "has_key": True,
        }


async def get_key(
    key_id: str,
) -> Optional[tuple[str, str]]:
    """Retrieve and decrypt an API key by ID.

    Returns (decrypted_key, base_url) or None if not found / inactive.
    Key is decrypted in memory only — never persisted.
    """
    # Check cache first
    cached = apikey_cache.get(key_id)
    if cached is not None:
        return cached["api_key"], cached.get("base_url", "") or ""

    async with async_session() as session:
        result = await session.execute(select(APIKey).where(APIKey.id == key_id))
        obj = result.scalar_one_or_none()
        if not obj or obj.is_active != "1":
            return None

        plain = decrypt_value(obj.api_key)
        # Cache decrypted value (TTL-limited, in-memory only)
        apikey_cache.set(key_id, {"api_key": plain, "base_url": obj.base_url or ""})
        return plain, obj.base_url or ""


async def get_key_by_provider(provider: str) -> Optional[tuple[str, str, str]]:
    """Get the active key for a provider.

    Returns (key_id, decrypted_key, base_url) or None.
    """
    cache_key = f"provider:{provider}"
    cached = apikey_cache.get(cache_key)
    if cached is not None:
        return cached["id"], cached["api_key"], cached.get("base_url", "") or ""

    async with async_session() as session:
        result = await session.execute(
            select(APIKey).where(
                APIKey.provider == provider,
                APIKey.is_active == "1",
            ).order_by(APIKey.created_at.desc()).limit(1)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            return None

        plain = decrypt_value(obj.api_key)
        info = (obj.id, plain, obj.base_url or "")
        apikey_cache.set(cache_key, {"id": obj.id, "api_key": plain, "base_url": obj.base_url or ""})
        return info


async def rotate_key(key_id: str, new_raw_key: str) -> Optional[dict]:
    """Rotate an existing key. Deactivates old, creates new with same provider+label.

    Returns new key metadata or None if key_id not found.
    """
    async with async_session() as session:
        result = await session.execute(select(APIKey).where(APIKey.id == key_id))
        old = result.scalar_one_or_none()
        if not old:
            return None

        provider = old.provider
        label = old.label
        base_url = old.base_url

        # Deactivate old
        old.is_active = "0"
        apikey_cache.invalidate(old.id)

        # Create new
        encrypted = encrypt_value(new_raw_key)
        key_hash = _hash_key(new_raw_key)
        new_key = APIKey(
            provider=provider,
            label=label,
            api_key=encrypted,
            key_hash=key_hash,
            base_url=base_url,
            is_active=True,
        )
        session.add(new_key)
        await session.commit()
        await session.refresh(new_key)

        apikey_cache.invalidate_prefix(f"provider:{provider}")
        logger.info("Key rotated: provider=%s old=%s new=%s", provider, key_id, new_key.id)

        return {
            "id": new_key.id,
            "provider": new_key.provider,
            "label": new_key.label,
            "is_active": new_key.is_active == "1",
            "has_key": True,
        }


async def revoke_key(key_id: str) -> bool:
    """Deactivate a key. Returns True if found and deactivated."""
    async with async_session() as session:
        result = await session.execute(select(APIKey).where(APIKey.id == key_id))
        obj = result.scalar_one_or_none()
        if not obj:
            return False
        obj.is_active = "0"
        await session.commit()
        apikey_cache.invalidate(obj.id)
        apikey_cache.invalidate_prefix(f"provider:{obj.provider}")
        logger.info("Key revoked: provider=%s id=%s", obj.provider, key_id)
        return True


async def test_key(key_id: str) -> dict:
    """Check if a key exists and is active. Never returns the key itself."""
    async with async_session() as session:
        result = await session.execute(select(APIKey).where(APIKey.id == key_id))
        obj = result.scalar_one_or_none()
        if not obj:
            return {"exists": False, "is_active": False, "provider": None}
        return {
            "exists": True,
            "is_active": obj.is_active == "1",
            "provider": obj.provider,
            "label": obj.label,
            "has_key": bool(obj.api_key),
        }


async def list_keys(db: Optional[AsyncSession] = None) -> list[dict]:
    """List all active API keys (safe metadata only, never the keys themselves)."""
    async with async_session() as session:
        result = await session.execute(
            select(APIKey).where(APIKey.is_active == "1").order_by(APIKey.created_at)
        )
        keys = result.scalars().all()
        return [
            {
                "id": k.id,
                "provider": k.provider,
                "label": k.label,
                "base_url": k.base_url,
                "is_active": k.is_active == "1",
                "has_key": bool(k.api_key),
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ]
