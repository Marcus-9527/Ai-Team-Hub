#!/usr/bin/env python3
"""Debug proxy header stripping"""
import json, subprocess, os

# Read key
with open('/home/liunx/workspace/ai-team-hub/.or_key_b64') as f:
    b64 = f.read().strip()
key = __import__('base64').b64decode(b64).decode('utf-8', errors='replace')
print("Key len:", len(key))

# Test 1: 直接 curl（走 proxy）
env = os.environ.copy()
env['OR_KEY'] = key

cmd = ["bash", "-c",
       'curl -s --max-time 15 -X POST "https://httpbin.org/headers" '
       '-H "Authorization: Bearer ${OR_KEY}" '
       '-H "User-Agent: Mozilla/5.0"']

r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
print("Test 1 (httpbin):", r.stdout[:500])

# Test 2: curl with --noproxy
cmd2 = ["bash", "-c",
        'curl -s --noproxy "*" --max-time 5 -X POST "https://httpbin.org/headers" '
        '-H "Authorization: Bearer ${OR_KEY}" '
        '-H "User-Agent: Mozilla/5.0"']

r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10, env=env)
print("Test 2 (noproxy):", r2.stdout[:500])
