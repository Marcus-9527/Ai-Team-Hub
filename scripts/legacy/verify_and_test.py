#!/usr/bin/env python3
"""验证 D1 里的 OpenRouter key 并测试"""
import json, subprocess, os

# 用 curl 从 D1 获取 key
cmd = ["curl", "-s", "https://ai-team-hub.wt5371.workers.dev/api/apikeys", "-H", "User-Agent: Mozilla/5.0"]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
keys = json.loads(r.stdout)
or_key = [k["api_key"] for k in keys if k["provider"] == "openrouter"][0]
print(f"Key len: {len(or_key)}")
print(f"Key: {or_key[:30]}...")

# 用 curl 测试 owl-alpha（curl 走 proxy）
cmd2 = ["curl", "-s", "--max-time", "15", "-X", "POST",
        "https://openrouter.ai/api/v1/chat/completions",
        "-H", "Content-Type: application/json",
        "-H", "Authorization: Bearer " + or_key,
        "-H", "User-Agent: Mozilla/5.0",
        "-d", json.dumps({"model": "openrouter/owl-alpha",
                           "messages": [{"role": "user", "content": "say hi"}],
                           "max_tokens": 5, "stream": False})]

r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=20)
try:
    d = json.loads(r2.stdout)
    if "choices" in d:
        content = d["choices"][0]["message"]["content"]
        print(f"owl-alpha: OK - {content[:50]}")
    else:
        err = d.get("error", {}).get("message", "")[:80]
        print(f"owl-alpha: FAIL - {err}")
except:
    print(f"PARSE_ERR: {r2.stdout[:100]}")
