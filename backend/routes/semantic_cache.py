"""
routes/semantic_cache.py — Semantic Cache API endpoints.

Provides:
  GET  /api/semantic-cache/stats    — Cache statistics
  POST /api/semantic-cache/lookup   — Manual cache lookup
  POST /api/semantic-cache/store    — Manual cache store
  POST /api/semantic-cache/normalize — Normalize a request
  DELETE /api/semantic-cache/clear  — Clear all caches
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any

from backend.services.kernel.cache_kernel import (
    normalize_request,
    compute_semantic_key,
    get_multi_layer_cache,
    CacheLayer,
    get_embedding_cache,
    get_prompt_deduplicator,
)

router = APIRouter(prefix="/api/semantic-cache", tags=["semantic-cache"])


class LookupRequest(BaseModel):
    text: str
    layer: Optional[str] = "output"
    teammate_id: Optional[str] = ""
    channel_id: Optional[str] = ""
    system_prompt: Optional[str] = ""


class StoreRequest(BaseModel):
    text: str
    value: Any
    layer: Optional[str] = "output"
    teammate_id: Optional[str] = ""
    channel_id: Optional[str] = ""
    system_prompt: Optional[str] = ""


class NormalizeRequest(BaseModel):
    text: str


@router.get("/stats")
async def stats():
    """Get all semantic cache statistics."""
    mlc = get_multi_layer_cache()
    emb = get_embedding_cache()
    dedup = get_prompt_deduplicator()

    return {
        "multi_layer": mlc.stats,
        "embedding": emb.stats,
        "prompt_dedup": dedup.stats,
    }


@router.post("/normalize")
async def normalize(req: NormalizeRequest):
    """Normalize a user request into structured intent format."""
    result = normalize_request(req.text)
    return result.to_dict()


@router.post("/lookup")
async def lookup(req: LookupRequest):
    """Look up a request in semantic cache."""
    normalized = normalize_request(req.text)
    cache_key = compute_semantic_key(
        normalized,
        teammate_id=req.teammate_id,
        channel_id=req.channel_id,
        system_prompt=req.system_prompt,
    )
    mlc = get_multi_layer_cache()
    emb = get_embedding_cache()

    layer = CacheLayer(req.layer) if req.layer else CacheLayer.OUTPUT

    # 1. Exact key lookup
    exact = mlc.get(layer, cache_key.key)
    if exact is not None:
        return {
            "hit": True,
            "source": "exact",
            "key": cache_key.key,
            "normalized": normalized.to_dict(),
            "cache_key": cache_key.to_dict(),
            "value": exact,
        }

    # 2. Embedding fuzzy lookup
    emb_result = emb.lookup(req.text, intent=normalized.intent.value, domain=normalized.domain.value)
    if emb_result.hit:
        return {
            "hit": True,
            "source": "embedding",
            "key": emb_result.key,
            "similarity": round(emb_result.similarity, 4),
            "normalized": normalized.to_dict(),
            "value": emb_result.value,
        }

    return {
        "hit": False,
        "source": "miss",
        "key": cache_key.key,
        "normalized": normalized.to_dict(),
        "cache_key": cache_key.to_dict(),
        "best_similarity": round(emb_result.similarity, 4),
    }


@router.post("/store")
async def store(req: StoreRequest):
    """Manually store a value in semantic cache."""
    normalized = normalize_request(req.text)
    cache_key = compute_semantic_key(
        normalized,
        teammate_id=req.teammate_id,
        channel_id=req.channel_id,
        system_prompt=req.system_prompt,
    )
    mlc = get_multi_layer_cache()
    emb = get_embedding_cache()

    layer = CacheLayer(req.layer) if req.layer else CacheLayer.OUTPUT
    mlc.set(layer, cache_key.key, req.value,
            intent=normalized.intent.value, domain=normalized.domain.value)
    emb.store(req.text, cache_key.key, req.value,
              intent=normalized.intent.value, domain=normalized.domain.value)

    return {
        "stored": True,
        "key": cache_key.key,
        "layer": layer.value,
        "normalized": normalized.to_dict(),
    }


@router.delete("/clear")
async def clear(layer: Optional[str] = None):
    """Clear semantic caches."""
    mlc = get_multi_layer_cache()
    emb = get_embedding_cache()
    dedup = get_prompt_deduplicator()

    if layer:
        mlc.clear(CacheLayer(layer))
    else:
        mlc.clear()
    emb.clear()
    dedup.clear()

    return {"cleared": True, "layer": layer or "all"}
