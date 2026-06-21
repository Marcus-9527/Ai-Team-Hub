#!/bin/bash
# 测试新 key
KEY=*** .cf_token)
echo "Key: ${KEY:0:20}... len=${#KEY}"

curl -s --max-time 15 -X POST "https://openrouter.ai/api/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer *** \
  -H "User-Agent: Mozilla/5.0" \
  -d '{"model":"openrouter/owl-alpha","messages":[{"role":"user","content":"say hi"}],"max_tokens":5,"stream":false}' 2>&1 | python3 -c "
import json,sys
d=json.load(sys.stdin)
if 'choices' in d:
    print('owl-alpha: OK -', d['choices'][0]['message']['content'][:50])
else:
    print('owl-alpha: FAIL -', d.get('error',{}).get('message','')[:80])
"