#!/usr/bin/env python3
import subprocess, os

token = open('/home/liunx/workspace/ai-team-hub/.cf_token').read().strip()
env = {**os.environ, 'CLOUDFLARE_API_TOKEN': token}
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    env.pop(k, None)

os.chdir('/home/liunx/workspace/ai-team-hub')

# Try different deploy approaches
for cmd in [
    ['wrangler', 'deploy', 'worker/index.ts', '--no-build'],
    ['wrangler', 'deploy', 'worker/index.ts', '--format=modules'],
    ['wrangler', 'publish', 'worker/index.ts'],
]:
    print(f"\n=== Trying: {' '.join(cmd)} ===")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    print(result.stdout[-300:])
    if result.stderr:
        print("STDERR:", result.stderr[-200:])
    print("Exit:", result.returncode)
    if result.returncode == 0:
        print("SUCCESS!")
        break
