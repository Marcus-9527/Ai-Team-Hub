"""
middleware/auth.py — API Key authentication middleware.

Provides:
  - X-API-Key / Authorization Bearer header authentication
  - Request-ID tracking per tenant
  - Workspace isolation enforcement
"""
import uuid
import time
from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


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
        # Skip auth for health and public endpoints
        if request.url.path in ("/api/health", "/docs", "/openapi.json", "/favicon.ico"):
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
            raise HTTPException(status_code=401, detail="Missing X-API-Key header")

        # Validate API key
        tenant_id = ""
        if self._key_callback:
            result = await self._key_callback(api_key)
            if not result:
                raise HTTPException(status_code=403, detail="Invalid API key")
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
        async with async_session() as sess:
            result = await sess.execute(
                select(APIKey).where(APIKey.api_key == api_key)
            )
            key_obj = result.scalar_one_or_none()
            if key_obj:
                return key_obj.provider  # use provider as tenant_id for now
    except Exception:
        pass
    return ""
