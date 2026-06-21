#!/bin/bash
# Test models using curl with key from file
KEY=*** .cf_token)

for model in "openrouter/owl-alpha" "openrouter/auto" "google/gemini-2.0-flash" "meta-llama/llama-4-maverick"; do
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
