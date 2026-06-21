#!/usr/bin/env python3
"""重新插入完整 OpenRouter key 到 D1"""
import json, subprocess, os

# 完整 key
full_key = "sk-or-...15c2"

# 写入临时文件
with open("/tmp/_full_or_key.txt", "w") as f:
    f.write(full_key)

# 用 curl 更新 D1
# 先删除旧 key
cmd = ["curl", "-s", "-X", "DELETE", "https://ai-team-hub.wt5371.workers.dev/api/apikeys/c2eff3f1-8ccb-45f2-8bd6-77177063a21",
       "-H", "User-Agent: Mozilla/5.0"]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
print("Delete:", r.stdout[:200])

# 插入新 key（用 POST）
cmd2 = ["curl", "-s", "-X", "POST", "https://ai-team-hub.wt5371.workers.dev/api/apikeys",
        "-H", "Content-Type: application/json",
        "-H", "User-Agent: Mozilla/5.0",
        "-d", json.dumps({
            "provider": "openrouter",
            "label": "2",
            "api_key": full_key,
            "base_url": "https://openrouter.ai/api/v1/responses"
        })]
r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
print("Insert:", r2.stdout[:200])
