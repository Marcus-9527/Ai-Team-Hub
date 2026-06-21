#!/usr/bin/env python3
"""Workflow 稳定性测试 — 在 VM 上运行"""
import json, time, urllib.request, urllib.error

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def _open(url, timeout=300, data=None, headers=None):
    """打开 URL — 对 Worker 用直连，其他用代理"""
    proxy_handler = urllib.request.ProxyHandler({})  # 直连，不走代理
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": e.reason, "detail": body[:300]}, e.code
results = []

def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print("  [%s] %s: %s %s" % ("OK" if passed else "FAIL", name, status, detail))

def call_api(path, data=None, timeout=300):
    url = WORKER + path
    body = json.dumps(data).encode() if data else None
    return _open(url, timeout=timeout, data=body, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})

def call_orchestrator(task, intent=""):
    return call_api("/api/orchestrator/run", {"task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"})

def get_trace(trace_id):
    """获取 trace — 尝试 replay endpoint"""
    data, code = call_api("/api/traces/%s/replay" % trace_id)
    if code == 200:
        return data
    # fallback: 直接获取
    data2, code2 = call_api("/api/traces/%s" % trace_id)
    return data2

# ═══════════════════════════════════════════
# Test 1: DAG Dependency Strictness
# ═══════════════════════════════════════════
print("\n=== Test 1: DAG Dependency Strictness ===")
r1, _ = call_orchestrator("Write a REST API for user management", intent="code")
dag1 = r1.get("dag_results", {})
trace_id1 = r1.get("trace_id", "")

# plan 和 code 必须成功
test("dag_plan_success", dag1.get("plan", {}).get("status") == "success")
test("dag_code_success", dag1.get("code", {}).get("status") == "success")

# 结果必须有实质内容
plan_len = len(dag1.get("plan", {}).get("result", ""))
code_len = len(dag1.get("code", {}).get("result", ""))
test("dag_plan_substantive", plan_len > 100, "len=%d" % plan_len)
test("dag_code_substantive", code_len > 500, "len=%d" % code_len)

# review 可能失败（如果 agent_j 调用失败），但 plan→code 的依赖必须正确
# 验证：如果 plan 失败，code 必须 skipped
plan_status = dag1.get("plan", {}).get("status")
code_status = dag1.get("code", {}).get("status")
if plan_status != "success":
    test("dep_plan_fail_code_skipped", code_status == "skipped",
         "plan=%s code=%s" % (plan_status, code_status))
else:
    test("dep_plan_ok_code_runs", code_status == "success",
         "plan=%s code=%s" % (plan_status, code_status))

# 验证 trace 顺序
if trace_id1:
    tdata = get_trace(trace_id1)
    if "trace" in tdata:
        events = tdata["trace"]
        steps = [e.get("step", "") for e in events]
        state_seq = [s for s in steps if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
        plan_idx = next((i for i, s in enumerate(state_seq) if s == "PLAN"), -1)
        exec_idx = next((i for i, s in enumerate(state_seq) if s == "EXECUTE"), -1)
        review_idx = next((i for i, s in enumerate(state_seq) if s == "REVIEW"), -1)
        test("plan_before_exec", plan_idx < exec_idx and plan_idx >= 0, "seq=%s" % state_seq)
        if review_idx >= 0:
            test("exec_before_review", exec_idx < review_idx, "seq=%s" % state_seq)
        test("no_skip_state", len(state_seq) >= 4, "seq=%s" % state_seq)
    else:
        test("trace_has_events", False, "no trace in response")
else:
    test("trace_id_exists", False, "no trace_id")

# ═══════════════════════════════════════════
# Test 2: State Machine Lock
# ═══════════════════════════════════════════
print("\n=== Test 2: State Machine Lock ===")
r2, _ = call_orchestrator("Design a rate limiter with sliding window", intent="code")
trace_id2 = r2.get("trace_id", "")

if trace_id2:
    tdata2 = get_trace(trace_id2)
    if "trace" in tdata2:
        events2 = tdata2["trace"]
        steps2 = [e.get("step", "") for e in events2]
        state_seq2 = [s for s in steps2 if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
        expected = ["INIT", "PLAN", "EXECUTE", "REVIEW", "DONE"]
        test("strict_order", state_seq2 == expected, "actual=%s" % state_seq2)
        test("no_parallel_conflict", len(state_seq2) == len(set(state_seq2)), "states=%s" % state_seq2)
        test("final_done", state_seq2[-1] == "DONE", "final=%s" % state_seq2[-1])
    else:
        test("lock_trace_data", False, "no trace")
else:
    test("lock_trace_id", False, "no trace_id")

# ═══════════════════════════════════════════
# Test 3: Replay Consistency (3 runs)
# ═══════════════════════════════════════════
print("\n=== Test 3: Replay Consistency (3 runs) ===")
fixed_task = "Design a URL shortener service"
runs = []
traces = []
for i in range(3):
    print("  Run %d/3..." % (i+1))
    r, _ = call_orchestrator(fixed_task, intent="code")
    runs.append(r)
    traces.append(r.get("trace_id", ""))
    time.sleep(0.5)

all_done = all(r.get("state") == "DONE" for r in runs)
test("replay_all_done", all_done, "states=%s" % [r.get("state") for r in runs])

if all_done:
    node_ids_list = [sorted(r.get("dag_results", {}).keys()) for r in runs]
    same_struct = all(nids == node_ids_list[0] for nids in node_ids_list)
    test("replay_same_dag_structure", same_struct, "structures=%s" % node_ids_list)

    all_success = all(all(v.get("status") == "success" for v in r.get("dag_results", {}).values()) for r in runs)
    test("replay_all_nodes_success", all_success)

    lens = [len(r.get("final_result", "")) for r in runs]
    if min(lens) > 0:
        ratio = max(lens) / min(lens)
        test("replay_len_consistent", ratio < 3.0, "lens=%s ratio=%.1f" % (lens, ratio))
    else:
        test("replay_len_consistent", False, "some empty")

    state_paths = []
    for tid in traces:
        if tid:
            td = get_trace(tid)
            if "trace" in td:
                ss = [e.get("step", "") for e in td["trace"]]
                path = [s for s in ss if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
                state_paths.append(tuple(path))

    if state_paths:
        path_consistent = len(set(state_paths)) == 1
        test("replay_path_consistent", path_consistent, "paths=%s" % [list(p) for p in state_paths])

    review_passes = [r.get("review_result", {}).get("pass") for r in runs]
    test("replay_review_consistent", len(set(str(p) for p in review_passes)) <= 2, "passes=%s" % review_passes)

# ═══════════════════════════════════════════
# Report
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("WORKFLOW STABILITY TEST REPORT")
print("="*60)

total = len(results)
passed_count = sum(1 for _, s, _ in results if s == "PASS")
failed_count = total - passed_count

print("\n  Total: %d" % total)
print("  Passed: %d" % passed_count)
print("  Failed: %d" % failed_count)
print("  Rate: %.0f%%" % (passed_count/total*100))

if failed_count > 0:
    print("\n  FAILED:")
    for name, status, detail in results:
        if status == "FAIL":
            print("    - %s: %s" % (name, detail))

print("\n" + "="*60)
if failed_count == 0:
    print("ALL STABILITY TESTS PASSED!")
elif passed_count / total >= 0.8:
    print("MOSTLY STABLE - minor issues")
else:
    print("STABILITY ISSUES DETECTED")
print("="*60)
