#!/bin/bash
# 测试模型
KEY=$(curl -s https://ai-team-hub.wt5371.workers.dev/api/apikeys | python3 -c "import json,sys; d=json.load(sys.stdin); print([k['api_key'] for k in d if k['provider']=='openrouter'][0])")

for model in "openrouter/auto" "google/gemini-2.0-flash" "meta-llama/llama-4-maverick" "openrouter/owl-alpha" "qwen/qwen3-235b"; do
    RESP=$(curl -s --max-time 15 -X POST "https://openrouter.ai/api/v1/chat/completions" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer *** \
      -H "User-Agent: Mozilla/5.0" \
      -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":5,\"stream\":false}" 2>&1)
    
    if echo "$RESP" | grep -q '"choices"'; then
        CONTENT=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('choices',[{}])[0].get('message',{}).get('content','')[:50])" 2>/dev/null)
        echo "$model: OK - $CONTENT"
    else
        ERR=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error',{}).get('message','')[:80])" 2>/dev/null)
        echo "$model: FAIL - $ERR"
    fi
done
