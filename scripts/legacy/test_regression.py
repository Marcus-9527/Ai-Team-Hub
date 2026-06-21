#!/usr/bin/env python3
"""回归测试 — 9 个任务（简单/中等/复杂各 3 个）"""
import json, time, subprocess, os

# 禁用 proxy
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    icon = "OK" if passed else "FAIL"
    print(f"  [{icon}] {name}: {status} {detail}")

def post(path, data=None, timeout=180):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-X", "POST", WORKER + path,
           "-H", "Content-Type: application/json", "-H", "User-Agent: Mozilla/5.0"]
    if data:
        cmd.extend(["-d", json.dumps(data)])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+10)
        if r.returncode != 0:
            return {"error": "timeout"}, 0
        return json.loads(r.stdout), 200
    except json.JSONDecodeError:
        return {"error": "empty", "detail": r.stdout[:100] if r.stdout else "0 bytes"}, 0
    except Exception as e:
        return {"error": str(e)}, 0

def orch(task, intent=""):
    return post("/api/orchestrator/run",
        {"task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"})

def get_trace(tid):
    d, c = post(f"/api/traces/{tid}/replay")
    if c == 200 and "trace" in d:
        return d
    d2, _ = post(f"/api/traces/{tid}")
    return d2

# ── 回归测试任务 ──

TASKS = {
    "simple": [
        "Write a hello world in Python",
        "Create a function to add two numbers",
        "Design a user login API endpoint",
    ],
    "medium": [
        "Design a caching system with Redis",
        "Build a rate limiter with sliding window",
        "Create a task queue with priority scheduling",
    ],
    "complex": [
        "Design a recommendation system: research, implement, evaluate, optimize",
        "Build a distributed message queue with at-least-once delivery and dead letter queue",
        "Create a multi-agent decision system: plan, execute, critique, redesign",
    ],
}

print("=" * 60)
print("REGRESSION TEST — 9 tasks (3 simple / 3 medium / 3 complex)")
print("=" * 60)

for category, tasks in TASKS.items():
    print(f"\n--- {category.upper()} ---")
    for i, task in enumerate(tasks):
        print(f"\n  Task {i+1}: {task[:60]}...")
        r, code = orch(task, intent="code" if "code" in task.lower() or "function" in task.lower() or "API" in task else "")

        if "error" in r and r.get("error") == "timeout":
            test(f"{category}_{i+1}", False, "Worker timeout (cold start)")
            # 重试一次
            print("    Retrying...")
            time.sleep(5)
            r, code = orch(task)

        state = r.get("state", "ERROR")
        dag = r.get("dag_results", {})
        tid = r.get("trace_id", "")

        # 基本检查
        test(f"{category}_{i+1}_done", state == "DONE", f"state={state}")

        if dag:
            for node_id, node_result in dag.items():
                status = node_result.get("status", "missing")
                rlen = len(node_result.get("result", ""))
                cat = node_result.get("error_category", "")
                test(f"{category}_{i+1}_{node_id}_success", status == "success",
                     f"status={status} len={rlen} cat={cat}")

            # 检查 DAG 节点数 >= 3
            test(f"{category}_{i+1}_dag_nodes", len(dag) >= 3, f"nodes={len(dag)}")

            # 检查 plan → code 依赖
            plan_ok = dag.get("plan", {}).get("status") == "success"
            code_status = dag.get("code", {}).get("status", "missing")
            if not plan_ok:
                test(f"{category}_{i+1}_dep_plan_code", code_status == "skipped",
                     f"plan=failed code={code_status}")
            else:
                test(f"{category}_{i+1}_dep_plan_code", code_status == "success",
                     f"plan=ok code={code_status}")

        # 检查 review 输出
        review = r.get("review_result", {})
        if review:
            has_pass = "pass" in review
            has_reason = bool(review.get("reason"))
            has_cat = bool(review.get("failureCategory"))
            has_root = bool(review.get("rootCause"))
            has_sev = bool(review.get("severity"))
            test(f"{category}_{i+1}_review_structured",
                 has_pass and has_reason and has_cat and has_root and has_sev,
                 f"pass={has_pass} reason={has_reason} cat={has_cat} root={has_root} sev={has_sev}")

        # 检查 trace 顺序
        if tid:
            td = get_trace(tid)
            evts = td.get("trace", [])
            if evts:
                steps = [e.get("step", "") for e in evts]
                seq = [s for s in steps if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
                expected = ["INIT", "PLAN", "EXECUTE", "REVIEW", "DONE"]
                test(f"{category}_{i+1}_trace_order", seq == expected, f"seq={seq}")

        # 检查 final_result 非空
        fr = r.get("final_result", "")
        test(f"{category}_{i+1}_has_output", len(fr) > 50, f"len={len(fr)}")

        time.sleep(1)  # 避免 rate limit

# ── 报告 ──
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
    print(f"\n  FAILED ITEMS:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"    - {name}: {detail}")

# 按类别统计
for cat in ["simple", "medium", "complex"]:
    cat_results = [r for r in results if r[0].startswith(cat)]
    cat_pass = sum(1 for _, s, _ in cat_results if s == "PASS")
    cat_total = len(cat_results)
    if cat_total > 0:
        print(f"  {cat}: {cat_pass}/{cat_total} ({cat_pass/cat_total*100:.0f}%)")

print("\n" + "=" * 60)
if failed == 0:
    print("ALL REGRESSION TESTS PASSED!")
elif passed / total >= 0.8:
    print("MOSTLY PASSED - check failed items")
else:
    print("REGRESSION DETECTED - fixes may have broken existing functionality")
print("=" * 60)
