#!/bin/bash
cd /home/liunx/workspace/ai-team-hub
CLOUDFLARE_API_TOKEN="cfut_ZAbIuZYvFTq5GRdeE4ugq95e5Uh9kEFbMv7foHl89b49f0f4" wrangler deploy worker/index.ts 2>&1 | tail -5
