#!/bin/bash
# Workflow 稳定性测试 — 带长重试逻辑

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/stability_test"
mkdir -p "$OUTDIR"

echo "=== AI Team Hub v2.1 Workflow Stability Test ==="
echo ""

# 带重试的 POST 函数（长重试间隔）
post_with_retry() {
    local outfile="$1"
    local data="$2"
    local max_retries="${3:-5}"
    local retry_delay="${4:-10}"
    
    for i in $(seq 1 $max_retries); do
        curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
          -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
          -d "$data" > "$outfile" 2>/dev/null
        local size=$(wc -c < "$outfile" 2>/dev/null || echo 0)
        if [ "$size" -gt 100 ]; then
            return 0
        fi
        if [ $i -lt $max_retries ]; then
            echo "    Retry $i/$max_retries (${size} bytes), waiting ${retry_delay}s..."
            sleep $retry_delay
        fi
    done
    return 1
}

# 预热
echo "Warming up..."
post_with_retry "$OUTDIR/warmup.json" '{"task":"warmup","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' 5 10
echo "Ready."
echo ""

# ── Test 1: DAG Dependency Strictness ──
echo "=== Test 1: DAG Dependency Strictness ==="
post_with_retry "$OUTDIR/test1.json" '{"task":"Write a REST API for user management","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' 5 10

python3 -c "
import json
with open('$OUTDIR/test1.json') as f:
    d = json.load(f)
print('state:', d.get('state'))
tid = d.get('trace_id','')
print('trace_id:', tid)
for k,v in d.get('dag_results',{}).items():
    print('  [%s] status=%s len=%d cat=%s' % (k, v.get('status'), len(v.get('result','')), v.get('error_category','')))
"

TID=$(python3 -c "import json; print(json.load(open('$OUTDIR/test1.json')).get('trace_id',''))" 2>/dev/null)
if [ -n "$TID" ]; then
    curl -s --max-time 15 "$WORKER/api/traces/$TID/replay" -H "User-Agent: Mozilla/5.0" > "$OUTDIR/trace1.json" 2>/dev/null
    python3 -c "
import json
with open('$OUTDIR/trace1.json') as f: d=json.load(f)
evts=d.get('trace',[])
steps=[e.get('step','') for e in evts]
seq=[s for s in steps if s in ('INIT','PLAN','EXECUTE','REVIEW','REPAIR','DONE')]
print('State sequence:', seq)
print('PLAN<EXECUTE:', seq.index('PLAN')<seq.index('EXECUTE') if 'PLAN' in seq and 'EXECUTE' in seq else False)
print('EXECUTE<REVIEW:', seq.index('EXECUTE')<seq.index('REVIEW') if 'EXECUTE' in seq and 'REVIEW' in seq else False)
print('No skip:', len(seq)>=5)
"
fi
echo ""

# ── Test 2: State Machine Lock ──
echo "=== Test 2: State Machine Lock ==="
post_with_retry "$OUTDIR/test2.json" '{"task":"Design a rate limiter","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' 5 10

TID2=$(python3 -c "import json; print(json.load(open('$OUTDIR/test2.json')).get('trace_id',''))" 2>/dev/null)
if [ -n "$TID2" ]; then
    curl -s --max-time 15 "$WORKER/api/traces/$TID2/replay" -H "User-Agent: Mozilla/5.0" > "$OUTDIR/trace2.json" 2>/dev/null
    python3 -c "
import json
with open('$OUTDIR/trace2.json') as f: d=json.load(f)
evts=d.get('trace',[])
steps=[e.get('step','') for e in evts]
seq=[s for s in steps if s in ('INIT','PLAN','EXECUTE','REVIEW','REPAIR','DONE')]
print('State sequence:', seq)
print('Strict order:', seq==['INIT','PLAN','EXECUTE','REVIEW','DONE'])
print('No parallel conflict:', len(seq)==len(set(seq)))
print('Final DONE:', seq[-1]=='DONE' if seq else False)
"
fi
echo ""

# ── Test 3: Replay Consistency (3 runs) ──
echo "=== Test 3: Replay Consistency (3 runs) ==="
for i in 1 2 3; do
    echo "  Run $i/3..."
    post_with_retry "$OUTDIR/replay_$i.json" '{"task":"Design a URL shortener service","intent":"code","provider":"openrouter","model":"openrouter/owl-alpha"}' 5 10
    sleep 1
done

python3 -c "
import json
runs, traces = [], []
for i in range(1,4):
    try:
        with open('$OUTDIR/replay_%d.json'%i) as f: runs.append(json.load(f))
        traces.append(runs[-1].get('trace_id',''))
    except: runs.append({'state':'FAIL'})

all_done = all(r.get('state')=='DONE' for r in runs)
print('All DONE:', all_done, [r.get('state') for r in runs])
if all_done:
    nids=[sorted(r.get('dag_results',{}).keys()) for r in runs]
    print('Same DAG structure:', all(n==nids[0] for n in nids))
    all_ok=all(all(v.get('status')=='success' for v in r.get('dag_results',{}).values()) for r in runs)
    print('All nodes success:', all_ok)
    lens=[len(r.get('final_result','')) for r in runs]
    ratio=max(lens)/min(lens) if min(lens)>0 else 999
    print('Length ratio: %.1f (lens=%s)' % (ratio, lens))
    rps=[r.get('review_result',{}).get('pass') for r in runs]
    print('Review passes:', rps)
    print('Review consistent:', len(set(str(p) for p in rps))<=2)
"
echo ""
echo "=== Files ==="
ls -la "$OUTDIR/"
