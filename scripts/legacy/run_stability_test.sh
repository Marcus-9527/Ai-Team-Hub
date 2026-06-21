#!/bin/bash
# Workflow 稳定性测试 — Shell 版
# 每个测试独立执行，结果存到文件

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/stability_test"
mkdir -p "$OUTDIR"

echo "=== AI Team Hub v2.1 Workflow Stability Test ==="
echo ""

# 预热
echo "Warming up..."
curl -s --max-time 60 -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"warmup","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > /dev/null
sleep 2
echo "Ready."
echo ""

# ── Test 1: DAG Dependency Strictness ──
echo "=== Test 1: DAG Dependency Strictness ==="
curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"Write a REST API for user management","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > "$OUTDIR/test1.json" 2>/dev/null

python3 << 'EOF'
import json
with open("/tmp/stability_test/test1.json") as f:
    d = json.load(f)
print("state:", d.get("state"))
tid = d.get("trace_id", "")
print("trace_id:", tid)
for k, v in d.get("dag_results", {}).items():
    print(f"  [{k}] status={v.get('status')} len={len(v.get('result',''))} cat={v.get('error_category','')}")
EOF

# 验证 trace 顺序
TID=$(python3 -c "import json; print(json.load(open('/tmp/stability_test/test1.json')).get('trace_id',''))" 2>/dev/null)
if [ -n "$TID" ]; then
    curl -s --max-time 15 "$WORKER/api/traces/$TID/replay" -H "User-Agent: Mozilla/5.0" > "$OUTDIR/trace1.json" 2>/dev/null
    python3 << 'EOF'
import json
with open("/tmp/stability_test/trace1.json") as f:
    d = json.load(f)
evts = d.get("trace", [])
steps = [e.get("step", "") for e in evts]
seq = [s for s in steps if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
print("State sequence:", seq)
if "PLAN" in seq and "EXECUTE" in seq:
    print("PLAN before EXECUTE:", seq.index("PLAN") < seq.index("EXECUTE"))
if "EXECUTE" in seq and "REVIEW" in seq:
    print("EXECUTE before REVIEW:", seq.index("EXECUTE") < seq.index("REVIEW"))
print("No skip state:", len(seq) >= 5)
EOF
fi
echo ""

# ── Test 2: State Machine Lock ──
echo "=== Test 2: State Machine Lock ==="
curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -d '{"task":"Design a rate limiter","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > "$OUTDIR/test2.json" 2>/dev/null

TID2=$(python3 -c "import json; print(json.load(open('/tmp/stability_test/test2.json')).get('trace_id',''))" 2>/dev/null)
if [ -n "$TID2" ]; then
    curl -s --max-time 15 "$WORKER/api/traces/$TID2/replay" -H "User-Agent: Mozilla/5.0" > "$OUTDIR/trace2.json" 2>/dev/null
    python3 << 'EOF'
import json
with open("/tmp/stability_test/trace2.json") as f:
    d = json.load(f)
evts = d.get("trace", [])
steps = [e.get("step", "") for e in evts]
seq = [s for s in steps if s in ("INIT", "PLAN", "EXECUTE", "REVIEW", "REPAIR", "DONE")]
expected = ["INIT", "PLAN", "EXECUTE", "REVIEW", "DONE"]
print("State sequence:", seq)
print("Strict order:", seq == expected)
print("No parallel conflict:", len(seq) == len(set(seq)))
print("Final DONE:", seq[-1] == "DONE" if seq else False)
EOF
fi
echo ""

# ── Test 3: Replay Consistency (3 runs) ──
echo "=== Test 3: Replay Consistency (3 runs) ==="
for i in 1 2 3; do
    echo "  Run $i/3..."
    curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d '{"task":"Design a URL shortener service","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' > "$OUTDIR/replay_$i.json" 2>/dev/null
    sleep 0.5
done

python3 << 'EOF'
import json

runs = []
traces = []
for i in range(1, 4):
    with open(f"/tmp/stability_test/replay_{i}.json") as f:
        runs.append(json.load(f))
    traces.append(runs[-1].get("trace_id", ""))

all_done = all(r.get("state") == "DONE" for r in runs)
print("All DONE:", all_done, [r.get("state") for r in runs])

if all_done:
    nids = [sorted(r.get("dag_results", {}).keys()) for r in runs]
    print("Same DAG structure:", all(n == nids[0] for n in nids))
    print("Structures:", nids)

    all_ok = all(all(v.get("status") == "success" for v in r.get("dag_results", {}).values()) for r in runs)
    print("All nodes success:", all_ok)

    lens = [len(r.get("final_result", "")) for r in runs]
    ratio = max(lens) / min(lens) if min(lens) > 0 else 999
    print(f"Length ratio: {ratio:.1f} (lens={lens})")
    print("Length consistent (ratio<5):", ratio < 5.0)

    rps = [r.get("review_result", {}).get("pass") for r in runs]
    print("Review passes:", rps)
    print("Review consistent:", len(set(str(p) for p in rps)) <= 2)
fi
echo ""

# ── Report ──
echo "=== Files saved to $OUTDIR ==="
ls -la "$OUTDIR/"
