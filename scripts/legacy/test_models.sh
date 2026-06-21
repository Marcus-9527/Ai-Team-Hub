#!/bin/bash
# 测试 OpenRouter 免费模型

WORKER="https://ai-team-hub.wt5371.workers.dev"

# 获取 key
OR_KEY=$(curl -s "$WORKER/api/apikeys" | python3 -c "import json,sys; d=json.load(sys.stdin); print([k['api_key'] for k in d if k['provider']=='openrouter'][0])")

echo "Testing models with key: ${OR_KEY:0:20}..."
echo ""

for model in "openrouter/auto" "google/gemini-2.0-flash" "meta-llama/llama-4-maverick" "openrouter/owl-alpha" "qwen/qwen3-235b" "mistralai/mistral-7b-instruct"; do
    RESP=$(curl -s --max-time 15 -X POST "https://openrouter.ai/api/v1/chat/completions" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $OR_KEY" \
      -H "User-Agent: Mozilla/5.0" \
      -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":5,\"stream\":false}" 2>&1)
    
    # 检查是否有 error
    if echo "$RESP" | grep -q '"error"'; then
        ERR=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error',{}).get('message','')[:80])" 2>/dev/null)
        echo "$model: FAIL - $ERR"
    else
        CONTENT=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('choices',[{}])[0].get('message',{}).get('content','')[:50])" 2>/dev/null)
        echo "$model: OK - $CONTENT"
    fi
done
