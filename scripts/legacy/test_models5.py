#!/usr/bin/env python3
"""测试 OpenRouter 可用模型 — 控制 proxy"""
import json, subprocess, os

# 复制环境变量但移除代理
env = {k: v for k, v in os.environ.items() if k not in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']}

# 获取 key
r = subprocess.run(["curl", "-s", "https://ai-team-hub.wt5371.workers.dev/api/apikeys", "-H", "User-Agent: Mozilla/5.0"],
                   capture_output=True, text=True, timeout=10, env=env)
keys = json.loads(r.stdout)
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
    cmd = ["curl", "-s", "--max-time", "15", "-X", "POST",
           "https://openrouter.ai/api/v1/chat/completions",
           "-H", "Content-Type: application/json",
           "-H", f"Authorization: Bearer {or_key}",
           "-H", "User-Agent: Mozilla/5.0",
           "-d", json.dumps({"model": model, "messages": [{"role": "user", "content": "say hi"}],
                              "max_tokens": 5, "stream": False})]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
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
