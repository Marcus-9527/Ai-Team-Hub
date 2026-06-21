#!/usr/bin/env python3
"""清理 D1 重复 key 并验证"""
import subprocess, os, json

token = open('/home/liunx/workspace/ai-team-hub/.cf_token').read().strip()
env = {**os.environ, 'CLOUDFLARE_API_TOKEN': token}
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    env.pop(k, None)
os.chdir('/home/liunx/workspace/ai-team-hub')

# 删除重复
r = subprocess.run(
    ['wrangler', 'd1', 'execute', 'ai-team-hub-db',
     '--command', "DELETE FROM apikeys WHERE provider='openrouter' AND length(api_key) < 20",
     '--remote'],
    capture_output=True, text=True, timeout=60, env=env)
print("Delete:", r.stdout[:200] if r.returncode == 0 else r.stderr[:200])

# 验证
r2 = subprocess.run(
    ['wrangler', 'd1', 'execute', 'ai-team-hub-db',
     '--command', "SELECT provider, label, length(api_key) as klen FROM apikeys",
     '--remote', '--json'],
    capture_output=True, text=True, timeout=60, env=env)
if r2.returncode == 0:
    data = json.loads(r2.stdout)
    for row in data[0]['results']:
        print(row)
