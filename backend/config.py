"""Central configuration constants: CORS, CSP, and encryption key.

Keeping these together enforces the "config is centralized" rule — no
scattered os.environ reads for cross-cutting infrastructure settings.
"""
import os

_CORS_RAW = os.environ.get("CORS_ORIGINS", "")
if _CORS_RAW.strip():
    # Concrete origins → credentials allowed (RFC-compliant combo).
    CORS_ORIGINS: list[str] = [o.strip() for o in _CORS_RAW.split(",") if o.strip()]
    CORS_CREDENTIALS = True
else:
    # Open dev mode: any origin but WITHOUT credentials (valid combination).
    CORS_ORIGINS = ["*"]
    CORS_CREDENTIALS = False

# P3 #6 (short-term mitigation): a same-origin XSS can't pull an external
# script to exfiltrate the API key from localStorage. 'unsafe-eval' removed.
# 'unsafe-inline' retained (legacy/SPA inline scripts); drop after moving
# inline → external + nonce.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)

# ── Encryption key ──
# API keys are encrypted at rest (Fernet, see backend.security.crypto). The
# key itself is sourced from the env var below (or a file / auto-generated in
# dev). We centralize the env-var name here so it is not scattered, but the
# actual key loading/validation lives in backend.security.crypto (single source
# of truth for the crypto singleton).
ENCRYPTION_KEY_ENV = "AI_TEAM_HUB_CRYPTO_KEY"
# When set, startup refuses to fall back to file / auto-generated keys.
ENCRYPTION_KEY_REQUIRED = os.environ.get("AI_TEAM_HUB_CRYPTO_KEY_REQUIRED", "").lower() in (
    "1",
    "true",
    "yes",
)
