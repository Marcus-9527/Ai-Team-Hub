"""
Encryption utilities for sensitive data (API keys, etc.).

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
Key sourced from AI_TEAM_HUB_CRYPTO_KEY env var or auto-generated file.

Architecture:
  - ENV var > file-based key
  - Lazy initialization with global singleton
  - Auto-generates key file on first run (dev convenience)
  - validate_key() for startup health checks
"""
import os
import sys
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("security.crypto")

ENCRYPTION_KEY_ENV = "AI_TEAM_HUB_CRYPTO_KEY"

_KEY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", ".crypto_key"
)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Get or initialize the Fernet cipher singleton."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.environ.get(ENCRYPTION_KEY_ENV)
    if key:
        try:
            _fernet = Fernet(key.encode() if isinstance(key, str) else key)
            return _fernet
        except Exception as e:
            logger.warning(
                "%s is not a valid Fernet key (%s), falling back to file-based key",
                ENCRYPTION_KEY_ENV, e,
            )

    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            _fernet = Fernet(f.read().strip())
            return _fernet

    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(_KEY_FILE), exist_ok=True)
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    logger.info("Generated new crypto key at %s", _KEY_FILE)
    _fernet = Fernet(key)
    return _fernet


def reset_fernet() -> None:
    """Reset the singleton (for testing or key rotation)."""
    global _fernet
    _fernet = None


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns Fernet token (base64 string)."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet token. Returns original plaintext.

    If ciphertext is not valid Fernet, returns it as-is (forward compat
    for unencrypted values during migration).
    """
    if not ciphertext:
        return ciphertext
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Not encrypted or unknown format — return as-is for migration compat
        return ciphertext


def get_encryption_key_info() -> dict:
    """Return info about the current encryption key (safe for display/logging)."""
    source = "env_var" if os.environ.get(ENCRYPTION_KEY_ENV) else (
        "file" if os.path.exists(_KEY_FILE) else "auto_generated"
    )
    return {
        "source": source,
        "key_file_exists": os.path.exists(_KEY_FILE),
        "key_file_path": _KEY_FILE,
    }


def validate_key() -> None:
    """Check that a valid encryption key is configured. Raises RuntimeError on failure."""
    f = _get_fernet()
    # Round-trip test
    test = "validation_test_string"
    token = f.encrypt(test.encode())
    result = f.decrypt(token).decode()
    if result != test:
        raise RuntimeError("Encryption key round-trip validation failed")
    logger.info("Encryption key validated (source: %s)", get_encryption_key_info()["source"])
