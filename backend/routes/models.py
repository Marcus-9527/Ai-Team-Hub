"""
routes/models.py — Model listing & sync API.

Endpoints:
  GET  /api/models          — List all models (cached, auto-sync if stale)
  GET  /api/models/:provider  — List models for one provider
  POST /api/models/sync     — Force re-sync all models
"""
from fastapi import APIRouter

from backend.services.model_sync import (
    sync_models,
    get_cached_models_with_meta,
)

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def list_models():
    meta = get_cached_models_with_meta()
    if not meta["is_fresh"]:
        models = await sync_models()
        meta = {
            "models": models,
            "cached_at": 0,
            "is_fresh": True,
        }
    return {
        "providers": list(meta["models"].keys()),
        "total_models": sum(len(v) for v in meta["models"].values()),
        "models": meta["models"],
        "cached_at": meta["cached_at"],
    }


@router.get("/{provider_id}")
async def list_provider_models(provider_id: str):
    meta = get_cached_models_with_meta()
    if not meta["is_fresh"]:
        models = await sync_models()
        meta = {"models": models, "cached_at": 0, "is_fresh": True}
    provider_models = meta["models"].get(provider_id, [])
    return {
        "provider": provider_id,
        "models": provider_models,
        "count": len(provider_models),
    }


@router.post("/sync")
async def trigger_sync():
    models = await sync_models()
    total = sum(len(v) for v in models.values())
    return {
        "status": "ok",
        "providers": len(models),
        "total_models": total,
    }
