#!/usr/bin/env python3
"""Test OpenRouter key using base64 file"""
import json, subprocess, os, base64

# Read base64 key from file
with open("/tmp/or_key_b64.txt") as f:
    b64 = f.read().strip()
or_key = base64.b64decode(b64).decode()
print("Key len:", len(or_key))

# Write decoded key to temp file
with open("/tmp/_or_key.txt", "w") as f:
    f.write(or_key)

# Test owl-alpha
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
