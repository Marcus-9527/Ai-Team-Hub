#!/usr/bin/env python3
"""Deploy Worker v2.3"""
import subprocess, os

token = open('/home/liunx/workspace/ai-team-hub/.cf_token').read().strip()
env = {**os.environ, 'CLOUDFLARE_API_TOKEN': token}
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    env.pop(k, None)

os.chdir('/home/liunx/workspace/ai-team-hub')

# First try to find syntax errors by running tsc
print("=== Checking for syntax errors ===")
result = subprocess.run(
    ['npx', 'tsc', '--noEmit', '--skipLibCheck', 'worker/index.ts'],
    capture_output=True, text=True, timeout=30, env=env
)
if result.returncode != 0:
    print("TSC errors:", result.stdout[:1000])
    print("TSC stderr:", result.stderr[:1000])
else:
    print("TSC check passed")

# Deploy
print("\n=== Deploying ===")
result = subprocess.run(
    ['wrangler', 'deploy', 'worker/index.ts'],
    capture_output=True, text=True, timeout=60, env=env
)
print(result.stdout[-500:])
if result.stderr:
    print("STDERR:", result.stderr[-500:])
print("Exit:", result.returncode)
