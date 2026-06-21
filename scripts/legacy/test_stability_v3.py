#!/usr/bin/env python3
"""Workflow 稳定性测试 — 用 subprocess curl 通过 proxy"""
import json, time, subprocess

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print("  [%s] %s: %s %s" % ("OK" if passed else "FAIL", name, status, detail))

def curl_post(path, data=None, timeout=180):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-X", "POST", WORKER + path,
           "-H", "Content-Type: application/json", "-H", "User-Agent: Mozilla/5.0"]
    if data:
        cmd.extend(["-d", json.dumps(data)])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
    if r.returncode != 0:
        return {"error": "timeout"}, 0
    try:
        return json.loads(r.stdout), 200
    except:
        return {"error": "empty", "detail": r.stdout[:100]}, 0

def curl_get(path, timeout=15):
    cmd = ["curl", "-s", "--max-time", str(timeout), WORKER + path, "-H", "User-Agent: Mozilla/5.0"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
    if r.returncode != 0:
        return {"error": "timeout"}, 0
    try:
        return json.loads(r.stdout), 200
    except:
        return {"error": "empty"}, 0

def call_orchestrator(task, intent=""):
    return curl_post("/api/orchestrator/run",
        {"task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha"})

def get_trace(tid):
    d, c = curl_get("/api/traces/%s/replay" % tid)
    if c == 200 and "trace" in d:
        return d
    d2, _ = curl_get("/api/traces/%s" % tid)
    return d2

# ═══════════════════════════════════════════
# Test 1: DAG Dependency Strictness
# ═══════════════════════════════════════════
print("\n=== Test 1: DAG Dependency Strictness ===")
r1, _ = call_orchestrator("Write a REST API for user management", intent="code")
dag1 = r1.get("dag_results", {})
tid1 = r1.get("trace_id", "")

for nid in ["plan", "code", "review"]:
    v = dag1.get(nid, {})
    s = v.get("status", "missing")
    rlen = len(v.get("result", ""))
    test("dag_%s_success" % nid, s == "success", "status=%s" % s)
    test("dag_%s_substantive" % nid, rlen > 100, "len=%d" % rlen)

# 依赖关系
ps = dag1.get("plan", {}).get("status", "missing")
cs = dag1.get("code", {}).get("status", "missing")
test("dep_plan_ok_code_runs", ps == "success" and cs == "success",
     "plan=%s code=%s" % (ps, cs))

# trace 顺序
if tid1:
    td = get_trace(tid1)
    evts = td.get("trace", [])
    if evts:
        steps = [e.get("step", "") for e in evts]
        seq = [s for s in steps if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
        pi = next((i for i, s in enumerate(seq) if s == "PLAN"), -1)
        ei = next((i for i, s in enumerate(seq) if s == "EXECUTE"), -1)
        ri = next((i for i, s in enumerate(seq) if s == "REVIEW"), -1)
        test("plan_before_exec", pi < ei and pi >= 0, "seq=%s" % seq)
        test("exec_before_review", ei < ri and ei >= 0, "seq=%s" % seq)
        test("no_skip_state", len(seq) >= 5, "seq=%s" % seq)
    else:
        test("trace_has_events", False, "no events")
else:
    test("trace_id_exists", False, "no trace_id")

# ═══════════════════════════════════════════
# Test 2: State Machine Lock
# ═══════════════════════════════════════════
print("\n=== Test 2: State Machine Lock ===")
r2, _ = call_orchestrator("Design a rate limiter", intent="code")
tid2 = r2.get("trace_id", "")

if tid2:
    td2 = get_trace(tid2)
    evts2 = td2.get("trace", [])
    if evts2:
        steps2 = [e.get("step", "") for e in evts2]
        seq2 = [s for s in steps2 if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
        expected = ["INIT", "PLAN", "EXECUTE", "REVIEW", "DONE"]
        test("strict_order", seq2 == expected, "actual=%s" % seq2)
        test("no_parallel_conflict", len(seq2) == len(set(seq2)), "states=%s" % seq2)
        test("final_done", seq2[-1] == "DONE", "final=%s" % seq2[-1])
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
    nids = [sorted(r.get("dag_results", {}).keys()) for r in runs]
    test("replay_same_dag_structure", all(n == nids[0] for n in nids), "structs=%s" % nids)

    all_ok = all(all(v.get("status") == "success" for v in r.get("dag_results", {}).values()) for r in runs)
    test("replay_all_nodes_success", all_ok)

    lens = [len(r.get("final_result", "")) for r in runs]
    if min(lens) > 0:
        ratio = max(lens) / min(lens)
        test("replay_len_consistent", ratio < 5.0, "lens=%s ratio=%.1f" % (lens, ratio))
    else:
        test("replay_len_consistent", False, "some empty")

    paths = []
    for tid in traces:
        if tid:
            td = get_trace(tid)
            evts = td.get("trace", [])
            if evts:
                ss = [e.get("step", "") for e in evts]
                path = [s for s in ss if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
                paths.append(tuple(path))
    if paths:
        test("replay_path_consistent", len(set(paths)) == 1, "paths=%s" % [list(p) for p in paths])

    rps = [r.get("review_result", {}).get("pass") for r in runs]
    test("replay_review_consistent", len(set(str(p) for p in rps)) <= 2, "passes=%s" % rps)

# ═══════════════════════════════════════════
# Report
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("WORKFLOW STABILITY TEST REPORT")
print("="*60)

total = len(results)
pc = sum(1 for _, s, _ in results if s == "PASS")
fc = total - pc
print("\n  Total: %d | Passed: %d | Failed: %d | Rate: %.0f%%" % (total, pc, fc, pc/total*100))

if fc > 0:
    print("\n  FAILED:")
    for name, st, det in results:
        if st == "FAIL":
            print("    - %s: %s" % (name, det))

print("\n" + "="*60)
if fc == 0: print("ALL STABILITY TESTS PASSED!")
elif pc/total >= 0.8: print("MOSTLY STABLE")
else: print("STABILITY ISSUES")
print("="*60)
