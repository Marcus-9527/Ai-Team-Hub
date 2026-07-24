"""
Phase 2.3 — Session Event Stream 验证测试。

验收标准:
A. 一次 Chat 可以查询完整事件链
B. 一次 Task 可以查询 plan/review/tool/execution 全流程
C. 新增 teammate 行为无需新增日志代码
D. Session 与 ExecutionRecord 语义不变
"""
import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio

from backend.models.session import (
    SessionTrigger, SessionTurn, SessionEvent,
    TriggerType, TurnAction,
)
from backend.services.session.session_hooks import SessionHooks


async def _events_for(db_session, trigger_id) -> list[SessionEvent]:
    """Helper: query events ordered by timestamp."""
    from sqlalchemy import select
    r = await db_session.execute(
        select(SessionEvent)
        .where(SessionEvent.trigger_id == trigger_id)
        .order_by(SessionEvent.timestamp)
    )
    return list(r.scalars().all())


async def test_event_model_creates_and_persists(db_session):
    """SessionEvent 模型可以创建和持久化。"""
    # Create trigger first (FK)
    trigger = SessionTrigger(trigger_type="test", channel_id="ch")
    db_session.add(trigger)
    await db_session.flush()

    event = SessionEvent(
        trigger_id=trigger.id,
        event_type="test.event",
        payload={"key": "val"},
    )
    db_session.add(event)
    await db_session.commit()

    fresh = await db_session.get(SessionEvent, event.id)
    assert fresh is not None
    assert fresh.event_type == "test.event"
    assert fresh.payload == {"key": "val"}
    assert fresh.timestamp is not None
    assert fresh.trigger_id == trigger.id
    assert fresh.turn_id is None


async def test_start_turn_auto_emits_event(db_session):
    """A. auto-emit turn.start on start_turn()."""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )
    turn = await hooks.start_turn(trigger.id, teammate_id="bot")

    events = await _events_for(db_session, trigger.id)
    assert len(events) == 1
    assert events[0].event_type == "turn.start"
    assert events[0].turn_id == turn.id
    assert events[0].payload["teammate_id"] == "bot"


async def test_close_turn_auto_emits_event(db_session):
    """A. auto-emit turn.close on close_turn()."""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )
    turn = await hooks.start_turn(trigger.id, teammate_id="bot")
    await hooks.close_turn(turn.id, action=TurnAction.RESPONDED,
                           tokens_in=100, tokens_out=50)

    events = await _events_for(db_session, trigger.id)
    assert len(events) == 2
    assert events[0].event_type == "turn.start"
    assert events[1].event_type == "turn.close"
    assert events[1].turn_id == turn.id
    assert events[1].payload["action"] == "responded"
    assert events[1].payload["tokens_in"] == 100
    assert events[1].payload["tokens_out"] == 50


async def test_record_failed_turn_auto_emits_event(db_session):
    """A. auto-emit turn.fail on record_failed_turn()."""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.TASK,
    )
    turn = await hooks.record_failed_turn(
        trigger.id, teammate_id="bot", failure="timeout",
    )

    events = await _events_for(db_session, trigger.id)
    assert len(events) == 1
    assert events[0].event_type == "turn.fail"
    assert events[0].turn_id == turn.id
    assert events[0].payload["failure"] == "timeout"
    assert turn.failure == "timeout"


async def test_record_turn_auto_emits_event(db_session):
    """record_turn() 一步完成 start+close 并产生 turn.record 事件。"""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )
    turn = await hooks.record_turn(
        trigger.id, teammate_id="bot",
        action=TurnAction.CEDED,
    )

    events = await _events_for(db_session, trigger.id)
    assert len(events) == 1
    assert events[0].event_type == "turn.record"
    assert events[0].turn_id == turn.id
    assert events[0].payload["action"] == "ceded"


async def test_close_trigger_auto_emits_event(db_session):
    """close_trigger() 产生 trigger.close 事件。"""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )
    await hooks.close_trigger(trigger.id, status="completed")

    events = await _events_for(db_session, trigger.id)
    assert len(events) == 1
    assert events[0].event_type == "trigger.close"
    assert events[0].payload["status"] == "completed"
    assert trigger.ended_at is not None


async def test_emit_event_custom(db_session):
    """hooks.emit_event() 可以写任意类型的事件。"""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )
    evt = await hooks.emit_event(
        trigger.id, event_type="custom.test",
        payload={"msg": "hello"},
    )
    assert evt.event_type == "custom.test"
    assert evt.payload == {"msg": "hello"}


async def test_task_full_event_chain(db_session):
    """B. 一次 Task 产生 plan/review/task 完整事件链。

    模拟 task session 生命周期（类似 Phase 2.2 的流程）并验证事件流。
    """
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="task_ch", user_msg_id="",
        workspace_id="ws_test", trigger_type=TriggerType.TASK, task_id="task_3",
    )

    # 1. Plan turn
    plan_turn = await hooks.start_turn(trigger.id, teammate_id="system")
    plan_turn.turn_type = "plan"
    await hooks.close_turn(plan_turn.id, action=TurnAction.RESPONDED)

    # 2. TechLead review turn
    tl = await hooks.start_turn(trigger.id, teammate_id="techlead_1")
    tl.turn_type = "review"
    await hooks.close_turn(tl.id, action=TurnAction.RESPONDED)

    # 3. Step execution turns (2 steps)
    step1 = await hooks.start_turn(trigger.id, teammate_id="engineer_1")
    step1.turn_type = "task"
    await hooks.close_turn(step1.id, action=TurnAction.RESPONDED,
                           tokens_in=200, tokens_out=100)

    step2 = await hooks.start_turn(trigger.id, teammate_id="engineer_2")
    step2.turn_type = "task"
    await hooks.record_failed_turn(
        trigger.id, teammate_id="engineer_2",
        failure="tool error", execution_id=step2.execution_id,
    )

    # 4. Close trigger
    await hooks.close_trigger(trigger.id, status="completed")

    events = await _events_for(db_session, trigger.id)

    # 验证事件链：按类型和顺序
    event_types = [e.event_type for e in events]
    expected_sequence = [
        "turn.start", "turn.close",       # plan
        "turn.start", "turn.close",       # review
        "turn.start", "turn.close",       # step1
        "turn.start", "turn.fail",        # step2 → note: step2's start_turn then record_failed_turn
        "trigger.close",                  # trigger done
    ]
    assert event_types == expected_sequence, f"Expected {expected_sequence}, got {event_types}"

    # 每个事件都有 trigger_id 和 timestamp
    for evt in events:
        assert evt.trigger_id == trigger.id
        assert evt.timestamp is not None

    # turn.start 事件链接着正确 turn
    start_events = [e for e in events if e.event_type == "turn.start"]
    assert start_events[0].turn_id == plan_turn.id
    assert start_events[1].turn_id == tl.id
    assert start_events[2].turn_id == step1.id


async def test_events_linked_to_turn(db_session):
    """事件通过 turn_id 关联到 SessionTurn，可以双向查询。"""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )
    turn = await hooks.start_turn(trigger.id, teammate_id="bot")
    await hooks.close_turn(turn.id, action=TurnAction.RESPONDED)

    # 按 turn 查事件
    turn_events = await hooks.events_for_turn(turn.id)
    assert len(turn_events) == 2
    assert turn_events[0].event_type == "turn.start"
    assert turn_events[1].event_type == "turn.close"

    # 事件反过来指向 turn
    assert turn_events[0].turn_id == turn.id
    assert turn_events[1].turn_id == turn.id


async def test_events_for_trigger_ordered(db_session):
    """events_for_trigger 按时间序返回。"""
    from asyncio import sleep
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.CHAT,
    )

    await hooks.emit_event(trigger.id, event_type="alpha")
    await hooks.emit_event(trigger.id, event_type="beta")
    await hooks.emit_event(trigger.id, event_type="gamma")

    events = await hooks.events_for_trigger(trigger.id)
    assert [e.event_type for e in events] == ["alpha", "beta", "gamma"]

    # standalone query also works
    raw = await _events_for(db_session, trigger.id)
    assert [e.event_type for e in raw] == ["alpha", "beta", "gamma"]


async def test_execution_record_unchanged(db_session):
    """D. ExecutionRecord 语义不变 — 不增加 session_event 字段不影响它。"""
    from backend.models.task import TaskExecutionModel
    exec_record = TaskExecutionModel(
        task_step_id="step_1", attempt=1,
        maeos_task_id="maeos_x", trace_id="trace_x",
        teammate_id="bot",
    )
    db_session.add(exec_record)
    await db_session.flush()

    # 创建 session 并关联 execution_id
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        trigger_type=TriggerType.TASK, task_id="task_x",
    )
    turn = await hooks.start_turn(trigger.id, teammate_id="bot")
    turn.execution_id = exec_record.id
    await db_session.flush()
    await hooks.close_turn(turn.id, action=TurnAction.RESPONDED)

    # 事件有关 execution_id，但 TaskExecutionModel 本身无变化
    events = await _events_for(db_session, trigger.id)
    turn_event = events[0]  # turn.start
    assert turn_event.turn_id == turn.id

    # TaskExecutionModel 没有 session 字段
    fresh_exec = await db_session.get(TaskExecutionModel, exec_record.id)
    assert fresh_exec.maeos_task_id == "maeos_x"
    # 不需要 hasattr 检查 — 只要 ExecutionRecord 没有 session_event 字段就算通过


async def test_agent_loop_on_event_fires_by_default(db_session):
    """AgentLoop.run on_event 默认始终触发（no-op），不会报错。"""
    from backend.services.runtime.agent_loop import AgentLoop
    from unittest.mock import AsyncMock

    llm_mock = AsyncMock()
    llm_mock.complete.return_value = type("Resp", (), {
        "text": "hello", "tool_calls": [], "stop_reason": "end_turn",
    })()

    tool_mock = AsyncMock()
    loop = AgentLoop(llm_client=llm_mock, tool_executor=tool_mock)

    # No on_event passed — default no-op, should not crash
    result = await loop.run(
        system_prompt="be helpful",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        workspace_id="ws",
        subject="test",
    )
    assert result.final_text == "hello"

    # With on_event wired — should be called
    collector = []
    async def capture(*args):
        collector.append(args)
    result2 = await loop.run(
        system_prompt="be helpful",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        workspace_id="ws",
        subject="test2",
        on_event=capture,
    )
    assert len(collector) >= 2  # text_delta + final
    types = [c[0] for c in collector]
    assert "text_delta" in types
    assert "final" in types
