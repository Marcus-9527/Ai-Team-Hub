"""CORS + CSP configuration constants."""
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
