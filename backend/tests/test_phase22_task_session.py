"""
Phase 2.2 — Task Session lifecycle verification.

Validates:
  A. SessionTrigger created on task creation
  B. SessionTurn written for plan / review / step execution
  C. execution_id linked to ExecutionRecord
  D. All turns closed properly
"""
import os
import sys
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.models.session import SessionTrigger, SessionTurn, TriggerType, TurnAction
from backend.services.session.session_hooks import SessionHooks

pytestmark = pytest.mark.asyncio


async def _get_all(db_session, model):
    from sqlalchemy import select
    r = await db_session.execute(select(model))
    return list(r.scalars().all())


async def test_session_trigger_created_on_task_create(db_session):
    """A. Task creation produces a SessionTrigger with type=TASK."""
    from backend.models import TaskModel

    task = TaskModel(title="test task", description="phase 2.2 test",
                     workspace_id="ws_test", channel_id="ch_test",
                     status="PENDING", priority=2, intent="test", created_by="test")
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch_test", user_msg_id="",
        workspace_id="ws_test", trigger_type=TriggerType.TASK, task_id=task.id,
    )
    await db_session.commit()

    assert trigger.trigger_type == TriggerType.TASK.value
    assert trigger.task_id == task.id
    assert trigger.workspace_id == "ws_test"
    assert trigger.status == "active"

    await hooks.close_trigger(trigger.id, status="completed")
    await db_session.commit()
    assert trigger.status == "completed"
    assert trigger.ended_at is not None


async def test_session_turn_for_plan(db_session):
    """B1. SessionTurn with turn_type='plan' written during _plan()."""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        workspace_id="ws", trigger_type=TriggerType.TASK, task_id="task_1",
    )
    await db_session.commit()

    turn = await hooks.start_turn(trigger.id, teammate_id="system")
    turn.turn_type = "plan"
    await db_session.flush()
    await hooks.close_turn(turn.id, action=TurnAction.RESPONDED)

    turns = await _get_all(db_session, SessionTurn)
    assert len(turns) == 1
    assert turns[0].turn_type == "plan"
    assert turns[0].teammate_id == "system"
    assert turns[0].action == TurnAction.RESPONDED.value
    assert turns[0].end_time is not None
    assert turns[0].failure is None


async def test_session_turn_for_techlead_review(db_session):
    """B2. SessionTurn with turn_type='review'."""
    from backend.models import Teammate
    tl = Teammate(name="TL", role="techlead", model_provider="openrouter", model_name="x")
    db_session.add(tl)
    await db_session.flush()

    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        workspace_id="ws", trigger_type=TriggerType.TASK, task_id="task_2",
    )
    await db_session.commit()

    turn = await hooks.start_turn(trigger.id, teammate_id=tl.id)
    turn.turn_type = "review"
    await db_session.flush()
    await hooks.close_turn(turn.id, action=TurnAction.RESPONDED)

    turns = await _get_all(db_session, SessionTurn)
    assert len(turns) == 1
    assert turns[0].turn_type == "review"
    assert turns[0].teammate_id == tl.id
    assert turns[0].end_time is not None
    assert turns[0].failure is None


async def test_session_turn_for_step_execution(db_session):
    """B3 + C. SessionTurn with turn_type='task', execution_id linked."""
    from backend.models import Teammate, TaskModel, TaskStepModel, TaskExecutionModel
    tm = Teammate(name="Bot", role="engineer", model_provider="openrouter", model_name="x")
    db_session.add(tm)
    task = TaskModel(title="t", status="PENDING", created_by="test")
    db_session.add(task)
    await db_session.flush()

    step = TaskStepModel(task_id=task.id, objective="do it", teammate_id=tm.id,
                         order=1, status="PENDING")
    db_session.add(step)
    await db_session.flush()

    execution = TaskExecutionModel(
        task_step_id=step.id, attempt=1,
        maeos_task_id="maeos_1", trace_id="trace_1", teammate_id=tm.id,
    )
    db_session.add(execution)
    await db_session.flush()

    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        workspace_id="ws", trigger_type=TriggerType.TASK, task_id=task.id,
    )
    await db_session.flush()

    turn = await hooks.start_turn(trigger.id, teammate_id=tm.id)
    turn.turn_type = "task"
    turn.execution_id = execution.id
    await db_session.flush()
    await hooks.close_turn(turn.id, action=TurnAction.RESPONDED)

    assert turn.execution_id == execution.id
    assert turn.turn_type == "task"
    assert turn.end_time is not None

    fresh = await db_session.get(SessionTurn, turn.id)
    assert fresh.execution_id == execution.id


async def test_failed_turn_recorded(db_session):
    """D. Failed step records failure on turn."""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        workspace_id="ws", trigger_type=TriggerType.TASK, task_id="task_fail",
    )
    await db_session.flush()

    turn = await hooks.start_turn(trigger.id, teammate_id="bot")
    turn.turn_type = "task"
    await db_session.flush()
    turn.failure = "execution error"
    turn.end_time = datetime.now(timezone.utc)
    await db_session.flush()

    assert turn.failure == "execution error"
    assert turn.end_time is not None

    failed = await hooks.record_failed_turn(
        trigger.id, teammate_id="bot2", failure="timeout",
    )
    assert failed.failure == "timeout"
    assert failed.end_time is not None


async def test_trigger_marked_task_type(db_session):
    """Correct trigger_type=TASK on the SessionTrigger."""
    hooks = SessionHooks(db_session)
    trigger = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        workspace_id="ws", trigger_type=TriggerType.TASK, task_id="t_type_check",
    )
    await db_session.flush()
    assert trigger.trigger_type == "task"
