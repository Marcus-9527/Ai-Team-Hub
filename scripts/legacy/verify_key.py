#!/usr/bin/env python3
"""验证 D1 key — 用 json 格式避免截断"""
import json, subprocess, os

# 用 curl 获取 json 格式
cmd = ["curl", "-s", "https://ai-team-hub.wt5371.workers.dev/api/apikeys", "-H", "User-Agent: Mozilla/5.0"]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
keys = json.loads(r.stdout)
or_key = [k["api_key"] for k in keys if k["provider"] == "openrouter"][0]
print("Key len:", len(or_key))

# 写入文件（避免 shell 截断）
with open("/tmp/or_key.txt", "w") as f:
    f.write(or_key)
print("Key written to /tmp/or_key.txt")

# 测试
cmd2 = ["bash", "-c", "KEY=*** /tmp/or_key.txt); curl -s --max-time 15 -X POST 'https://openrouter.ai/api/v1/chat/completions' -H 'Content-Type: application/json' -H \"Authorization: Bearer *** -H 'User-Agent: Mozilla/5.0' -d '{\"model\":\"openrouter/owl-alpha\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":5,\"stream\":false}' 2>&1 | python3 -c \"import json,sys; d=json.load(sys.stdin); print('OK:', d.get('choices',[{}])[0].get('message',{}).get('content','')[:50]) if 'choices' in d else 'FAIL:', d.get('error',{}).get('message','')[:80])\""]

r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=20)
print(r2.stdout)
