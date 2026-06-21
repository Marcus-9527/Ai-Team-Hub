#!/usr/bin/env python3
"""回归测试 — 直接调用 Worker（Worker 从 D1 读 key）"""
import json, time, urllib.request, os

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def record(name, passed, detail=""):
    results.append((name, "PASS" if passed else "FAIL", detail))
    print(f"  [{'OK' if passed else 'FAIL'}] {name}: {detail}")

def orch(task, intent="code"):
    url = WORKER + "/api/orchestrator/run"
    data = json.dumps({"task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())

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
    ("c1", "Design a recommendation system", "complex"),
    ("c2", "Build a distributed message queue", "complex"),
    ("c3", "Create a multi-agent decision system", "complex"),
]

for task_id, task, intent in tasks:
    print(f"--- {task_id}: {task[:50]}... ---")
    t0 = time.time()
    try:
        r = orch(task, intent)
        dt = time.time() - t0
        state = r.get("state", "ERROR")
        dag = r.get("dag_results", {})
        review = r.get("review_result", {})
        fr = r.get("final_result", "")
        
        record(f"{task_id}_done", state == "DONE", f"state={state} in {dt:.0f}s")
        for nid, v in dag.items():
            record(f"{task_id}_{nid}", v.get("status") == "success",
                   f"status={v.get('status')} len={len(v.get('result',''))}")
        if dag:
            ok = sum(1 for v in dag.values() if v.get("status") == "success")
            record(f"{task_id}_dag", ok >= 2, f"nodes={ok}/{len(dag)}")
        if review:
            has = all(k in review for k in ["pass","failureCategory","rootCause","severity"])
            record(f"{task_id}_review", has)
        record(f"{task_id}_output", len(fr) > 50, f"len={len(fr)}")
    except Exception as e:
        dt = time.time() - t0
        record(f"{task_id}_done", False, f"error in {dt:.0f}s: {str(e)[:80]}")
    time.sleep(1)

print("\n" + "="*60)
print("REGRESSION TEST REPORT")
print("="*60)
total = len(results)
passed = sum(1 for _,s,_ in results if s == "PASS")
failed = total - passed
print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed} | Rate: {passed/total*100:.0f}%")
for p in ["s","m","c"]:
    cat = [r for r in results if r[0].startswith(p)]
    cp = sum(1 for _,s,_ in cat if s == "PASS")
    ct = len(cat)
    if ct > 0:
        label = {"s":"Simple","m":"Medium","c":"Complex"}[p]
        print(f"  {label}: {cp}/{ct} ({cp/ct*100:.0f}%)")
print("\n" + "="*60)
if failed == 0: print("ALL PASSED!")
elif passed/total >= 0.8: print("MOSTLY PASSED")
else: print("REGRESSION DETECTED")
print("="*60)
