#!/usr/bin/env python3
"""Deploy Worker with correct token"""
import subprocess, os, json

# Read token from file
with open('/home/liunx/workspace/ai-team-hub/.cf_token') as f:
    token = f.read().strip()

env = {**os.environ, 'CLOUDFLARE_API_TOKEN': token}
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    env.pop(k, None)

os.chdir('/home/liunx/workspace/ai-team-hub')
result = subprocess.run(
    ['wrangler', 'deploy', 'worker/index.ts'],
    capture_output=True, text=True, timeout=90, env=env
)
print(result.stdout[-300:])
print(result.stderr[-200:])
print("Exit:", result.returncode)
