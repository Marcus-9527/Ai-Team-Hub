"""
middleware/auth.py — API Key authentication middleware.

Provides:
  - X-API-Key / Authorization Bearer header authentication
  - Request-ID tracking per tenant
  - Workspace isolation enforcement
"""
import os
import uuid
import time
import secrets
import logging
from fastapi import Depends, HTTPException, Header, Request, Security
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("auth")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# ── Master API key (gates /api/* and /v1/*) ──
# Source priority: AI_TEAM_HUB_API_KEY env > persisted data/.api_key.
# If neither is set, a key is auto-provisioned on startup (locked by default)
# and written to data/.api_key + frontend/.env so the SPA keeps working.
# If provisioning fails, the gate stays OPEN (never hard-locks a running app).
API_KEY_ENV = "AI_TEAM_HUB_API_KEY"
# auth.py lives at backend/middleware/ → project root is two levels up.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_DATA_KEY_FILE = os.path.join(_DATA_DIR, ".api_key")
_FRONTEND_ENV = os.path.join(_PROJECT_ROOT, "frontend", ".env")

_master_key: str | None = None


def get_api_key() -> str | None:
    """Return the expected master API key (env > file), or None if unset."""
    global _master_key
    if _master_key is not None:
        return _master_key
    env = os.environ.get(API_KEY_ENV, "").strip()
    if env:
        _master_key = env
        return _master_key
    try:
        if os.path.exists(_DATA_KEY_FILE):
            with open(_DATA_KEY_FILE, "r") as f:
                v = f.read().strip()
                if v:
                    _master_key = v
                    return _master_key
    except OSError:
        pass
    return None


def _write_frontend_env(key: str) -> None:
    """Ensure frontend/.env carries VITE_API_KEY so the built SPA can auth."""
    try:
        lines = []
        if os.path.exists(_FRONTEND_ENV):
            with open(_FRONTEND_ENV, "r") as f:
                lines = f.read().splitlines()
        kept = [ln for ln in lines if not ln.startswith("VITE_API_KEY=")]
        kept.append(f"VITE_API_KEY={key}")
        with open(_FRONTEND_ENV, "w") as f:
            f.write("\n".join(kept) + "\n")
    except OSError as e:
        logger.warning("[auth] could not write frontend/.env: %s", e)


def ensure_api_key() -> str | None:
    """Provision a master key if none is configured. Returns the active key."""
    global _master_key
    existing = get_api_key()
    if existing is not None:
        return existing
    key = secrets.token_urlsafe(32)
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_DATA_KEY_FILE, "w") as f:
            f.write(key)
        _write_frontend_env(key)
        _master_key = key
        logger.warning(
            "[auth] No %s set — auto-provisioned a master API key and locked /api + /v1. "
            "Frontend .env written. Set %s to a fixed value in production.",
            API_KEY_ENV, API_KEY_ENV,
        )
    except OSError as e:
        logger.error("[auth] failed to provision API key: %s", e)
    return _master_key

# ── Admin key for sensitive management endpoints ──
# If AI_TEAM_HUB_ADMIN_KEY is unset, management endpoints stay OPEN (legacy
# dev behavior — existing frontend keeps working). If set, clients must send
# `Authorization: Bearer <key>` or `X-Admin-Key: <key>`.
ADMIN_KEY_ENV = "AI_TEAM_HUB_ADMIN_KEY"
_admin_scheme = HTTPBearer(auto_error=False)


async def require_admin(
    request: Request,
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    creds: HTTPAuthorizationCredentials | None = Depends(_admin_scheme),
):
    """Gate sensitive management endpoints behind an admin key.

    Open by default (no key configured) to preserve existing frontend behavior;
    enforced when AI_TEAM_HUB_ADMIN_KEY is set in the environment.
    """
    admin_key = os.environ.get(ADMIN_KEY_ENV, "").strip()
    if not admin_key:
        return  # open mode
    provided = None
    if authorization and authorization.startswith("Bearer "):
        provided = authorization[7:].strip()
    if provided is None and creds and creds.credentials:
        provided = creds.credentials
    if provided is None:
        provided = x_admin_key
    if provided != admin_key:
        raise HTTPException(status_code=403, detail="Admin authentication required")


class RequestContext:
    """Per-request tenant context."""
    def __init__(self, api_key: str = "", tenant_id: str = "", request_id: str = ""):
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.request_id = request_id or str(uuid.uuid4())
        self.start_time = time.time()

    @property
    def latency_ms(self) -> float:
        return round((time.time() - self.start_time) * 1000, 2)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Extracts API key from request, sets RequestContext.
    All /v1 routes require authentication.
    """

    def __init__(self, app, api_key_callback=None):
        super().__init__(app)
        self._key_callback = api_key_callback

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health, docs, and favicon only
        skip_paths = ("/api/health", "/v1/health", "/docs", "/openapi.json", "/favicon.ico")
        if request.url.path in skip_paths:
            return await call_next(request)

        # CORS preflight (OPTIONS) carries no API key — let CORSMiddleware answer
        # it. Blocking it with 401 makes every cross-origin API call fail in the
        # browser (the real request is never even attempted).
        if request.method == "OPTIONS":
            return await call_next(request)

        # Gate /api/* and /v1/* behind the master API key.
        # Default: LOCKED. A missing/explicitly-disabled key no longer opens the
        # gate (that was the "all data exposed" bug — a pre-key process stayed
        # open forever). Set AI_TEAM_HUB_AUTH_DISABLED=1 to opt out (dev only).
        if request.url.path.startswith("/v1") or request.url.path.startswith("/api"):
            expected = get_api_key()
            if os.environ.get("AI_TEAM_HUB_AUTH_DISABLED", "").strip() == "1":
                # Explicit dev opt-out — never the default.
                request.state.tenant_id = "default"
                request.state.api_key = "dev-disabled"
                return await call_next(request)
            if expected is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "API key not configured; set AI_TEAM_HUB_API_KEY"},
                )
            api_key = request.headers.get("X-API-Key", "")
            if not api_key:
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    api_key = auth[7:]
            # EventSource (SSE) can't send custom headers — allow key via query.
            if not api_key:
                api_key = request.query_params.get("api_key", "")
            if not api_key or api_key != expected:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid X-API-Key header"},
                )
            request.state.tenant_id = "default"
            request.state.api_key = api_key

        response = await call_next(request)
        req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        response.headers["X-Request-ID"] = req_id
        return response


async def validate_api_key(api_key: str) -> str:
    """Legacy middleware callback — kept for import compatibility.

    Master-key auth is now enforced directly in AuthMiddleware.dispatch via
    get_api_key(). The per-tenant DB-key model is retired; always returns the
    default tenant so a misconfigured caller never hard-fails.
    """
    return "default"
