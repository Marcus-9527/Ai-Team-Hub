#!/bin/bash
# 回归测试 — 只跑复杂任务

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/regression_v5"
mkdir -p "$OUTDIR"

echo "=== COMPLEX TASKS ==="

# 预热
echo "Warming up..."
curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"warmup","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > /dev/null
echo "Ready."

run_task() {
    local id="$1" task="$2" intent="${3:-complex}"
    echo "  $id: $task..."
    curl -s --max-time 600 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$OUTDIR/${id}.json" 2>/dev/null
    local sz=$(wc -c < "$OUTDIR/${id}.json" 2>/dev/null || echo 0)
    echo "    -> ${sz} bytes"
}

run_task "c1" "Design a recommendation system: research, implement, evaluate, optimize" "complex"
run_task "c2" "Build a distributed message queue with at-least-once delivery" "complex"
run_task "c3" "Create a multi-agent decision system: plan, execute, critique, redesign" "complex"

echo ""
echo "=== FULL ANALYSIS ==="
python3 << 'PYEOF'
import json, os, glob

# 合并所有结果
all_results = {}
for d in ["/tmp/regression", "/tmp/regression_v5"]:
    for f in sorted(glob.glob(f"{d}/*.json")):
        name = os.path.basename(f).replace(".json","")
        if name in ["warmup"]: continue
        try:
            with open(f) as fh: data = json.load(fh)
            state = data.get("state","ERROR")
            dag = data.get("dag_results",{})
            review = data.get("review_result",{})
            fr = data.get("final_result","")
            nodes_ok = sum(1 for v in dag.values() if v.get("status")=="success")
            has_review = bool(review) and "pass" in review
            has_output = len(fr) > 50
            all_results[name] = {"state":state,"nodes":f"{nodes_ok}/{len(dag)}",
                                 "review":has_review,"output":has_output,
                                 "pass":state=="DONE" and nodes_ok>=2 and has_output}
        except:
            all_results[name] = {"state":"PARSE_ERR","pass":False}

order = ["s1","s2","s3","m1","m2","m3","c1","c2","c3"]
print(f"\n{'Name':<6} {'State':<8} {'Nodes':<8} {'Review':<6} {'Output':<6} {'Pass':<6}")
print("-"*48)
for name in order:
    r = all_results.get(name, {"state":"?","pass":False})
    print(f"{name:<6} {r.get('state','?'):<8} {r.get('nodes','?'):<8} "
          f"{'Y' if r.get('review') else 'N':<6} {'Y' if r.get('output') else 'N':<6} "
          f"{'PASS' if r.get('pass') else 'FAIL':<6}")

total = len([n for n in order if n in all_results])
passed = sum(1 for n in order if all_results.get(n,{}).get("pass"))
failed = total - passed
print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed} | Rate: {passed/total*100:.0f}%")
for p in ["s","m","c"]:
    cat = [n for n in order if n.startswith(p) and n in all_results]
    cp = sum(1 for n in cat if all_results[n].get("pass"))
    ct = len(cat)
    if ct > 0: print(f"  {p}: {cp}/{ct} ({cp/ct*100:.0f}%)")
PYEOF
