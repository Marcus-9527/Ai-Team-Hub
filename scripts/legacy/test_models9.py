#!/usr/bin/env python3
"""Test OpenRouter models - bypass proxy with ProxyHandler({})"""
import json, urllib.request, os

# Read key from file
with open('/home/liunx/workspace/ai-team-hub/.cf_token') as f:
    or_key = f.read().strip()

print(f"Key: {or_key[:20]}... (len={len(or_key)})")

# Bypass proxy entirely
proxy_handler = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(proxy_handler)

models = [
    "openrouter/owl-alpha",
    "openrouter/auto",
    "google/gemini-2.0-flash",
    "meta-llama/llama-4-maverick",
    "qwen/qwen3-235b",
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
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {or_key}",
                "User-Agent": "Mozilla/5.0"
            }
        )
        with opener.open(req, timeout=15) as r:
            resp = json.loads(r.read())
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"  {model}: OK - {content[:50]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:120]
        print(f"  {model}: HTTP {e.code} - {body[:100]}")
    except Exception as e:
        print(f"  {model}: ERROR - {type(e).__name__}: {e}")
