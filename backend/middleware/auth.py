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
import logging
from fastapi import Depends, HTTPException, Header, Request, Security
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("auth")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

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

        # Skip non-v1 routes (legacy /api/* routes don't require auth)
        if not request.url.path.startswith("/v1"):
            return await call_next(request)

        # Extract API key
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                api_key = auth[7:]

        if not api_key:
            return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key header"})

        # Validate API key
        tenant_id = ""
        if self._key_callback:
            result = await self._key_callback(api_key)
            if not result:
                return JSONResponse(status_code=403, content={"detail": "Invalid API key"})
            tenant_id = result

        # Set request context
        ctx = RequestContext(api_key=api_key, tenant_id=tenant_id)
        request.state.ctx = ctx
        request.state.request_id = ctx.request_id
        request.state.tenant_id = tenant_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = ctx.request_id
        return response


async def validate_api_key(api_key: str) -> str:
    """Validate an API key from the database. Returns tenant_id or empty string."""
    try:
        from backend.database import async_session
        from sqlalchemy import select
        from backend.models import APIKey
        from backend.crypto import decrypt_value
        async with async_session() as sess:
            result = await sess.execute(select(APIKey))
            keys = result.scalars().all()
            for k in keys:
                if decrypt_value(k.api_key) == api_key:
                    return k.label
    except Exception as e:
        logger.warning(f"API key validation error: {e}")
    return ""
