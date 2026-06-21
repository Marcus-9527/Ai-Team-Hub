#!/usr/bin/env python3
"""回归测试 — 最终版，urllib 直连"""
import json, time, urllib.request, urllib.error, os

# 禁用 proxy
_proxy_handler = urllib.request.ProxyHandler({})
_opener = urllib.request.build_opener(_proxy_handler)

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def record(name, passed, detail=""):
    results.append((name, "PASS" if passed else "FAIL", detail))
    print(f"  [{'OK' if passed else 'FAIL'}] {name}: {detail}")

def post(path, data=None, timeout=300):
    url = WORKER + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.reason, "detail": e.read().decode()[:300]}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def orch(task, intent="code"):
    return post("/api/orchestrator/run",
        {"task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"})

# 预热
print("Warming up...")
orch("warmup")
print("Ready.\n")

tasks = [
    ("s1", "Write a hello world in Python", "code"),
    ("s2", "Create a function to add two numbers", "code"),
    ("s3", "Design a user login API endpoint", "code"),
    ("m1", "Design a caching system with Redis", "code"),
    ("m2", "Build a rate limiter with sliding window", "code"),
    ("m3", "Create a task queue with priority scheduling", "code"),
    ("c1", "Design a recommendation system: research, implement, evaluate, optimize", "complex"),
    ("c2", "Build a distributed message queue with at-least-once delivery", "complex"),
    ("c3", "Create a multi-agent decision system: plan, execute, critique, redesign", "complex"),
]

for task_id, task, intent in tasks:
    print(f"--- {task_id}: {task[:50]}... ---")
    r, _ = orch(task, intent)
    
    state = r.get("state", "ERROR")
    dag = r.get("dag_results", {})
    review = r.get("review_result", {})
    fr = r.get("final_result", "")
    
    record(f"{task_id}_done", state == "DONE", f"state={state}")
    
    for nid, v in dag.items():
        record(f"{task_id}_{nid}", v.get("status") == "success",
               f"status={v.get('status')} len={len(v.get('result',''))} cat={v.get('error_category','')}")
    
    if dag:
        ok = sum(1 for v in dag.values() if v.get("status") == "success")
        record(f"{task_id}_dag", ok >= 2, f"nodes={ok}/{len(dag)}")
    
    if review:
        has = all(k in review for k in ["pass","failureCategory","rootCause","severity"])
        record(f"{task_id}_review", has)
    
    record(f"{task_id}_output", len(fr) > 50, f"len={len(fr)}")
    
    time.sleep(1)

# 报告
print("\n" + "="*60)
print("REGRESSION TEST REPORT")
print("="*60)
total = len(results)
passed = sum(1 for _,s,_ in results if s == "PASS")
failed = total - passed
print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed} | Rate: {passed/total*100:.0f}%")
if failed > 0:
    print("\nFAILED:")
    for n,s,d in results:
        if s == "FAIL": print(f"  - {n}: {d}")
for p in ["s","m","c"]:
    cat = [r for r in results if r[0].startswith(p)]
    cp = sum(1 for _,s,_ in cat if s == "PASS")
    ct = len(cat)
    if ct > 0:
        print(f"  {p}: {cp}/{ct} ({cp/ct*100:.0f}%)")
print("\n" + "="*60)
if failed == 0: print("ALL PASSED!")
elif passed/total >= 0.8: print("MOSTLY PASSED")
else: print("REGRESSION DETECTED")
print("="*60)
