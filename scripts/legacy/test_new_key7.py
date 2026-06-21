#!/usr/bin/env python3
"""快速测试新 OpenRouter key"""
import json, subprocess, os

# 新 key（用户提供）
or_key = "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"
print("Key length:", len(or_key))

# 测试 owl-alpha
cmd = ["curl", "-s", "--max-time", "15", "-X", "POST",
       "https://openrouter.ai/api/v1/chat/completions",
       "-H", "Content-Type: application/json",
       "-H", "Authorization: Bearer " + or_key,
       "-H", "User-Agent: Mozilla/5.0",
       "-d", json.dumps({"model": "openrouter/owl-alpha",
                          "messages": [{"role": "user", "content": "say hi"}],
                          "max_tokens": 5, "stream": False})]

r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
try:
    d = json.loads(r.stdout)
    if "choices" in d:
        content = d["choices"][0]["message"]["content"]
        print("owl-alpha: OK -", content[:50])
    else:
        err = d.get("error", {}).get("message", "")[:80]
        print("owl-alpha: FAIL -", err)
except:
    print("PARSE_ERR:", r.stdout[:100])
