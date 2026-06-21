#!/usr/bin/env python3
"""Test new OpenRouter key via subprocess"""
import json, subprocess, os

# Read key from b64 file
with open('/home/liunx/workspace/ai-team-hub/.or_key_b64') as f:
    b64 = f.read().strip()
key = __import__('base64').b64decode(b64).decode('utf-8', errors='replace')
print("Key len:", len(key))

# Use subprocess with env to pass the key
env = os.environ.copy()
env['OR_KEY'] = key

cmd = ["bash", "-c", 
       'curl -s --max-time 15 -X POST "https://openrouter.ai/api/v1/chat/completions" '
       '-H "Content-Type: application/json" '
       '-H "Authorization: Bearer $OR_KEY" '
       '-H "User-Agent: Mozilla/5.0" '
       '-d \'{"model":"openrouter/owl-alpha","messages":[{"role":"user","content":"say hi"}],"max_tokens":5,"stream":false}\'']

r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
try:
    d = json.loads(r.stdout)
    if "choices" in d:
        print("owl-alpha: OK -", d["choices"][0]["message"]["content"][:50])
    else:
        print("owl-alpha: FAIL -", d.get("error",{}).get("message","")[:80])
except:
    print("PARSE_ERR:", r.stdout[:100])
