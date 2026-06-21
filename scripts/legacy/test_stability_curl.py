#!/usr/bin/env python3
"""Workflow 稳定性测试 — 用 curl 通过 proxy 访问 Worker"""
import json, time, subprocess, os

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print("  [%s] %s: %s %s" % ("OK" if passed else "FAIL", name, status, detail))

def curl_post(path, data=None, timeout=300):
    """用 curl 发送 POST 请求（通过 proxy）"""
    url = WORKER + path
    cmd = ["curl", "-s", "--max-time", str(timeout), "-X", "POST", url,
           "-H", "Content-Type: application/json",
           "-H", "User-Agent: Mozilla/5.0"]
    if data:
        cmd.extend(["-d", json.dumps(data)])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
    if result.returncode != 0:
        return {"error": "curl failed", "detail": result.stderr[:200]}, 0
    try:
        return json.loads(result.stdout), 200
    except json.JSONDecodeError:
        return {"error": "invalid JSON", "detail": result.stdout[:200]}, 0

def curl_get(path, timeout=30):
    """用 curl 发送 GET 请求"""
    url = WORKER + path
    cmd = ["curl", "-s", "--max-time", str(timeout), url,
           "-H", "User-Agent: Mozilla/5.0"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
    if result.returncode != 0:
        return {"error": "curl failed"}, 0
    try:
        return json.loads(result.stdout), 200
    except json.JSONDecodeError:
        return {"error": "invalid JSON"}, 0

def call_orchestrator(task, intent=""):
    return curl_post("/api/orchestrator/run", {
        "task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"
    })

def get_trace(trace_id):
    """获取 trace — 用 replay endpoint"""
    data, code = curl_get("/api/traces/%s/replay" % trace_id)
    if code == 200 and "trace" in data:
        return data
    # fallback
    data2, _ = curl_get("/api/traces/%s" % trace_id)
    return data2

# ═══════════════════════════════════════════
# Test 1: DAG Dependency Strictness
# ═══════════════════════════════════════════
print("\n=== Test 1: DAG Dependency Strictness ===")
r1, _ = call_orchestrator("Write a REST API for user management", intent="code")
dag1 = r1.get("dag_results", {})
trace_id1 = r1.get("trace_id", "")

for nid in ["plan", "code", "review"]:
    v = dag1.get(nid, {})
    status = v.get("status", "missing")
    rlen = len(v.get("result", ""))
    test("dag_%s_success" % nid, status == "success", "status=%s" % status)
    test("dag_%s_substantive" % nid, rlen > 100, "len=%d" % rlen)

# 验证依赖关系
plan_status = dag1.get("plan", {}).get("status", "missing")
code_status = dag1.get("code", {}).get("status", "missing")
if plan_status != "success":
    test("dep_plan_fail_code_skipped", code_status == "skipped",
         "plan=%s code=%s" % (plan_status, code_status))
else:
    test("dep_plan_ok_code_runs", code_status == "success",
         "plan=%s code=%s" % (plan_status, code_status))

# 验证 trace 顺序
if trace_id1:
    tdata = get_trace(trace_id1)
    events = tdata.get("trace", [])
    if events:
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
        test("trace_has_events", False, "no trace events")
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
    events2 = tdata2.get("trace", [])
    if events2:
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
        test("replay_len_consistent", ratio < 5.0, "lens=%s ratio=%.1f" % (lens, ratio))
    else:
        test("replay_len_consistent", False, "some empty")

    state_paths = []
    for tid in traces:
        if tid:
            td = get_trace(tid)
            evts = td.get("trace", [])
            if evts:
                ss = [e.get("step", "") for e in evts]
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
