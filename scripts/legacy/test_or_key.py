#!/usr/bin/env python3
"""Test new OpenRouter key"""
import json, subprocess, os

# Read key from file
with open('/home/liunx/workspace/ai-team-hub/.or_key_b64') as f:
    b64_key = f.read().strip()
or_key = __import__('base64').b64decode(b64_key).decode()
print(f"Key: {or_key[:20]}... len={len(or_key)}")

# Test owl-alpha
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
        print(f"owl-alpha: OK - {content[:50]}")
    else:
        err = d.get("error", {}).get("message", "")[:80]
        print(f"owl-alpha: FAIL - {err}")
except:
    print(f"PARSE_ERR: {r.stdout[:100]}")
