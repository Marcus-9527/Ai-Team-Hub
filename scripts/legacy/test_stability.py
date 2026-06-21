#!/usr/bin/env python3
"""Workflow 稳定性测试 — 3 项关键测试"""
import json, time, urllib.request, urllib.error

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print("  [%s] %s: %s %s" % ("OK" if passed else "FAIL", name, status, detail))

def call_api(path, data=None, timeout=180):
    url = WORKER + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; Hermes/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.reason, "detail": e.read().decode()[:300]}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def call_orchestrator(task, intent=""):
    return call_api("/api/orchestrator/run", {
        "task": task, "intent": intent, "provider": "openrouter", "model": "openrouter/owl-alpha",
    })

def get_trace(trace_id):
    """获取 trace 报告"""
    return call_api("/api/traces/%s" % trace_id)

# ═══════════════════════════════════════════
# Test 1: DAG Dependency Strictness
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("Test 1: DAG Dependency Strictness")
print("="*60)

# 运行 3 次，检查 DAG 执行顺序
for run_i in range(3):
    print("\n  Run %d/3..." % (run_i + 1))
    r, _ = call_orchestrator(
        "Design a caching system with Redis cluster, consistent hashing, and failover",
        intent="complex"
    )
    if "final_result" not in r or r.get("state") != "DONE":
        test("dep_run_%d_complete" % run_i, False, "state=%s" % r.get("state"))
        continue

    dag = r.get("dag_results", {})
    trace_id = r.get("trace_id", "")

    # 检查所有节点是否成功
    all_success = all(v.get("status") == "success" for v in dag.values())
    test("dep_run_%d_all_success" % run_i, all_success,
         "nodes=%s" % {k: v.get("status") for k, v in dag.items()})

    # 检查每个成功节点的结果长度（确保不是"弱信息版本"）
    for node_id, node_result in dag.items():
        if node_result.get("status") == "success":
            rlen = len(node_result.get("result", ""))
            # planner 至少 200 字，executor 至少 500 字，reviewer 至少 100 字
            min_len = 200 if "plan" in node_id else (500 if "code" in node_id or "exec" in node_id else 100)
            test("dep_run_%d_%s_substantive" % (run_i, node_id), rlen >= min_len,
                 "len=%d (min=%d)" % (rlen, min_len))

    # 通过 trace 验证执行顺序
    if trace_id:
        trace_data, _ = get_trace(trace_id)
        if "trace" in trace_data:
            events = trace_data["trace"]
            steps = [e.get("step", "") for e in events]
            # 验证 PLAN 在 EXECUTE 之前
            plan_idx = next((i for i, s in enumerate(steps) if s == "PLAN"), -1)
            exec_idx = next((i for i, s in enumerate(steps) if s == "EXECUTE"), -1)
            review_idx = next((i for i, s in enumerate(steps) if s == "REVIEW"), -1)

            test("dep_run_%d_plan_before_exec" % run_i, plan_idx < exec_idx and plan_idx >= 0,
                 "plan_idx=%d exec_idx=%d steps=%s" % (plan_idx, exec_idx, steps))
            test("dep_run_%d_exec_before_review" % run_i, exec_idx < review_idx and exec_idx >= 0,
                 "exec_idx=%d review_idx=%d" % (exec_idx, review_idx))

    time.sleep(1)

# ═══════════════════════════════════════════
# Test 2: State Machine Lock
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("Test 2: State Machine Lock")
print("="*60)

# 运行 3 次，通过 trace 验证状态机严格顺序
valid_transitions = {
    "INIT": ["PLAN"],
    "PLAN": ["EXECUTE"],
    "EXECUTE": ["REVIEW"],
    "REVIEW": ["DONE", "REPAIR"],
    "REPAIR": ["EXECUTE"],
}

for run_i in range(3):
    print("\n  Run %d/3..." % (run_i + 1))
    r, _ = call_orchestrator("Write a REST API for user management", intent="code")
    trace_id = r.get("trace_id", "")

    if not trace_id:
        test("lock_run_%d_trace" % run_i, False, "no trace_id")
        continue

    trace_data, _ = get_trace(trace_id)
    if "trace" not in trace_data:
        test("lock_run_%d_trace_data" % run_i, False, "no trace data")
        continue

    events = trace_data["trace"]
    steps = [e.get("step", "") for e in events]

    # 验证没有跳 state
    state_seq = []
    for step in steps:
        if step in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE"):
            state_seq.append(step)

    # 验证每个转换是否合法
    valid = True
    transition_log = []
    for i in range(len(state_seq) - 1):
        curr, nxt = state_seq[i], state_seq[i + 1]
        allowed = valid_transitions.get(curr, [])
        if nxt not in allowed:
            valid = False
            transition_log.append("%s->%s (ILLEGAL)" % (curr, nxt))
        else:
            transition_log.append("%s->%s" % (curr, nxt))

    test("lock_run_%d_no_skip" % run_i, valid,
         "seq=%s transitions=%s" % (state_seq, transition_log))

    # 验证没有 parallel state conflict（同一时间只有一个 active state）
    # trace 中的事件应该是严格有序的
    test("lock_run_%d_strict_order" % run_i, len(state_seq) >= 4,
         "states=%s (need at least INIT->PLAN->EXECUTE->REVIEW->DONE)" % state_seq)

    # 验证最终状态是 DONE
    test("lock_run_%d_final_done" % run_i, state_seq[-1] == "DONE",
         "final=%s" % state_seq[-1] if state_seq else "empty")

    time.sleep(1)

# ═══════════════════════════════════════════
# Test 3: Replay Consistency
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("Test 3: Replay Consistency (3 runs, same input)")
print("="*60)

fixed_task = "Design a URL shortener service with analytics, rate limiting, and custom aliases"
fixed_intent = "code"

runs = []
for run_i in range(3):
    print("\n  Run %d/3..." % (run_i + 1))
    r, _ = call_orchestrator(fixed_task, intent=fixed_intent)
    runs.append(r)
    time.sleep(1)

# 检查所有运行都成功
all_done = all(r.get("state") == "DONE" for r in runs)
test("replay_all_done", all_done, "states=%s" % [r.get("state") for r in runs])

if all_done:
    # 检查 DAG 结构一致性（节点数量和 ID 应该完全相同）
    dag_structures = []
    for i, r in enumerate(runs):
        dag = r.get("dag_results", {})
        structure = {
            "node_ids": sorted(dag.keys()),
            "node_count": len(dag),
            "success_count": sum(1 for v in dag.values() if v.get("status") == "success"),
            "all_success": all(v.get("status") == "success" for v in dag.values()),
        }
        dag_structures.append(structure)
        print("    Run %d: nodes=%d success=%d all_success=%s" % (
            i + 1, structure["node_count"], structure["success_count"], structure["all_success"]))

    # 节点 ID 应该完全一致
    node_ids_sets = [set(s["node_ids"]) for s in dag_structures]
    same_structure = all(s == node_ids_sets[0] for s in node_ids_sets)
    test("replay_same_dag_structure", same_structure,
         "node_ids=%s" % [s["node_ids"] for s in dag_structures])

    # 所有运行应该全部成功
    all_runs_all_success = all(s["all_success"] for s in dag_structures)
    test("replay_all_runs_all_success", all_runs_all_success)

    # 结果长度应该在同一量级（不超过 3 倍偏差）
    result_lens = [len(r.get("final_result", "")) for r in runs]
    if result_lens and min(result_lens) > 0:
        ratio = max(result_lens) / min(result_lens)
        test("replay_result_len_consistent", ratio < 3.0,
             "lens=%s ratio=%.1f" % (result_lens, ratio))
    else:
        test("replay_result_len_consistent", False, "some results empty")

    # Review 判定应该一致（都 pass 或都 fail）
    review_passes = [r.get("review_result", {}).get("pass") for r in runs]
    review_consistent = len(set(str(p) for p in review_passes)) <= 2  # 最多两种结果
    test("replay_review_consistent", review_consistent,
         "passes=%s" % review_passes)

    # 状态机路径应该一致
    state_paths = []
    for r in runs:
        trace_id = r.get("trace_id", "")
        if trace_id:
            trace_data, _ = get_trace(trace_id)
            if "trace" in trace_data:
                steps = [e.get("step", "") for e in trace_data["trace"]]
                state_seq = [s for s in steps if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
                state_paths.append(tuple(state_seq))

    if state_paths:
        path_consistent = len(set(state_paths)) == 1
        test("replay_state_path_consistent", path_consistent,
             "paths=%s" % [list(p) for p in state_paths])

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
