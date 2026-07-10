"""
Plaintext API key migration — auto-detect and encrypt existing keys.

On startup, scans the apikeys table for unencrypted values.
If a value fails decryption (returns same value), it's treated as plaintext
and re-encrypted with Fernet.

Migrated keys are marked with is_active="1" and a new key_hash.
"""
import logging

from sqlalchemy import select

from backend.database import async_session
from backend.models import APIKey
from backend.security.crypto import encrypt_value, decrypt_value

logger = logging.getLogger("migration")


async def migrate_plaintext_keys() -> int:
    """Detect and encrypt any plaintext API keys in the database.

    Returns count of migrated keys.
    """
    migrated = 0
    async with async_session() as session:
        result = await session.execute(select(APIKey))
        keys = result.scalars().all()

        for key in keys:
            raw = key.api_key
            if not raw:
                continue

            # Try to decrypt — if it returns the same value, it's plaintext
            decrypted = decrypt_value(raw)
            if decrypted == raw:
                # This is a plaintext key — encrypt it
                logger.info("Migrating plaintext key: id=%s provider=%s", key.id, key.provider)
                encrypted = encrypt_value(decrypted)
                key.api_key = encrypted
                key.key_hash = None  # hash not available (no original raw key)
                migrated += 1

        if migrated > 0:
            await session.commit()
            logger.info("Migrated %d plaintext API keys to encrypted storage", migrated)

    return migrated
