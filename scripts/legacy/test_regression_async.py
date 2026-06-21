#!/usr/bin/env python3
"""回归测试 — asyncio 并发版，每个任务独立超时"""
import json, time, asyncio, os

for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

WORKER = "https://ai-team-hub.wt5371.workers.dev"
OUTDIR = "/tmp/regression"
os.makedirs(OUTDIR, exist_ok=True)

results = []

def record(name, passed, detail=""):
    results.append((name, "PASS" if passed else "FAIL", detail))
    icon = "OK" if passed else "FAIL"
    print(f"  [{icon}] {name}: {detail}")

async def curl_post(session, path, data=None, timeout=300):
    """aiohttp POST"""
    import aiohttp
    url = WORKER + path
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    try:
        async with session.post(url, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            text = await resp.text()
            return json.loads(text), resp.status
    except asyncio.TimeoutError:
        return {"error": "timeout"}, 0
    except Exception as e:
        return {"error": str(e)}, 0

async def run_task(session, task_id, task, intent="code"):
    """运行单个任务"""
    print(f"  {task_id}: {task[:50]}...")
    r, code = await curl_post(session, "/api/orchestrator/run",
        {"task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"})

    if "error" in r and r.get("error") == "timeout":
        record(task_id, False, "timeout")
        return

    state = r.get("state", "ERROR")
    dag = r.get("dag_results", {})
    review = r.get("review_result", {})
    fr = r.get("final_result", "")

    record(f"{task_id}_done", state == "DONE", f"state={state}")

    for node_id, node_result in dag.items():
        status = node_result.get("status", "missing")
        rlen = len(node_result.get("result", ""))
        cat = node_result.get("error_category", "")
        record(f"{task_id}_{node_id}", status == "success", f"status={status} len={rlen} cat={cat}")

    if dag:
        nodes_ok = sum(1 for v in dag.values() if v.get("status") == "success")
        record(f"{task_id}_dag", nodes_ok >= 2, f"nodes={nodes_ok}/{len(dag)}")

    if review:
        has_all = all(k in review for k in ["pass", "failureCategory", "rootCause", "severity"])
        record(f"{task_id}_review", has_all, f"pass={'pass' in review} cat={'failureCategory' in review}")

    record(f"{task_id}_output", len(fr) > 50, f"len={len(fr)}")

async def main():
    import aiohttp

    # 任务列表
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

    print("=" * 60)
    print("REGRESSION TEST — 9 tasks")
    print("=" * 60)

    # 预热
    print("\nWarming up...")
    async with aiohttp.ClientSession() as session:
        await curl_post(session, "/api/orchestrator/run",
            {"task": "warmup", "intent": "code", "provider": "openrouter", "model": "openrouter/owl-alpha"})
    print("Ready.\n")

    # 串行执行（避免并发导致 Worker 过载）
    async with aiohttp.ClientSession() as session:
        for task_id, task, intent in tasks:
            print(f"--- {task_id} ---")
            await run_task(session, task_id, task, intent)
            await asyncio.sleep(1)  # 避免 rate limit

    # 报告
    print("\n" + "=" * 60)
    print("REGRESSION TEST REPORT")
    print("=" * 60)

    total = len(results)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = total - passed

    print(f"\n  Total: {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Rate: {passed/total*100:.0f}%")

    if failed > 0:
        print(f"\n  FAILED:")
        for name, status, detail in results:
            if status == "FAIL":
                print(f"    - {name}: {detail}")

    for prefix in ["s", "m", "c"]:
        cat = [r for r in results if r[0].startswith(prefix)]
        cp = sum(1 for _, s, _ in cat if s == "PASS")
        ct = len(cat)
        if ct > 0:
            label = {"s": "Simple", "m": "Medium", "c": "Complex"}[prefix]
            print(f"  {label}: {cp}/{ct} ({cp/ct*100:.0f}%)")

    print("\n" + "=" * 60)
    if failed == 0:
        print("ALL REGRESSION TESTS PASSED!")
    elif passed / total >= 0.8:
        print("MOSTLY PASSED - check failed items")
    else:
        print("REGRESSION DETECTED")
    print("=" * 60)

asyncio.run(main())
