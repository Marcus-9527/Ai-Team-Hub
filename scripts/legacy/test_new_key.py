#!/usr/bin/env python3
"""快速测试新 API key"""
import json, urllib.request, os

# 禁用 proxy
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)
_proxy_handler = urllib.request.ProxyHandler({})
_opener = urllib.request.build_opener(_proxy_handler)

# 获取新 key
req = urllib.request.Request("https://ai-team-hub.wt5371.workers.dev/api/apikeys", headers={"User-Agent": "Mozilla/5.0"})
with _opener.open(req, timeout=10) as r:
    keys = json.loads(r.read())
    or_key = [k["api_key"] for k in keys if k["provider"] == "openrouter"][0]

print(f"New key: {or_key[:20]}... (len={len(or_key)})")

# 测试 owl-alpha
data = json.dumps({"model":"openrouter/owl-alpha","messages":[{"role":"user","content":"say hi"}],"max_tokens":5,"stream":False}).encode()
req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=data,
    headers={"Content-Type":"application/json","Authorization":"Bearer "+or_key,"User-Agent":"Mozilla/5.0"})
try:
    with _opener.open(req, timeout=15) as r:
        resp = json.loads(r.read())
        content = resp.get("choices",[{}])[0].get("message",{}).get("content","")
        print(f"owl-alpha: OK - {content[:50]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:100]
    print(f"owl-alpha: HTTP {e.code} - {body}")
