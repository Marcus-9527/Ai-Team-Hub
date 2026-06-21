#!/usr/bin/env python3
import subprocess, os

token = open('/home/liunx/workspace/ai-team-hub/.cf_token').read().strip()
env = {**os.environ, 'CLOUDFLARE_API_TOKEN': token}
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    env.pop(k, None)

os.chdir('/home/liunx/workspace/ai-team-hub')

# Update wrangler.toml to point to .js
with open('wrangler.toml', 'r') as f:
    config = f.read()
config = config.replace('main = "worker/index.ts"', 'main = "worker/index.js"')
with open('wrangler.toml', 'w') as f:
    f.write(config)

# Deploy
result = subprocess.run(
    ['wrangler', 'deploy', 'worker/index.js'],
    capture_output=True, text=True, timeout=60, env=env
)
print(result.stdout[-500:])
if result.stderr:
    print("STDERR:", result.stderr[-300:])
print("Exit:", result.returncode)

# Restore wrangler.toml
config = config.replace('main = "worker/index.js"', 'main = "worker/index.ts"')
with open('wrangler.toml', 'w') as f:
    f.write(config)
