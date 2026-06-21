#!/usr/bin/env python3
"""Test OpenRouter key - write key to file using Python, then test"""
import json, subprocess, os

# 新 key（用户提供）- 直接写在 Python 脚本里避免 shell glob
or_key = "sk-or-...15c2"

# 写入文件
with open("/tmp/_or_key.txt", "w") as f:
    f.write(or_key)

print("Key len:", len(or_key))

# 测试 owl-alpha
cmd = ["bash", "-c",
       "KEY=*** /tmp/_or_key.txt); "
       "curl -s --max-time 15 -X POST 'https://openrouter.ai/api/v1/chat/completions' "
       "-H 'Content-Type: application/json' "
       "-H \"Authorization: Bearer *** "
       "-H 'User-Agent: Mozilla/5.0' "
       "-d '{\"model\":\"openrouter/owl-alpha\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":5,\"stream\":false}' "
       "2>&1 | python3 -c \"import json,sys; d=json.load(sys.stdin); "
       "print('OK:', d.get('choices',[{}])[0].get('message',{}).get('content','')[:50]) "
       "if 'choices' in d else 'FAIL:', d.get('error',{}).get('message','')[:80])\""]

r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
print(r.stdout.strip())
