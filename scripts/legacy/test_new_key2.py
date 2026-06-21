#!/usr/bin/env python3
"""快速测试 — 用 curl 子进程"""
import json, subprocess, os

# 读取 key
with open('/home/liunx/workspace/ai-team-hub/.cf_token') as f:
    or_key = f.read().strip()

print(f"Key: {or_key[:20]}... len={len(or_key)}")

# 用 curl 测试（走系统 proxy）
cmd = ["curl", "-s", "--max-time", "15", "-X", "POST",
       "https://openrouter.ai/api/v1/chat/completions",
       "-H", "Content-Type: application/json",
       "-H", f"Authorization: Bearer {or_key}",
       "-H", "User-Agent: Mozilla/5.0",
       "-d", json.dumps({"model": "openrouter/owl-alpha",
                          "messages": [{"role": "user", "content": "say hi"}],
                          "max_tokens": 5, "stream": False})]

r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
try:
    d = json.loads(r.stdout)
    if "choices" in d:
        content = d["choices"][0]["message"]["content"]
        print(f"owl-alpha: OK - {content[:50]}")
    else:
        err = d.get("error", {}).get("message", "")[:80]
        print(f"owl-alpha: FAIL - {err}")
except:
    print(f"PARSE_ERR: {r.stdout[:100]}")
