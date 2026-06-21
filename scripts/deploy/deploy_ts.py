#!/usr/bin/env python3
"""Deploy .ts directly, letting Cloudflare handle TypeScript"""
import subprocess, os

token = open('/home/liunx/workspace/ai-team-hub/.cf_token').read().strip()
env = {**os.environ, 'CLOUDFLARE_API_TOKEN': token}
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    env.pop(k, None)

os.chdir('/home/liunx/workspace/ai-team-hub')

# First, restore the .ts file from the last known good state
# The .ts file has proper TypeScript syntax - wrangler should handle it
# The issue is that our patches broke the syntax

# Let's check if the .ts file has valid syntax
with open('worker/index.ts', 'r') as f:
    ts = f.read()

# Check for obvious syntax errors
import re
errors = []
for i, line in enumerate(ts.split('\n'), 1):
    # Check for broken function signatures
    if re.search(r'function\s+\w+\([^)]*\)\s*[^:{]\s*\{', line):
        errors.append(f"L{i}: {line.strip()[:80]}")
    # Check for missing colons in object properties
    if re.search(r'^\s+\w+\s*$', line) and i > 1:
        prev = ts.split('\n')[i-2].strip() if i > 1 else ''
        if prev.endswith(',') and not line.strip().endswith(('{', ',', '}')):
            errors.append(f"L{i}: possible missing colon: {line.strip()[:60]}")

print(f"TS syntax errors found: {len(errors)}")
for err in errors[:10]:
    print(f"  {err}")

# The .ts file is broken. Let's restore from the .js file which has correct logic
# but we need to add back TypeScript types for wrangler to compile

# Actually, the simplest approach: use the .js file but rename to .ts
# Cloudflare Workers runtime accepts .ts files and compiles them
# The issue is wrangler's build system

# Let's try: deploy .js as .ts (wrangler will treat it as TS but it's valid JS)
import shutil
shutil.copy('worker/index.js', 'worker/index_deploy.ts')

result = subprocess.run(
    ['wrangler', 'deploy', 'worker/index_deploy.ts'],
    capture_output=True, text=True, timeout=60, env=env
)
print(result.stdout[-500:])
if result.stderr:
    print("STDERR:", result.stderr[-300:])
print("Exit:", result.returncode)

# Cleanup
os.remove('worker/index_deploy.ts')
