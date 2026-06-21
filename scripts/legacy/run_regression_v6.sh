#!/bin/bash
# 回归测试 — 用 curl 的 -o 参数写文件，避免 shell 变量问题

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/regression_v6"
mkdir -p "$OUTDIR"

echo "=== REGRESSION TEST ==="

# 预热
echo "Warming up..."
curl -s --max-time 120 -o "$OUTDIR/warmup.json" -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"warmup","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}'
echo "Done."

run_task() {
    local id="$1" task="$2" intent="${3:-code}"
    echo "  $id: ${task:0:50}..."
    curl -s --max-time 300 -o "$OUTDIR/${id}.json" -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$task\",\"intent\":\"$intent\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}"
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
run_task "c1" "Design a recommendation system" "complex"
run_task "c2" "Build a distributed message queue" "complex"
run_task "c3" "Create a multi-agent decision system" "complex"

echo ""
echo "All tasks dispatched. Results in $OUTDIR/"
