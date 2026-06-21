#!/bin/bash
# 回归测试 — 长超时版

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/regression"
mkdir -p "$OUTDIR"

echo "=== REGRESSION TEST ==="
echo ""

# 预热
echo "Warming up..."
curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"warmup","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > /dev/null
echo "Ready."
echo ""

run_task() {
    local id="$1"
    local task="$2"
    local intent="${3:-code}"
    local outfile="$OUTDIR/${id}.json"
    
    echo "  Running: $task..."
    curl -s --max-time 300 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$outfile" 2>/dev/null
    
    local size=$(wc -c < "$outfile" 2>/dev/null || echo 0)
    if [ "$size" -gt 100 ]; then
        echo "    OK (${size} bytes)"
        return 0
    fi
    
    # 重试 1
    echo "    Retry 1/2 (${size} bytes), waiting 15s..."
    sleep 15
    curl -s --max-time 300 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$outfile" 2>/dev/null
    size=$(wc -c < "$outfile" 2>/dev/null || echo 0)
    if [ "$size" -gt 100 ]; then
        echo "    OK on retry 1 (${size} bytes)"
        return 0
    fi
    
    # 重试 2
    echo "    Retry 2/2 (${size} bytes), waiting 15s..."
    sleep 15
    curl -s --max-time 300 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$outfile" 2>/dev/null
    size=$(wc -c < "$outfile" 2>/dev/null || echo 0)
    if [ "$size" -gt 100 ]; then
        echo "    OK on retry 2 (${size} bytes)"
        return 0
    fi
    
    echo "    FAIL (empty after 2 retries)"
    return 1
}

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

# 分析
python3 << 'PYEOF'
import json, os, glob

outdir = "/tmp/regression"
files = sorted(glob.glob(f"{outdir}/*.json"))
results = []

for f in files:
    name = os.path.basename(f).replace(".json", "")
    try:
        with open(f) as fh:
            d = json.load(fh)
        state = d.get("state", "ERROR")
        dag = d.get("dag_results", {})
        review = d.get("review_result", {})
        fr = d.get("final_result", "")
        nodes_ok = sum(1 for v in dag.values() if v.get("status") == "success")
        has_review = bool(review) and "pass" in review
        has_output = len(fr) > 50
        results.append({"name": name, "state": state, "nodes": f"{nodes_ok}/{len(dag)}",
                        "has_review": has_review, "has_output": has_output,
                        "pass": state == "DONE" and nodes_ok >= 2 and has_output})
    except:
        results.append({"name": name, "state": "PARSE_ERR", "pass": False})

print(f"\n{'Name':<8} {'State':<8} {'Nodes':<8} {'Review':<8} {'Output':<8} {'Pass':<6}")
print("-" * 50)
for r in results:
    print(f"{r['name']:<8} {r.get('state','?'):<8} {r.get('nodes','?'):<8} "
          f"{'Y' if r.get('has_review') else 'N':<8} {'Y' if r.get('has_output') else 'N':<8} "
          f"{'PASS' if r['pass'] else 'FAIL':<6}")

total = len(results)
passed = sum(1 for r in results if r["pass"])
print(f"\nTotal: {total} | Passed: {passed} | Failed: {total-passed} | Rate: {passed/total*100:.0f}%")

for p in ["s", "m", "c"]:
    cat = [r for r in results if r["name"].startswith(p)]
    cp = sum(1 for r in cat if r["pass"])
    ct = len(cat)
    if ct > 0:
        print(f"  {p}: {cp}/{ct} ({cp/ct*100:.0f}%)")
PYEOF
