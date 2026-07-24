"""
Phase 3.1 — AI Organization Memory 基于 SessionEvent 验证测试。

验收标准:
A. 一次 task 完成后，可以从 SessionEvent 生成组织知识
B. 新增 teammate 不需要手写 memory 逻辑
C. Chat 和 Task 产生同一种 memory 输入
D. 不删除现有 memory_service
E. 不引入复杂 RAG
"""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

from backend.models.session import SessionTrigger, SessionTurn, SessionEvent, TriggerType, TurnAction
from backend.services.session.session_hooks import SessionHooks
from backend.services.memory.event_processor import MemoryEventProcessor
from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_types import MemoryItem, MemoryType
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _clean_memory():
    """Clean memory service before each test."""
    from backend.database import engine
    from sqlalchemy import text
    svc = get_memory_service()
    svc._ready = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS memory_items"))
            await conn.commit()
    except Exception:
        pass
    yield


async def _make_task_trigger(db_session) -> tuple[SessionHooks, SessionTrigger]:
    """Helper: create a TASK trigger with plan/review/step turns."""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="task_ch", user_msg_id="",
        workspace_id="ws1", trigger_type=TriggerType.TASK, task_id="task_demo_1",
    )
    return hooks, trigger


async def _make_turns(hooks, trigger, db_session) -> None:
    """Add plan/review/step turns to a trigger."""
    # Plan turn
    plan = await hooks.start_turn(trigger.id, teammate_id="system")
    plan.turn_type = "plan"
    await db_session.flush()
    await hooks.close_turn(plan.id, action=TurnAction.RESPONDED)

    # Review turn
    review = await hooks.start_turn(trigger.id, teammate_id="techlead_1")
    review.turn_type = "review"
    await db_session.flush()
    await hooks.close_turn(review.id, action=TurnAction.RESPONDED)

    # Step 1 — success
    step1 = await hooks.start_turn(trigger.id, teammate_id="engineer_1")
    step1.turn_type = "task"
    await db_session.flush()
    await hooks.close_turn(step1.id, action=TurnAction.RESPONDED,
                           tokens_in=300, tokens_out=150)

    # Step 2 — failure
    step2 = await hooks.record_failed_turn(
        trigger.id, teammate_id="engineer_2",
        failure="API rate limit",
    )
    step2.turn_type = "task"
    await db_session.flush()

    # Close trigger
    await hooks.close_trigger(trigger.id, status="completed")
    await db_session.commit()


# ── A. Task → Organization Knowledge ──

async def test_task_generates_member_memory(db_session):
    """A. task 完成后生成 member memory（队友经验）。"""
    hooks, trigger = await _make_task_trigger(db_session)
    await _make_turns(hooks, trigger, db_session)

    # Process
    proc = MemoryEventProcessor()
    count = await proc.process_trigger(db_session, trigger.id)
    assert count > 0, "Should generate memories"

    # Verify member memories
    items = await get_memory_service().query(memory_type=MemoryType.TEAMMATE, limit=100)
    member_items = [i for i in items if i.metadata.get("scope") == "member"]
    assert len(member_items) >= 1

    # Check fields
    for mi in member_items:
        assert mi.content.startswith("[")
        assert mi.metadata.get("teammate_id") is not None
        assert mi.metadata.get("turn_type") is not None
        assert mi.metadata.get("outcome") in ("completed", "failed")
        assert mi.metadata.get("source") == "session_event"

    # specific teammate traces
    engineer_items = [i for i in member_items if i.metadata["teammate_id"] == "engineer_1"]
    assert len(engineer_items) == 1
    assert engineer_items[0].metadata["outcome"] == "completed"

    failed_items = [i for i in member_items if i.metadata["outcome"] == "failed"]
    assert len(failed_items) >= 1


async def test_task_generates_team_memory(db_session):
    """A. 多队友协作产生 team memory。"""
    hooks, trigger = await _make_task_trigger(db_session)
    await _make_turns(hooks, trigger, db_session)

    proc = MemoryEventProcessor()
    await proc.process_trigger(db_session, trigger.id)

    items = await get_memory_service().query(memory_type=MemoryType.TEAMMATE, limit=100)
    team_items = [i for i in items if i.metadata.get("scope") == "team"]
    assert len(team_items) >= 1

    ti = team_items[0]
    assert ti.content.startswith("[team]")
    assert ti.metadata.get("n_teammates") >= 3
    assert ti.metadata.get("teammate_ids") is not None
    assert ti.metadata.get("turn_types") is not None
    assert ti.metadata.get("failed_turns") >= 1
    assert ti.metadata.get("trigger_type") == "task"


async def test_task_generates_project_memory(db_session):
    """A. task 完成后产生 project memory（项目事实）。"""
    hooks, trigger = await _make_task_trigger(db_session)
    await _make_turns(hooks, trigger, db_session)

    proc = MemoryEventProcessor()
    await proc.process_trigger(db_session, trigger.id)

    items = await get_memory_service().query(limit=100)
    proj_items = [i for i in items if i.metadata.get("scope") == "project"]
    assert len(proj_items) >= 1

    pi = proj_items[0]
    assert pi.content.startswith("[project]")
    assert pi.metadata.get("task_id") == "task_demo_1"
    assert pi.metadata.get("workspace_id") == "ws1"
    assert pi.metadata.get("trigger_type") == "task"
    # tokens from close events
    assert pi.metadata.get("tokens_in") >= 300
    assert pi.metadata.get("tokens_out") >= 150
    assert pi.metadata.get("failures") >= 1


async def test_memory_count_consistency(db_session):
    """验证 Task 完成后三种记忆都有合理的数量。

    4 turns (plan/review/step1/step2) → 4 member memories
    + 1 team memory (≥2 teammates) + 1 project memory
    """
    hooks, trigger = await _make_task_trigger(db_session)
    await _make_turns(hooks, trigger, db_session)

    proc = MemoryEventProcessor()
    total = await proc.process_trigger(db_session, trigger.id)

    items = await get_memory_service().query(limit=100)
    assert len(items) == total

    member_items = [i for i in items if i.metadata.get("scope") == "member"]
    team_items = [i for i in items if i.metadata.get("scope") == "team"]
    proj_items = [i for i in items if i.metadata.get("scope") == "project"]

    assert len(member_items) >= 3
    assert len(team_items) == 1
    assert len(proj_items) == 1


# ── B. New teammate → no manual memory logic ──

async def test_new_teammate_auto_memory(db_session):
    """B. 新增 teammate（加一个 turn）自动产生记忆，无需手写逻辑。"""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )
    turn = await hooks.start_turn(trigger.id, teammate_id="new_teammate_x")
    turn.turn_type = "chat"
    await db_session.flush()
    await hooks.close_turn(turn.id, action=TurnAction.RESPONDED,
                           tokens_in=50, tokens_out=100)
    await hooks.close_trigger(trigger.id, status="completed")
    await db_session.commit()

    proc = MemoryEventProcessor()
    total = await proc.process_trigger(db_session, trigger.id)
    assert total > 0

    items = await get_memory_service().query(memory_type=MemoryType.TEAMMATE, limit=100)
    new_mem = [i for i in items if i.metadata.get("teammate_id") == "new_teammate_x"]
    assert len(new_mem) == 1
    assert new_mem[0].metadata["outcome"] == "completed"


# ── C. Chat and Task produce same memory input ──

async def test_chat_produces_same_memory_types(db_session):
    """C. Chat trigger 经过同 process_trigger 产生同样三类记忆。"""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch_1", user_msg_id="msg_1",
        workspace_id="ws1", trigger_type=TriggerType.CHAT,
    )
    for tm in ["bot_a", "bot_b"]:
        t = await hooks.start_turn(trigger.id, teammate_id=tm)
        t.turn_type = "chat"
        await db_session.flush()
        await hooks.close_turn(t.id, action=TurnAction.RESPONDED,
                               tokens_in=40, tokens_out=80)
    await hooks.close_trigger(trigger.id, status="completed")
    await db_session.commit()

    proc = MemoryEventProcessor()
    await proc.process_trigger(db_session, trigger.id)

    items = await get_memory_service().query(limit=100)
    scopes = {i.metadata.get("scope") for i in items}
    assert "member" in scopes
    assert "team" in scopes
    assert "project" in scopes

    for item in items:
        assert item.metadata.get("source") == "session_event"


# ── D. Existing memory_service unchanged ──

async def test_existing_memory_service_unchanged(db_session):
    """D. 现有 MemoryService 可以继续独立使用。"""
    svc = get_memory_service()
    item = MemoryItem(
        memory_type=MemoryType.GLOBAL,
        content="legacy memory",
        source_id="manual",
    )
    await svc.store(item)
    items = await svc.query(memory_type=MemoryType.GLOBAL)
    assert len(items) == 1
    assert items[0].content == "legacy memory"


# ── E. No complex RAG ──

async def test_no_ai_summary_needed(db_session):
    """E. 记忆提取是纯规则式的，不依赖 AI/RAG。"""
    hooks, trigger = await _make_task_trigger(db_session)
    await _make_turns(hooks, trigger, db_session)

    proc = MemoryEventProcessor()
    total = await proc.process_trigger(db_session, trigger.id)

    items = await get_memory_service().query(limit=100)
    for item in items:
        assert isinstance(item.content, str)
        assert len(item.content) < 500
        assert item.embedding is not None


async def test_empty_trigger_produces_only_project_memory(db_session):
    """没有 turn 的 trigger 只产生 project memory。"""
    hooks, trigger = await _make_task_trigger(db_session)
    await hooks.close_trigger(trigger.id, status="completed")
    await db_session.commit()

    proc = MemoryEventProcessor()
    total = await proc.process_trigger(db_session, trigger.id)
    # project memory 总是产生（trigger 本身是一个事实）
    assert total == 1

    items = await get_memory_service().query(limit=100)
    proj = [i for i in items if i.metadata.get("scope") == "project"]
    assert len(proj) == 1
    assert len([i for i in items if i.metadata.get("scope") == "member"]) == 0
    assert len([i for i in items if i.metadata.get("scope") == "team"]) == 0


async def test_multiple_triggers_isolated(db_session):
    """多个 trigger 各自产生隔离的记忆。"""
    for i in range(3):
        hooks = SessionHooks(db_session)
        trigger = await hooks.open_trigger(
            channel_id=f"ch_{i}", user_msg_id="",
            trigger_type=TriggerType.CHAT,
        )
        turn = await hooks.start_turn(trigger.id, teammate_id=f"bot_{i}")
        await db_session.flush()
        await hooks.close_turn(turn.id, action=TurnAction.RESPONDED)
        await hooks.close_trigger(trigger.id, status="completed")
        await db_session.flush()

    proc = MemoryEventProcessor()
    all_triggers = await db_session.execute(
        select(SessionTrigger).order_by(SessionTrigger.trigger_time)
    )
    total = 0
    for trig in all_triggers.scalars().all():
        total += await proc.process_trigger(db_session, trig.id)

    items = await get_memory_service().query(limit=100)
    assert len(items) == total
    member_items = [i for i in items if i.metadata.get("scope") == "member"]
    assert len(member_items) == 3
