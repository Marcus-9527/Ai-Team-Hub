"""
model_sync.py — Fetch latest model lists from all providers.

Primary source: OpenRouter public API (covers ~50+ providers).
Secondary: provider-specific APIs (when API keys are configured).
Cache: backend/data/models_cache.json with timestamp.
"""
import json
import os
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger("model_sync")

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "models_cache.json")
CACHE_TTL = 3600  # 1 hour

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Provider model-list API templates.
# Key = provider id, value = (api_url, api_key_header, api_key_template, response_path)
# OpenAI-compatible providers use: GET {base}/models -> {"data": [{"id": "...", ...}]}
# We strip /chat/completions from the chat endpoint to get the base.
PROVIDER_MODEL_LIST_API = {
    "openai":       ("https://api.openai.com/v1/models",                     "Authorization", "Bearer {}",        ["data"]),
    "anthropic":    ("https://api.anthropic.com/v1/models",                  "x-api-key",     "{}",              ["data"]),
    "google":       ("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key", "{}",         ["models"]),
    "deepseek":     ("https://api.deepseek.com/v1/models",                   "Authorization", "Bearer {}",        ["data"]),
    "mistral":      ("https://api.mistral.ai/v1/models",                     "Authorization", "Bearer {}",        ["data"]),
    "groq":         ("https://api.groq.com/openai/v1/models",                "Authorization", "Bearer {}",        ["data"]),
    "together":     ("https://api.together.xyz/v1/models",                   "Authorization", "Bearer {}",        ["data"]),
    "moonshot":      ("https://api.moonshot.cn/v1/models",                    "Authorization", "Bearer {}", ["data"]),
    "alibaba":       ("https://dashscope.aliyuncs.com/compatible-mode/v1/models", "Authorization", "Bearer {}", ["data"]),
    "siliconflow":  ("https://api.siliconflow.cn/v1/models",                 "Authorization", "Bearer {}",        ["data"]),
    "opencode-zen": ("https://opencode.ai/zen/v1/models",                   "Authorization", "Bearer {}",        ["data"]),
    "opencode":     ("https://opencode.ai/zen/v1/models",                   "Authorization", "Bearer {}",        ["data"]),
    # openrouter intentionally omitted — already handled by fetch_openrouter_models()
}

# OpenRouter provider prefix → our provider ID mapping
OPENROUTER_PROVIDER_MAP = {
    "openai": "openai",
    "anthropic": "anthropic",
    "~anthropic": "anthropic",
    "google": "google",
    "~google": "google",
    "deepseek": "deepseek",
    "mistralai": "mistral",
    "openrouter": "openrouter",
    "moonshotai": "moonshot",
    "~moonshotai": "moonshot",
    "baidu": "baidu",
    "qwen": "alibaba",
    "bytedance": "doubao",
    "bytedance-seed": "doubao",
    "minimax": "minimax",
    "stepfun": "stepfun",
    "tencent": "hunyuan",
    "cohere": "cohere",
    "meta-llama": "meta-llama",
    "amazon": "amazon",
    "x-ai": "xai",
    "nvidia": "nvidia",
    "microsoft": "microsoft",
    "ibm-granite": "ibm",
    "z-ai": "z-ai",
    "nousresearch": "nousresearch",
    "perplexity": "perplexity",
    "ai21": "ai21",
    "inflection": "inflection",
    "sakana": "sakana",
    "liquid": "liquid",
    "writer": "writer",
    "upstage": "upstage",
}

# Providers we support that need static/alternative sources
STATIC_ONLY_PROVIDERS = {
    "zhipu", "baichuan", "yi", "spark", "siliconflow", "custom",
}


def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(data: dict):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _is_cache_fresh(timestamp: float) -> bool:
    return time.time() - timestamp < CACHE_TTL


async def fetch_openrouter_models(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get(OPENROUTER_MODELS_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", data if isinstance(data, list) else [])


def _map_openrouter_to_our_providers(
    openrouter_models: list[dict],
) -> dict[str, list[dict]]:
    result = {}
    for m in openrouter_models:
        mid: str = m.get("id", "")
        if not mid or "/" not in mid:
            continue
        prefix = mid.split("/")[0]
        our_provider = OPENROUTER_PROVIDER_MAP.get(prefix)
        if not our_provider:
            continue
        pricing = m.get("pricing") or {}
        is_free = pricing.get("prompt") == "0" and pricing.get("completion") == "0"
        entry = {
            "id": mid,
            "name": m.get("name", mid),
            "context_length": m.get("context_length", 0),
            "description": (m.get("description") or "")[:200],
            "is_free": is_free,
        }
        result.setdefault(our_provider, []).append(entry)
    return result


def _normalize_model_id(mid: str) -> str:
    """Strip common prefixes/suffixes to get a clean model id."""
    return mid.replace("/", "-")


async def _load_configured_apikeys() -> dict[str, str]:
    """Load API keys from DB via async session, grouped by provider. Returns {provider: api_key}."""
    try:
        from sqlalchemy import select
        from backend.database import async_session
        from backend.models import APIKey
        async with async_session() as db:
            rows = (await db.execute(select(APIKey))).scalars().all()
        from backend.crypto import decrypt_value
        result = {}
        for key in rows:
            if not key.api_key:
                continue
            plain = decrypt_value(key.api_key)
            if plain:
                result[key.provider] = plain
        return result
    except Exception as e:
        logger.debug("Could not load API keys: %s", e)
        return {}


def _normalize_provider_models(
    raw: list[dict],
    provider_id: str,
    id_field: str = "id",
) -> list[dict]:
    """Normalize a raw model list from a provider API into our internal format."""
    result = []
    for m in raw:
        mid = m.get(id_field, "")
        if not mid:
            continue
        # For google, ids look like "models/gemini-2.0-flash"
        clean_id = mid.replace("models/", "")
        entry = {
            "id": clean_id,
            "name": m.get("name", m.get("display_name", clean_id)),
            "context_length": m.get("context_length", m.get("max_input_tokens", 0)),
            "description": "",
        }
        result.append(entry)
    return result


async def _fetch_direct_provider_models(
    client: httpx.AsyncClient,
    provider_id: str,
    api_key: str,
) -> Optional[list[dict]]:
    """Fetch models directly from a single provider's API."""
    spec = PROVIDER_MODEL_LIST_API.get(provider_id)
    if not spec:
        return None

    url, header_name, header_template, path_keys = spec
    header_value = header_template.format(api_key)
    headers = {"Content-Type": "application/json", header_name: header_value}

    try:
        resp = await client.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for key in path_keys:
            if isinstance(data, dict):
                data = data.get(key, data)
            else:
                break
        raw_list = data if isinstance(data, list) else []
        return _normalize_provider_models(raw_list, provider_id)
    except Exception as e:
        logger.debug("Direct fetch failed for %s: %s", provider_id, e)
        return None


STATIC_FALLBACK = {
    "zhipu": ["glm-4-plus", "glm-4-air", "glm-4-airx", "glm-4-flash", "glm-4-long", "glm-4v", "glm-4v-plus", "glm-4", "glm-3-turbo", "codegeex-4"],
    "baichuan": ["Baichuan4", "Baichuan3-Turbo", "Baichuan3", "Baichuan2-Turbo", "Baichuan2-13B-Chat", "Baichuan2-7B-Chat"],
    "yi": ["yi-lightning", "yi-large", "yi-large-turbo", "yi-medium", "yi-medium-200k", "yi-vision", "yi-spark", "yi-coder"],
    "spark": ["spark-4.0-ultra", "spark-4.0", "spark-3.5", "spark-3.5-128k", "spark-3.0", "spark-2.0", "spark-lite", "spark-pro", "spark-pro-128k"],
    "siliconflow": ["Qwen/Qwen3-235B-A22B", "Qwen/Qwen3-30B-A3B", "Qwen/Qwen3-32B", "Qwen/Qwen3-14B", "Qwen/Qwen3-8B", "deepseek-ai/DeepSeek-V3.1", "deepseek-ai/DeepSeek-R1-0528", "deepseek-ai/DeepSeek-R1", "deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct", "meta-llama/Llama-3.1-8B-Instruct", "google/gemma-2-27b-it", "google/gemma-2-9b-it"],
    "custom": [],
}


def _get_static_fallback() -> dict[str, list[dict]]:
    result = {}
    for provider_id, model_ids in STATIC_FALLBACK.items():
        result[provider_id] = [
            {"id": mid, "name": mid, "context_length": 0, "description": ""}
            for mid in model_ids
        ]
    return result


async def sync_models() -> dict[str, list[dict]]:
    all_models = {}

    api_keys = await _load_configured_apikeys()
    logger.info("Loaded %d API keys for direct provider fetch", len(api_keys))

    async with httpx.AsyncClient(timeout=30) as client:
        # 1) OpenRouter (primary source)
        try:
            raw = await fetch_openrouter_models(client)
            or_models = _map_openrouter_to_our_providers(raw)
            logger.info(
                "OpenRouter: %d models across %d provider groups",
                len(raw), len(or_models),
            )
            all_models.update(or_models)
        except Exception as e:
            logger.warning("OpenRouter fetch failed: %s", e)

        # 2) Direct per-provider fetch (for providers with configured API keys)
        for provider_id, api_key in api_keys.items():
            if provider_id in PROVIDER_MODEL_LIST_API:
                direct = await _fetch_direct_provider_models(client, provider_id, api_key)
                if direct:
                    logger.info(
                        "Direct fetch %s: %d models", provider_id, len(direct)
                    )
                    all_models[provider_id] = direct

        # 3) Refresh OpenRouter again if any provider is still missing
        #    (handles providers without configured keys)

    # 4) Static fallback for providers without online sources
    static = _get_static_fallback()
    for pid in STATIC_ONLY_PROVIDERS:
        if pid in static:
            all_models.setdefault(pid, static[pid])

    for pid in set(
        list(OPENROUTER_PROVIDER_MAP.values()) + list(STATIC_ONLY_PROVIDERS)
    ):
        if pid not in all_models and pid in static:
            all_models[pid] = static[pid]

    cache_data = {
        "timestamp": time.time(),
        "models": all_models,
    }
    _save_cache(cache_data)
    logger.info("Synced models for %d providers", len(all_models))
    return all_models


def get_cached_models() -> Optional[dict[str, list[dict]]]:
    cache = _load_cache()
    ts = cache.get("timestamp", 0)
    if _is_cache_fresh(ts):
        return cache.get("models")
    return None


def get_cached_models_with_meta() -> dict:
    cache = _load_cache()
    ts = cache.get("timestamp", 0)
    return {
        "models": cache.get("models", {}),
        "cached_at": ts,
        "is_fresh": _is_cache_fresh(ts),
    }


async def get_models(provider_id: str = None) -> dict:
    cached = get_cached_models()
    if cached is None:
        cached = await sync_models()
    if provider_id:
        return {provider_id: cached.get(provider_id, [])}
    return cached
