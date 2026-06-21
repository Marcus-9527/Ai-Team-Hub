#!/usr/bin/env python3
"""Test OpenRouter models - subprocess curl with clean env"""
import json, subprocess, os

# Read key
with open('/home/liunx/workspace/ai-team-hub/.cf_token') as f:
    or_key = f.read().strip()

# Clean env - remove proxy vars so curl doesn't use proxy
# But curl needs proxy to reach external hosts...
# Let's try: use proxy but add --proxy-header to pass auth
env = {k: v for k, v in os.environ.items() if k not in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']}

# Get key from Worker (no proxy needed for Worker)
r = subprocess.run(
    ["curl", "-s", "https://ai-team-hub.wt5371.workers.dev/api/apikeys", "-H", "User-Agent: Mozilla/5.0"],
    capture_output=True, text=True, timeout=10, env=env
)
keys = json.loads(r.stdout)
or_key = [k["api_key"] for k in keys if k["provider"] == "openrouter"][0]
print(f"Key: {or_key[:20]}... (len={len(or_key)})")

# Test models using curl WITHOUT proxy
# This will fail for external hosts but let's see
models = ["openrouter/owl-alpha", "openrouter/auto", "google/gemini-2.0-flash", "meta-llama/llama-4-maverick"]

for model in models:
    cmd = [
        "curl", "-s", "--noproxy", "*", "--max-time", "10", "-X", "POST",
        "https://openrouter.ai/api/v1/chat/completions",
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {or_key}",
        "-H", "User-Agent: Mozilla/5.0",
        "-d", json.dumps({"model": model, "messages": [{"role": "user", "content": "say hi"}],
                           "max_tokens": 5, "stream": False})
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
    try:
        resp = json.loads(r.stdout)
        if "choices" in resp:
            content = resp["choices"][0]["message"]["content"]
            print(f"  {model}: OK - {content[:50]}")
        else:
            err = resp.get("error", {}).get("message", "")[:80]
            print(f"  {model}: FAIL - {err}")
    except:
        print(f"  {model}: PARSE_ERR - {r.stdout[:80]}")
