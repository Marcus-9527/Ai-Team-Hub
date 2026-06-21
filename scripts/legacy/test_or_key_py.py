#!/usr/bin/env python3
"""测试新 OpenRouter key — 用 Python subprocess"""
import json, subprocess, os

# 读取完整 key
with open("/tmp/_full_or_key.txt") as f:
    or_key = f.read().strip()
print(f"Key len: {len(or_key)}")

# 用 Python urllib 直接调用（不走 proxy）
import urllib.request
proxy_handler = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(proxy_handler)

data = json.dumps({
    "model": "openrouter/owl-alpha",
    "messages": [{"role": "user", "content": "say hi"}],
    "max_tokens": 5,
    "stream": False
}).encode()

req = urllib.request.Request(
    "https://openrouter.ai/api/v1/chat/completions",
    data=data,
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + or_key,
        "User-Agent": "Mozilla/5.0"
    }
)

try:
    with opener.open(req, timeout=15) as r:
        resp = json.loads(r.read())
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"owl-alpha: OK - {content[:50]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:120]
    print(f"owl-alpha: HTTP {e.code} - {body[:100]}")
except Exception as e:
    print(f"owl-alpha: ERROR - {type(e).__name__}: {e}")
