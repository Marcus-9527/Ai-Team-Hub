"""Task 7 第5步后端验证：list_chat_memory_by_workspace 隔离 + 倒序。

Run:
  PYTHONPATH=/home/liunx/workspace/ai-team-hub python backend/tests/test_chat_memory_list.py
"""
import asyncio

from backend.services.brain.fragment_store import (
    get_brain_fragment_store,
    BrainFragment,
    BrainFragmentType,
)


async def main():
    store = get_brain_fragment_store()
    ws_a, ws_b = "ws_list_A", "ws_list_B"

    # a 的两条（不同队友），b 的一条
    await store.store(BrainFragment(
        teammate_id="tm_a1", workspace_id=ws_a, fragment_type=BrainFragmentType.CHAT_MEMORY,
        content="A1 的事实", source="chat_memory",
    ))
    await store.store(BrainFragment(
        teammate_id="tm_a2", workspace_id=ws_a, fragment_type=BrainFragmentType.CHAT_MEMORY,
        content="A2 的事实", source="chat_memory",
    ))
    await store.store(BrainFragment(
        teammate_id="tm_b1", workspace_id=ws_b, fragment_type=BrainFragmentType.CHAT_MEMORY,
        content="B1 的事实", source="chat_memory",
    ))

    a = await store.list_chat_memory_by_workspace(ws_a)
    b = await store.list_chat_memory_by_workspace(ws_b)

    assert len(a) == 2, f"ws_a 应 2 条，实际 {len(a)}"
    assert len(b) == 1, f"ws_b 应 1 条，实际 {len(b)}"
    # 全部精确命中 ws
    assert all(m.workspace_id == ws_a for m in a), "ws_a 泄漏"
    assert all(m.workspace_id == ws_b for m in b), "ws_b 泄漏"
    # 倒序
    times = [m.created_at for m in a]
    assert times == sorted(times, reverse=True), "未倒序"
    # to_dict 含前端需要的字段
    d = a[0].to_dict()
    assert {"id", "teammate_id", "workspace_id", "content", "created_at"} <= d.keys(), f"字段缺失: {d.keys()}"
    print(f"[OK] ws_a={len(a)} 条（最新='{a[0].content}'） ws_b={len(b)} 条，全部命中 ws 过滤、倒序、字段齐全")


if __name__ == "__main__":
    asyncio.run(main())
