"""
ai_service.py — LLM Runtime (v5 — FSM-compatible)

Streaming LLM call with connection pooling and cache key optimization.
Used by: agent_functions.py (orchestrator), messages.py (chat).
"""

import json
import hashlib
import logging
import sys
from typing import AsyncGenerator, Optional

import httpx

logger = logging.getLogger("ai_service")

# ── Provider Endpoints ──

PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "together": "https://api.together.xyz/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "moonshot": "https://api.moonshot.cn/v1/chat/completions",
    "baidu": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions",
    "alibaba": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1/chat/completions",
    "baichuan": "https://api.baichuan-ai.com/v1/chat/completions",
    "lingyi": "https://api.01.ai/v1/chat/completions",
    "minimax": "https://api.minimax.chat/v1/text/chatcompletion_v2",
    "stepfun": "https://api.stepfun.com/v1/chat/completions",
    "xfyun": "https://spark-api-open.xf-yun.com/v1/chat/completions",
    "siliconflow": "https://api.siliconflow.cn/v1/chat/completions",
}

WARMUP_USER_MESSAGE = "Reply with exactly: OK"

_http_client: Optional[httpx.AsyncClient] = None
_key_cache: dict[int, str] = {}
_ep_cache: dict[tuple[str, str], str] = {}


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=120.0)
    return _http_client


def _cached_key(prompt: str) -> str:
    h = hash(prompt) & 0xFFFFFFFF
    if h not in _key_cache:
        _key_cache[h] = hashlib.md5(prompt.encode()).hexdigest()[:16]
    return _key_cache[h]


def _get_ep(provider: str, base_url: str = None) -> str:
    key = (provider, base_url or "")
    if key not in _ep_cache:
        if base_url:
            _ep_cache[key] = base_url if base_url.endswith("/chat/completions") else f"{base_url.rstrip('/')}/v1/chat/completions"
        elif provider == "custom":
            _ep_cache[key] = ""
        else:
            _ep_cache[key] = PROVIDER_ENDPOINTS.get(provider, f"https://api.{provider}.com/v1/chat/completions")
    return _ep_cache[key]


async def stream_ai_response(
    system_prompt: str,
    messages: list[dict],
    provider: str,
    model: str,
    api_key: str,
    base_url: str = None,
    channel_id: str = None,
    teammate_id: str = None,
) -> AsyncGenerator[str, None]:
    """
    Streaming LLM call. Yields text chunks.

    Raises on error (caller handles).
    """
    endpoint = _get_ep(provider, base_url)
    client = _get_client()

    headers = {"Content-Type": "application/json"}
    is_anthropic = provider == "anthropic"

    if is_anthropic:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": messages,
            "max_tokens": 4096,
            "stream": True,
        }
    else:
        headers["Authorization"] = f"Bearer {api_key}"
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {
            "model": model,
            "messages": full_messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

    async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            raise RuntimeError(f"LLM error {resp.status_code}: {body[:300]}")

        async for line in resp.aiter_lines():
            if not line:
                continue
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    return
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if is_anthropic:
                    if obj.get("type") == "content_block_delta":
                        delta = obj.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield delta.get("text", "")
                else:
                    choices = obj.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content


async def warmup_cache(
    system_prompt: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = None,
) -> bool:
    """Send warm-up request to establish prefix cache."""
    try:
        endpoint = _get_ep(provider, base_url)
        client = _get_client()
        headers = {"Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": WARMUP_USER_MESSAGE},
            ],
            "max_tokens": 10,
            "stream": True,
        }

        async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
            if resp.status_code == 200:
                async for _ in resp.aiter_lines():
                    pass
                return True
            return False
    except Exception as e:
        logger.warning(f"Warmup failed: {e}")
        return False
