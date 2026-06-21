#!/usr/bin/env python3
"""Workflow 稳定性测试 — 快速版（每个测试 1 次执行）"""
import json, time, urllib.request

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print("  [%s] %s: %s %s" % ("OK" if passed else "FAIL", name, status, detail))

def call_api(path, data=None, timeout=300):
    url = WORKER + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()), resp.status

def call_orchestrator(task, intent=""):
    return call_api("/api/orchestrator/run", {"task":task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"})

# ═══════════════════════════════════════════
# Test 1: DAG Dependency Strictness
# ═══════════════════════════════════════════
print("\n=== Test 1: DAG Dependency Strictness ===")
r1, _ = call_orchestrator("Write a REST API for user management", intent="code")
dag1 = r1.get("dag_results", {})
trace_id1 = r1.get("trace_id", "")

for nid, v in dag1.items():
    rlen = len(v.get("result", ""))
    test("dag_%s_success" % nid, v.get("status") == "success", "status=%s" % v.get("status"))
    test("dag_%s_substantive" % nid, rlen > 100, "len=%d" % rlen)

# 验证 trace 顺序
if trace_id1:
    tdata, _ = call_api("/api/traces/%s" % trace_id1)
    events = tdata.get("trace", [])
    steps = [e.get("step", "") for e in events]
    state_seq = [s for s in steps if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
    test("plan_before_exec", state_seq.index("PLAN") < state_seq.index("EXECUTE"), "seq=%s" % state_seq)
    test("exec_before_review", state_seq.index("EXECUTE") < state_seq.index("REVIEW"), "seq=%s" % state_seq)
    test("no_skip_state", len(state_seq) >= 5, "seq=%s" % state_seq)

# ═══════════════════════════════════════════
# Test 2: State Machine Lock
# ═══════════════════════════════════════════
print("\n=== Test 2: State Machine Lock ===")
r2, _ = call_orchestrator("Design a rate limiter with sliding window", intent="code")
trace_id2 = r2.get("trace_id", "")

if trace_id2:
    tdata2, _ = call_api("/api/traces/%s" % trace_id2)
    events2 = tdata2.get("trace", [])
    steps2 = [e.get("step", "") for e in events2]
    state_seq2 = [s for s in steps2 if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]

    # 验证严格顺序：INIT→PLAN→EXECUTE→REVIEW→DONE
    expected = ["INIT", "PLAN", "EXECUTE", "REVIEW", "DONE"]
    test("strict_order", state_seq2 == expected, "actual=%s expected=%s" % (state_seq2, expected))
    test("no_parallel_conflict", len(state_seq2) == len(set(state_seq2)), "states=%s" % state_seq2)
    test("final_done", state_seq2[-1] == "DONE", "final=%s" % state_seq2[-1] if state_seq2 else "empty")
else:
    test("lock_trace_exists", False, "no trace_id")

# ═══════════════════════════════════════════
# Test 3: Replay Consistency
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
    # DAG 结构一致性
    node_ids_list = [sorted(r.get("dag_results", {}).keys()) for r in runs]
    same_struct = all(nids == node_ids_list[0] for nids in node_ids_list)
    test("replay_same_dag_structure", same_struct, "structures=%s" % node_ids_list)

    # 所有节点成功
    all_success = all(all(v.get("status") == "success" for v in r.get("dag_results", {}).values()) for r in runs)
    test("replay_all_nodes_success", all_success)

    # 结果长度一致性
    lens = [len(r.get("final_result", "")) for r in runs]
    if min(lens) > 0:
        ratio = max(lens) / min(lens)
        test("replay_len_consistent", ratio < 3.0, "lens=%s ratio=%.1f" % (lens, ratio))
    else:
        test("replay_len_consistent", False, "some empty")

    # 状态机路径一致性
    state_paths = []
    for tid in traces:
        if tid:
            td, _ = call_api("/api/traces/%s" % tid)
            evts = td.get("trace", [])
            ss = [e.get("step", "") for e in evts]
            path = [s for s in ss if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
            state_paths.append(tuple(path))

    if state_paths:
        path_consistent = len(set(state_paths)) == 1
        test("replay_path_consistent", path_consistent, "paths=%s" % [list(p) for p in state_paths])

    # Review 判定一致性
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
