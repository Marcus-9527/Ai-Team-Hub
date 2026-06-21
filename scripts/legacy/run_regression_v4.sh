#!/bin/bash
# 回归测试 — 纯 curl 版，结果存文件

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/regression"
mkdir -p "$OUTDIR"

echo "=== REGRESSION TEST ==="

# 预热
echo "Warming up..."
curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"warmup","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > /dev/null
echo "Ready."

# 运行任务
run_task() {
    local id="$1" task="$2" intent="${3:-code}"
    echo "  $id: $task..."
    curl -s --max-time 300 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$OUTDIR/${id}.json" 2>/dev/null
    local sz=$(wc -c < "$OUTDIR/${id}.json" 2>/dev/null || echo 0)
    echo "    -> ${sz} bytes"
}

echo ""
echo "--- SIMPLE ---"
run_task "s1" "Write a hello world in Python" "code"
run_task "s2" "Create a function to add two numbers" "code"
run_task "s3" "Design a user login API endpoint" "code"

echo ""
echo "--- MEDIUM ---"
run_task "m1" "Design a caching system with Redis" "code"
run_task "m2" "Build a rate limiter with sliding window" "code"
run_task "m3" "Create a task queue with priority scheduling" "code"

echo ""
echo "--- COMPLEX ---"
run_task "c1" "Design a recommendation system: research, implement, evaluate, optimize" "complex"
run_task "c2" "Build a distributed message queue with at-least-once delivery" "complex"
run_task "c3" "Create a multi-agent decision system: plan, execute, critique, redesign" "complex"

echo ""
echo "=== ANALYSIS ==="
python3 << 'PYEOF'
import json, os, glob

files = sorted(glob.glob("/tmp/regression/*.json"))
results = []
for f in files:
    name = os.path.basename(f).replace(".json","")
    try:
        with open(f) as fh: d = json.load(fh)
        state = d.get("state","ERROR")
        dag = d.get("dag_results",{})
        review = d.get("review_result",{})
        fr = d.get("final_result","")
        nodes_ok = sum(1 for v in dag.values() if v.get("status")=="success")
        has_review = bool(review) and "pass" in review
        has_output = len(fr) > 50
        results.append({"name":name,"state":state,"nodes":f"{nodes_ok}/{len(dag)}",
                        "review":has_review,"output":has_output,
                        "pass":state=="DONE" and nodes_ok>=2 and has_output})
    except:
        results.append({"name":name,"state":"PARSE_ERR","pass":False})

print(f"\n{'Name':<6} {'State':<8} {'Nodes':<8} {'Review':<6} {'Output':<6} {'Pass':<6}")
print("-"*48)
for r in results:
    print(f"{r['name']:<6} {r.get('state','?'):<8} {r.get('nodes','?'):<8} "
          f"{'Y' if r['review'] else 'N':<6} {'Y' if r['output'] else 'N':<6} "
          f"{'PASS' if r['pass'] else 'FAIL':<6}")

total=len(results); passed=sum(1 for r in results if r["pass"])
print(f"\nTotal: {total} | Passed: {passed} | Failed: {total-passed} | Rate: {passed/total*100:.0f}%")
for p in ["s","m","c"]:
    cat=[r for r in results if r["name"].startswith(p)]; cp=sum(1 for r in cat if r["pass"]); ct=len(cat)
    if ct>0: print(f"  {p}: {cp}/{ct} ({cp/ct*100:.0f}%)")
PYEOF
