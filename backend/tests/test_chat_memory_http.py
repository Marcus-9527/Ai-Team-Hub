"""Task 7 第5步 HTTP 层验证：/api/brain/chat-memories 走 ws_id_of 隔离。

复用 test_board_task_claim_concurrency 的 _fake_request 模式（不设真 server）。
Run:
  PYTHONPATH=/home/liunx/workspace/ai-team-hub python backend/tests/test_chat_memory_http.py
"""
import asyncio
import sys
from types import SimpleNamespace

from backend.routes.brain import list_chat_memories
from backend.services.brain.fragment_store import (
    get_brain_fragment_store,
    BrainFragment,
    BrainFragmentType,
)


def _fake_request(ws):
    """Minimal stub: route reads ws_id_of(request) → request.state.workspace_id."""
    req = SimpleNamespace()
    req.state = SimpleNamespace()
    req.state.workspace_id = ws
    req.headers = {}
    return req


async def main():
    store = get_brain_fragment_store()
    ws_a, ws_b = "ws_http_A", "ws_http_B"

    await store.store(BrainFragment(
        teammate_id="tm_a", workspace_id=ws_a, fragment_type=BrainFragmentType.CHAT_MEMORY,
        content="A 的事实", source="chat_memory",
    ))
    await store.store(BrainFragment(
        teammate_id="tm_b", workspace_id=ws_b, fragment_type=BrainFragmentType.CHAT_MEMORY,
        content="B 的事实", source="chat_memory",
    ))

    # HTTP 层：handler 直接读 request.state.workspace_id
    resp_a = await list_chat_memories(_fake_request(ws_a))
    resp_b = await list_chat_memories(_fake_request(ws_b))

    assert resp_a["count"] == 1 and resp_a["items"][0]["workspace_id"] == ws_a, f"ws_a 隔离失败: {resp_a}"
    assert resp_b["count"] == 1 and resp_b["items"][0]["workspace_id"] == ws_b, f"ws_b 隔离失败: {resp_b}"
    # 跨 ws 互不污染
    assert resp_a["items"][0]["content"] != resp_b["items"][0]["content"]
    # 字段齐全供前端
    item = resp_a["items"][0]
    assert {"id", "teammate_id", "workspace_id", "content", "created_at"} <= item.keys()
    print(f"[OK] HTTP /api/brain/chat-memories ws 隔离: A={resp_a['count']} B={resp_b['count']}，字段齐全")


if __name__ == "__main__":
    asyncio.run(main())
