"""Task 7 第1-2步验证：CHAT_MEMORY 落库 + workspace/teammate/channel 三字段隔离。

Ponytail: 单文件 self-check，无框架。Run:
  PYTHONPATH=/home/liunx/workspace/ai-team-hub python backend/tests/test_chat_memory_store.py
"""
import asyncio
import sys

from backend.services.brain.fragment_store import (
    get_brain_fragment_store,
    BrainFragment,
    BrainFragmentType,
)
from backend.services.brain import chat_memory


async def main():
    store = get_brain_fragment_store()

    ws = "ws_task7"
    tm = "tm_task7"
    ch = "ch_task7"

    # 1. 直接落一条 CHAT_MEMORY，验证三字段往返
    frag = BrainFragment(
        teammate_id=tm,
        workspace_id=ws,
        channel_id=ch,
        fragment_type=BrainFragmentType.CHAT_MEMORY,
        content="用户叫李雷，项目用 React。",
        confidence=0.8,
        source="chat_memory",
    )
    await store.store(frag)
    # 取回该 teammate 在该 workspace 的所有 fragment（最新版本）
    items = await store.get_all_by_teammate(tm, workspace_id=ws)
    mems = [f for f in items if f.fragment_type == BrainFragmentType.CHAT_MEMORY]
    assert mems, "CHAT_MEMORY 未写入"
    got = mems[0]
    assert got.workspace_id == ws, f"workspace_id 错: {got.workspace_id}"
    assert got.teammate_id == tm, f"teammate_id 错: {got.teammate_id}"
    assert got.channel_id == ch, f"channel_id 错: {got.channel_id}"
    assert "李雷" in got.content, f"content 错: {got.content}"
    assert "channel_id" in got.to_dict(), "to_dict 漏 channel_id"
    print(f"[OK] CHAT_MEMORY 落库: ws={got.workspace_id} tm={got.teammate_id} ch={got.channel_id} content='{got.content}'")

    # 2. 跨 workspace 隔离：另一 workspace 查不到这条
    other = await store.get_all_by_teammate(tm, workspace_id="ws_other")
    other_mems = [f for f in other if f.fragment_type == BrainFragmentType.CHAT_MEMORY]
    assert not other_mems, f"跨 workspace 泄漏: {other_mems}"
    print("[OK] 跨 workspace 隔离: ws_other 查不到该记忆")

    # 3. extract_and_store 无 key 时静默跳过（不抛、不崩）
    no_key_teammate = {"id": tm, "workspace_id": ws, "model_name": "x"}  # 没有 api_key_ref
    # 直接调内部 _do_store 验证 best-effort：无 key 应 return 不报错
    await chat_memory._do_store(no_key_teammate, "hi", "reply", ch)
    print("[OK] 无 key 时 _do_store 静默跳过（best-effort）")

    print("\nALL CHAT_MEMORY CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
