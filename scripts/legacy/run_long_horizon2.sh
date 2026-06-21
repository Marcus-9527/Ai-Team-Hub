#!/bin/bash
# 长链路稳定测试 — 20 轮，快速版

WORKER="https://ai-team-hub.wt5371.workers.dev"
OUTDIR="/tmp/long_horizon2"
mkdir -p "$OUTDIR"

echo "=== LONG HORIZON TEST (20 rounds, fast) ==="

PASS=0; FAIL=0; CONSEC=0; MAX_CONSEC=0

for i in $(seq 1 20); do
    TASK="Round $i: Write a simple Python function"
    
    # 第一次尝试
    curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
      -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
      -d "{\"task\":\"$TASK\",\"intent\":\"code\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$OUTDIR/r_$i.json" 2>/dev/null
    SZ=$(wc -c < "$OUTDIR/r_$i.json" 2>/dev/null || echo 0)
    
    # 如果空响应，重试一次
    if [ "$SZ" -le 100 ]; then
        sleep 3
        curl -s --max-time 120 -X POST "$WORKER/api/orchestrator/run" \
          -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
          -d "{\"task\":\"$TASK\",\"intent\":\"code\",\"provider\":\"openrouter\",\"model\":\"openrouter/owl-alpha\"}" > "$OUTDIR/r_$i.json" 2>/dev/null
        SZ=$(wc -c < "$OUTDIR/r_$i.json" 2>/dev/null || echo 0)
    fi
    
    if [ "$SZ" -gt 100 ]; then
        ST=$(python3 -c "import json; print(json.load(open('$OUTDIR/r_$i.json')).get('state','ERROR'))" 2>/dev/null)
        if [ "$ST" = "DONE" ]; then
            PASS=$((PASS+1))
            CONSEC=0
        else
            FAIL=$((FAIL+1))
            CONSEC=$((CONSEC+1))
        fi
    else
        FAIL=$((FAIL+1))
        CONSEC=$((CONSEC+1))
        ST="EMPTY"
    fi
    
    [ $CONSEC -gt $MAX_CONSEC ] && MAX_CONSEC=$CONSEC
    printf "  R%02d: %-8s %5dB  P=%d F=%d C=%d\n" $i "$ST" $SZ $PASS $FAIL $CONSEC
    
    [ $CONSEC -ge 5 ] && echo "STOPPED: 5 consecutive fails" && break
    sleep 1
done

echo ""
TOTAL=$((PASS+FAIL))
echo "Passed: $PASS | Failed: $FAIL | Rate: $((PASS*100/TOTAL))% | MaxConsec: $MAX_CONSEC"
[ $PASS -ge 16 ] && echo "RESULT: PASS" || { [ $PASS -ge 12 ] && echo "RESULT: MOSTLY STABLE" || echo "RESULT: UNSTABLE"; }
