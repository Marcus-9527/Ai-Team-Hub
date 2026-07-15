"""Mount the built frontend (production) if dist exists."""
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from backend.middleware.security_headers import no_cache_html


def mount_frontend(app: FastAPI) -> None:
    frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if not os.path.exists(frontend_dist):
        return
    # SPA entry HTML must not be cached (CF edge would pin old index.html);
    # /assets/* carry content hashes and are safe to long-cache.
    app.middleware("http")(no_cache_html)
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
