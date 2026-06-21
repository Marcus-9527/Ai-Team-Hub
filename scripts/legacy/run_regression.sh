#!/bin/bash
# 回归测试 — Shell 版
# 9 个任务分步执行，结果存到文件

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/regression"
mkdir -p "$OUTDIR"

echo "=== REGRESSION TEST ==="
echo ""

# 预热
echo "Warming up..."
curl -s --max-time 60 -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"warmup","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > /dev/null
echo "Ready."
echo ""

# 运行单个任务
run_task() {
    local id="$1"
    local task="$2"
    local intent="${3:-code}"
    local outfile="$OUTDIR/${id}.json"
    
    echo "  Running: $task..."
    curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$outfile" 2>/dev/null
    
    local size=$(wc -c < "$outfile" 2>/dev/null || echo 0)
    if [ "$size" -gt 100 ]; then
        echo "    OK (${size} bytes)"
        return 0
    else
        echo "    EMPTY (${size} bytes), retrying in 5s..."
        sleep 5
        curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
          -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
          -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$outfile" 2>/dev/null
        size=$(wc -c < "$outfile" 2>/dev/null || echo 0)
        if [ "$size" -gt 100 ]; then
            echo "    OK on retry (${size} bytes)"
            return 0
        else
            echo "    FAIL (empty after retry)"
            return 1
        fi
    fi
}

# ── Simple ──
echo "--- SIMPLE ---"
run_task "s1" "Write a hello world in Python" "code"
run_task "s2" "Create a function to add two numbers" "code"
run_task "s3" "Design a user login API endpoint" "code"
echo ""

# ── Medium ──
echo "--- MEDIUM ---"
run_task "m1" "Design a caching system with Redis" "code"
run_task "m2" "Build a rate limiter with sliding window" "code"
run_task "m3" "Create a task queue with priority scheduling" "code"
echo ""

# ── Complex ──
echo "--- COMPLEX ---"
run_task "c1" "Design a recommendation system: research, implement, evaluate, optimize" "complex"
run_task "c2" "Build a distributed message queue with at-least-once delivery" "complex"
run_task "c3" "Create a multi-agent decision system: plan, execute, critique, redesign" "complex"
echo ""

# ── 分析结果 ──
echo "=== ANALYSIS ==="
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
        tid = d.get("trace_id", "")
        review = d.get("review_result", {})
        fr = d.get("final_result", "")
        
        nodes_ok = sum(1 for v in dag.values() if v.get("status") == "success")
        nodes_total = len(dag)
        has_review = bool(review) and "pass" in review
        has_output = len(fr) > 50
        
        results.append({
            "name": name,
            "state": state,
            "nodes": f"{nodes_ok}/{nodes_total}",
            "has_review": has_review,
            "has_output": has_output,
            "trace_id": tid,
            "pass": state == "DONE" and nodes_ok >= 2 and has_output,
        })
    except Exception as e:
        results.append({"name": name, "state": "PARSE_ERROR", "pass": False, "error": str(e)})

print(f"\n{'Name':<8} {'State':<8} {'Nodes':<8} {'Review':<8} {'Output':<8} {'Pass':<6}")
print("-" * 50)
for r in results:
    print(f"{r['name']:<8} {r.get('state','?'):<8} {r.get('nodes','?'):<8} "
          f"{'Y' if r.get('has_review') else 'N':<8} {'Y' if r.get('has_output') else 'N':<8} "
          f"{'PASS' if r['pass'] else 'FAIL':<6}")

total = len(results)
passed = sum(1 for r in results if r["pass"])
failed = total - passed
print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed} | Rate: {passed/total*100:.0f}%")

# 按类别统计
for prefix in ["s", "m", "c"]:
    cat = [r for r in results if r["name"].startswith(prefix)]
    cp = sum(1 for r in cat if r["pass"])
    ct = len(cat)
    label = {"s": "Simple", "m": "Medium", "c": "Complex"}[prefix]
    if ct > 0:
        print(f"  {label}: {cp}/{ct} ({cp/ct*100:.0f}%)")

# 检查失败项
failed_items = [r for r in results if not r["pass"]]
if failed_items:
    print(f"\nFailed items:")
    for r in failed_items:
        print(f"  - {r['name']}: state={r.get('state','?')} nodes={r.get('nodes','?')}")
PYEOF
