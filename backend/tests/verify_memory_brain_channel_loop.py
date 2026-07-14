"""端到端验证 Memory → Brain → Channel Notify 完整闭环 (真实 Hook)。

不 mock 任何业务代码：使用与 main.py 完全相同的三个真实 Hook
(MemoryTaskHook / BrainTaskHook / ChannelNotifyHook)，通过真实
TaskHookRegistry.dispatch 触发，最后直接查真实 SQLite 确认三处副作用落地。

运行：
  cd ai-team-hub/backend && PYTHONPATH=. AI_TEAM_HUB_DB=/tmp/loop_verify.db \
      python tests/verify_memory_brain_channel_loop.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# 用临时数据库，隔离污染
_DB = os.path.join(tempfile.gettempdir(), "loop_verify.db")
if os.path.exists(_DB):
    os.remove(_DB)
os.environ["AI_TEAM_HUB_DB"] = _DB

# backend 包位于 ai-team-hub/backend，需把 ai-team-hub 加入 sys.path
_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PROJECT)
print(f"[setup] project root = {_PROJECT}")


async def main() -> int:
    from backend.database import init_db, async_session
    from backend.models import Message
    from sqlalchemy import text

    from backend.services.memory.memory_event_handler import MemoryTaskHook
    from backend.services.brain.task_hook import BrainTaskHook
    from backend.services.brain.channel_notify_hook import ChannelNotifyHook
    from backend.services.task.task_hooks import (
        get_task_hook_registry,
        TaskLifecycleEvent,
        TaskHookContext,
    )
    from backend.services.memory.memory_service import get_memory_service
    from backend.services.memory.memory_types import MemoryItem, MemoryType
    from backend.services.brain.fragment_store import get_brain_fragment_store

    await init_db()

    # 注册与 main.py 完全一致的三个真实 Hook
    registry = get_task_hook_registry()
    registry.register(MemoryTaskHook())
    registry.register(BrainTaskHook())
    registry.register(ChannelNotifyHook())
    assert registry.hook_count == 3, f"expected 3 hooks, got {registry.hook_count}"

    # ── 预置 Memory：让 Brain consolidation 有≥3条同类 DECISION 可合并 ──
    # 用 DECISION 而非 EXECUTION：consolidation 把 EXECUTION 也映射到 brain:lessons，
    # 会和 reflection 写的 brain:lessons 撞槽被 dedup 抑制。DECISION→brain:decisions
    # 与 reflection(LESSONS) 互不干扰，可干净验证两个 Brain 分支都写盘。
    mem = get_memory_service()
    tm_id = "tm_verify_001"
    ch_id = "ch_verify_001"
    for i in range(3):
        await mem.store(MemoryItem(
            memory_type=MemoryType.DECISION,
            content=f"Decision {i}: chose PostgreSQL over Mongo for durability tradeoff",
            source_id=f"dec_{i}",
            relevance_score=0.85,
            metadata={"teammate_id": tm_id, "task_id": "task_verify"},
        ))

    # ── 触发真实的 TASK_COMPLETED 事件 ──
    # 关键：execution_teammate_id 必须非空，否则 BrainTaskHook.reflection 静默 no-op
    ctx = TaskHookContext(
        task_id="task_verify",
        task_title="验证闭环任务",
        task_description="端到端测试 Memory→Brain→Channel",
        task_status="COMPLETED",
        channel_id=ch_id,
        workspace_id="ws_verify",
        execution_id="exec_verify",
        execution_outcome="success",
        execution_teammate_id=tm_id,
        step_error="",
        extra={"teammate_id": tm_id},
    )
    await registry.dispatch(TaskLifecycleEvent.TASK_COMPLETED, ctx)

    # MemoryTaskHook 用 buffered 异步 flush（2s timeout）。等它落盘。
    mem_hook = registry._hooks[0]
    await mem_hook.buffer.flush()
    # BrainTaskHook 内 reflection + consolidation 都是 fire-and-forget，等足够时间完成
    await asyncio.sleep(1.0)

    # ── 断言 1: Memory 落地 ──
    mem_items = await mem.query(limit=200)
    mem_types = {it.memory_type for it in mem_items}
    has_task = MemoryType.TASK in mem_types
    print(f"[1] Memory 落地: {len(mem_items)} items, types={sorted(mem_types)}")

    # ── 断言 2: Brain 落地 (reflection lesson + consolidation fragment) ──
    store = get_brain_fragment_store()
    frags = await store.get_all_by_teammate(tm_id)
    frag_types = {f.fragment_type for f in frags}
    print(f"[2] Brain 落地: {len(frags)} fragments, types={sorted(frag_types)}")

    # ── 断言 3: Channel Notify 落地 (真实 Message 表) ──
    async with async_session() as db:
        res = await db.execute(
            text("SELECT role, author_name, content FROM messages WHERE channel_id = :c ORDER BY rowid DESC LIMIT 1"),
            {"c": ch_id},
        )
        row = res.fetchone()
    channel_ok = row is not None
    role = row[0] if row else None
    author = row[1] if row else None
    content = (row[2][:40] if row else "")
    print(f"[3] Channel 落地: {'OK' if channel_ok else 'MISSING'} "
          f"-> role={role} author={author!r} content={content!r}")

    # ── 闭环判定 ──
    ok = has_task and channel_ok and any("brain:" in t for t in frag_types)
    print("\n=== 闭环验证结果 ===")
    print(f"  Memory  : {'✅' if has_task else '❌'} 任务记忆已写入")
    print(f"  Brain   : {'✅' if any('brain:' in t for t in frag_types) else '❌'} "
          f"reflection/consolidation 已生成 fragment ({sorted(frag_types)})")
    print(f"  Channel : {'✅' if channel_ok else '❌'} 系统消息已写入频道")
    print(f"  Hook数  : {registry.hook_count}/3 已注册并触发")
    print("\n结论:", "🟢 闭环真实工作 (Memory→Brain→Channel Notify)" if ok else "🔴 闭环存在断点")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
