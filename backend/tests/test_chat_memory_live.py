"""Task 7 真实 LLM 提炼落库验证（需 TestAI 真 key）。

Run:
  PYTHONPATH=/home/liunx/workspace/ai-team-hub python backend/tests/test_chat_memory_live.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from backend.database import async_session
from backend.models import Teammate
from sqlalchemy import select

from backend.services.brain import chat_memory
from backend.services.brain.fragment_store import (
    get_brain_fragment_store,
    BrainFragmentType,
)


async def main():
    async with async_session() as db:
        tm = (await db.execute(
            select(Teammate).where(Teammate.name == "TestAI")
        )).scalar_one_or_none()
        assert tm, "TestAI 队友未找到"
        # 转成 teammate_runner 用的 dict 形态
        teammate = {
            "id": tm.id,
            "name": tm.name,
            "workspace_id": tm.workspace_id,
            "model_name": tm.model_name,
            "model_provider": tm.model_provider,
            "api_key_ref": tm.api_key_ref,
            "system_prompt": tm.system_prompt or "",
        }
        ws = tm.workspace_id
        ch = "ch_live_verify"

        print(f"[live] teammate={tm.name} ws={ws[:12]} ref={tm.api_key_ref[:12] if tm.api_key_ref else None}")

        # 真实跑一次提炼 + 落库
        user_msg = "我叫李雷，这个协作项目前端用 React 和 TypeScript。"
        reply = "明白了，李雷。我会记住这个项目用 React + TypeScript 技术栈。"
        await chat_memory._do_store(teammate, user_msg, reply, ch)
        await asyncio.sleep(1.0)  # 等 ensure_future 完成（这里直接 await 了，但可以双保险）

        store = get_brain_fragment_store()
        items = await store.get_all_by_teammate(tm.id, workspace_id=ws)
        mems = [f for f in items if f.fragment_type == BrainFragmentType.CHAT_MEMORY]
        assert mems, "真实 LLM 提炼未落库"
        got = mems[0]
        assert got.workspace_id == ws, f"ws 错: {got.workspace_id}"
        assert got.channel_id == ch, f"ch 错: {got.channel_id}"
        print(f"[OK] 真实提炼落库: ws={got.workspace_id[:12]} tm={got.teammate_id[:12]} ch={got.channel_id}")
        print(f"     摘要: {got.content}")

        # 跨 workspace 隔离
        other = await store.get_all_by_teammate(tm.id, workspace_id="ws_other")
        assert not [f for f in other if f.fragment_type == BrainFragmentType.CHAT_MEMORY], "跨 ws 泄漏"
        print("[OK] 跨 workspace 隔离: ws_other 查不到")


if __name__ == "__main__":
    asyncio.run(main())
