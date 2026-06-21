#!/usr/bin/env python3
"""快速测试 Worker orchestrator 超时问题"""
import json, time, urllib.request

WORKER = "https://ai-team-hub.wt5371.workers.dev"

# 获取 openrouter key
req = urllib.request.Request(WORKER + "/api/apikeys", headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=10) as r:
    keys = json.loads(r.read())
    or_key = [k["api_key"] for k in keys if k["provider"] == "openrouter"][0]

# 测试 1: 直接 LLM 调用延迟
print("=== Test 1: Direct LLM call latency ===")
start = time.time()
payload = json.dumps({
    "model": "openrouter/owl-alpha",
    "messages": [{"role": "user", "content": "say hi"}],
    "max_tokens": 5,
    "stream": False
}).encode()
req2 = urllib.request.Request(
    "https://openrouter.ai/api/v1/chat/completions",
    data=payload,
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + or_key, "User-Agent": "Mozilla/5.0"}
)
with urllib.request.urlopen(req2, timeout=30) as r:
    resp = json.loads(r.read())
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    latency = time.time() - start
    print(f"  owl-alpha: {latency:.1f}s -> {content[:50]}")

# 测试 2: Worker orchestrator（简单任务）
print("\n=== Test 2: Worker orchestrator (simple task) ===")
start = time.time()
payload2 = json.dumps({
    "task": "Write hello world in Python",
    "intent": "code",
    "provider": "openrouter",
    "model": "openrouter/owl-alpha"
}).encode()
req3 = urllib.request.Request(
    WORKER + "/api/orchestrator/run",
    data=payload2,
    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
)
try:
    with urllib.request.urlopen(req3, timeout=120) as r:
        result = json.loads(r.read())
        latency = time.time() - start
        print(f"  Status: {result.get('state')} in {latency:.1f}s")
        dag = result.get("dag_results", {})
        for k, v in dag.items():
            print(f"    [{k}] status={v.get('status')} len={len(v.get('result',''))}")
        print(f"  Final result length: {len(result.get('final_result',''))}")
except urllib.error.URLError as e:
    latency = time.time() - start
    print(f"  TIMEOUT after {latency:.1f}s: {e}")
except Exception as e:
    latency = time.time() - start
    print(f"  ERROR after {latency:.1f}s: {e}")
