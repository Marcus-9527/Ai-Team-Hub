#!/usr/bin/env python3
import subprocess, os

token = open('/home/liunx/workspace/ai-team-hub/.cf_token').read().strip()
env = {**os.environ, 'CLOUDFLARE_API_TOKEN': token}
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    env.pop(k, None)

os.chdir('/home/liunx/workspace/ai-team-hub')
result = subprocess.run(
    ['wrangler', 'deploy', 'worker/index.ts'],
    capture_output=True, text=True, timeout=60, env=env
)
print(result.stdout[-500:])
print(result.stderr[-500:])
print("Exit:", result.returncode)
