"""System endpoints: health + cache stats."""
from fastapi import APIRouter

from backend.cache import teammate_cache, channel_cache, apikey_cache, message_cache

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.get("/api/cache/stats")
async def cache_stats():
    from backend.services.kernel.cache_kernel import (
        get_multi_layer_cache, get_embedding_cache, get_prompt_deduplicator,
    )
    mlc = get_multi_layer_cache()
    emb = get_embedding_cache()
    dedup = get_prompt_deduplicator()
    return {
        "teammate_cache": teammate_cache.stats,
        "channel_cache": channel_cache.stats,
        "apikey_cache": apikey_cache.stats,
        "message_cache": message_cache.stats,
        "semantic_cache": {
            "multi_layer": mlc.stats,
            "embedding": emb.stats,
            "prompt_dedup": dedup.stats,
        },
    }
