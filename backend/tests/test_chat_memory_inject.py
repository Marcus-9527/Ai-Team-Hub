"""Task 7 第3步验证：CHAT_MEMORY 注入（最近N条 + ws/tm 过滤 + best-effort）。

Run:
  PYTHONPATH=/home/liunx/workspace/ai-team-hub python backend/tests/test_chat_memory_inject.py
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
    BrainFragment,
    BrainFragmentType,
)
from backend.services.runtime import teammate_runner
from backend.services.runtime.teammate_runner import stream_teammate


def _tm_dict(tm):
    return {
        "id": tm.id, "name": tm.name, "workspace_id": tm.workspace_id,
        "model_name": tm.model_name, "model_provider": tm.model_provider,
        "api_key_ref": tm.api_key_ref, "system_prompt": tm.system_prompt or "",
    }


async def main():
    async with async_session() as db:
        tm = (await db.execute(
            select(Teammate).where(Teammate.name == "TestAI")
        )).scalar_one_or_none()
        assert tm, "TestAI 未找到"
        tmd = _tm_dict(tm)
        ws = tm.workspace_id
        ch = "ch_inject_verify"

        # 1) 先写 3 条聊天记忆（模拟之前几轮对话）
        facts = [
            ("我叫李雷，这个协作项目前端用 React 和 TypeScript。", "好的李雷，记住了。"),
            ("我们团队用 Slack 沟通，每天早上站会。", "了解，已记下。"),
            ("项目代号 Phoenix，deadline 是下周五。", "收到，记下了 Phoenix 下周五。"),
        ]
        for u, r in facts:
            await chat_memory._do_store(tmd, u, r, ch)
        await asyncio.sleep(1.0)

        # 2) 验证 recent_chat_memory 查询：显式 WHERE source_id + workspace_id 过滤
        store = get_brain_fragment_store()
        mems = await store.recent_chat_memory(tm.id, ws, limit=8)
        # 确认每条都精确命中 teammate_id + workspace_id
        for m in mems:
            assert m.teammate_id == tm.id, f"teammate_id 漏过滤: {m.teammate_id}"
            assert m.workspace_id == ws, f"workspace_id 漏过滤: {m.workspace_id}"
            assert m.fragment_type == BrainFragmentType.CHAT_MEMORY
        assert len(mems) >= 3, f"应至少取回 3 条，实际 {len(mems)}"
        print(f"[OK] recent_chat_memory 取回 {len(mems)} 条，全部命中 tm+ws 过滤")

        # 跨 workspace 隔离：另一 ws 取不到
        other = await store.recent_chat_memory(tm.id, "ws_other", limit=8)
        assert not other, f"跨 ws 泄漏: {other}"
        print("[OK] 跨 workspace 隔离: ws_other 取不到")

        # 3) 端到端注入：开"新对话"，问一个需要用到记忆的问题
        reply_chunks = []
        try:
            async for evt in stream_teammate(
                teammate=tmd,
                user_message="提醒我一下，我们项目叫什么、前端用什么技术栈、还有多久 deadline？",
                history_texts=[],
                turn_idx=0,
                phase="collaboration_round_1",
                channel_id=ch,
            ):
                if evt.startswith("data:") and "teammate_message" in evt:
                    import json
                    payload = json.loads(evt[5:].strip().rstrip("\n")).get("payload", {})
                    reply_chunks.append(payload.get("content", ""))
        except Exception as e:
            print(f"[FAIL] stream_teammate 抛错: {e}")
            raise
        reply = "".join(reply_chunks)
        print(f"\n[reply] {reply}\n")

        # 验收：回复应自然体现出记住的事实（不要求原文粘贴，但关键信息要在）
        assert any(k in reply for k in ("李雷", "React", "TypeScript", "Phoenix", "下周五", "站会")), \
            f"回复未体现记忆中的事实: {reply}"
        print("[OK] 新对话回复自然用上了之前记住的信息（注入生效）")

        # 4) best-effort：注入查询若抛错也应正常对话（这里验证异常分支不阻塞）
        #    —— 通过临时让 store 抛错模拟
        real_method = store.recent_chat_memory
        async def boom(*a, **k):
            raise RuntimeError("simulated DB failure")
        store.recent_chat_memory = boom
        try:
            chunks2 = []
            got_end = False
            async for evt in stream_teammate(
                teammate=tmd,
                user_message="我们项目前端用什么技术栈？",
                history_texts=[],
                turn_idx=0,
                phase="collaboration_round_1",
                channel_id=ch,
            ):
                if evt.startswith("data:"):
                    import json
                    e = json.loads(evt[5:].strip().rstrip("\n"))
                    if e.get("type") == "teammate_message":
                        chunks2.append(e.get("payload", {}).get("content", ""))
                    if e.get("type") == "teammate_end":
                        got_end = True
            assert got_end, "best-effort 下对话流程应正常走完（有 teammate_end）"
            print(f"[OK] 注入 DB 故障时 best-effort 跳过，对话仍正常完成（reply={''.join(chunks2)[:60]!r}）")
        finally:
            store.recent_chat_memory = real_method


if __name__ == "__main__":
    asyncio.run(main())
