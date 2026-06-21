#!/usr/bin/env python3
"""测试 OpenRouter 可用模型"""
import json, urllib.request, os

# 禁用 proxy
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

_proxy_handler = urllib.request.ProxyHandler({})
_opener = urllib.request.build_opener(_proxy_handler)

# 获取 key
req = urllib.request.Request("https://ai-team-hub.wt5371.workers.dev/api/apikeys", headers={"User-Agent": "Mozilla/5.0"})
with _opener.open(req, timeout=10) as r:
    keys = json.loads(r.read())
    or_key = [k["api_key"] for k in keys if k["provider"] == "openrouter"][0]

print(f"Key: {or_key[:20]}...")

models = [
    "openrouter/auto",
    "google/gemini-2.0-flash",
    "meta-llama/llama-4-maverick",
    "openrouter/owl-alpha",
    "qwen/qwen3-235b",
    "mistralai/mistral-7b-instruct",
]

for model in models:
    try:
        data = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "say hi"}],
            "max_tokens": 5,
            "stream": False
        }).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {or_key}", "User-Agent": "Mozilla/5.0"}
        )
        with _opener.open(req, timeout=15) as r:
            resp = json.loads(r.read())
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"  {model}: OK - {content[:50]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:100]
        print(f"  {model}: HTTP {e.code} - {body[:80]}")
    except Exception as e:
        print(f"  {model}: ERROR - {e}")
