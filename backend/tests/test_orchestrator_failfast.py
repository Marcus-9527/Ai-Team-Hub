"""Fail-fast + happy-path for TaskOrchestrator.start_task.

The real bug: an unassigned DAG node carried an empty teammate_id into the
runtime and silently hung the task at PLANNING until the 120s wait_for
timeout, with no error written. Fixed by a single guard after _assign_and_save
that covers every start_task caller (tasks.py, automation.py, demo.py).

These tests mock the LLM/executor layers (no real API key needed) and assert
the orchestration state machine only — they do not hit any model provider.
"""

import pytest
from unittest.mock import AsyncMock, patch
import uuid

from sqlalchemy import select

from backend.models import TaskStatus, TaskModel
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.dag.core import DAGDefinition, DAGNode


def _make_task(db, title="t"):
    return TaskManager().create_task(
        db, title=title, description="x", created_by="u", priority=2,
    )


# ── happy path: valid teammate → COMPLETED, fail-fast didn't break success ──

@pytest.mark.asyncio
async def test_happy_path_reaches_completed(db_session):
    rt = AsyncMock()
    orch = TaskOrchestrator(runtime=rt)

    task = await _make_task(db_session)
    await db_session.commit()

    # One node WITH a teammate assigned
    node = DAGNode(description="do", selected_teammate_id=uuid.uuid4().hex)
    dag = DAGDefinition(name="d")
    dag.add_node(node)

    # Mock execution: skip real LLM, return a COMPLETED task.
    async def _fake_execute(db, t):
        t.status = TaskStatus.COMPLETED
        return t

    with patch.object(orch, "_plan", new=AsyncMock(return_value=dag)), \
         patch.object(orch, "_techlead_review", new=AsyncMock()), \
         patch.object(orch, "_persist_dag", new=AsyncMock()), \
         patch.object(orch, "_create_steps", new=AsyncMock(return_value=task)), \
         patch.object(orch, "_execute", new=_fake_execute):
        result = await orch.start_task(db_session, task.id, "x")

    assert result.status == TaskStatus.COMPLETED


# ── fail-fast: no teammate → FAILED + error persisted to DB ──

@pytest.mark.asyncio
async def test_failfast_on_unassigned_node(db_session):
    rt = AsyncMock()
    orch = TaskOrchestrator(runtime=rt)

    task = await _make_task(db_session)
    await db_session.commit()

    # One node with NO teammate selected
    node = DAGNode(description="do something")
    dag = DAGDefinition(name="d")
    dag.add_node(node)

    with patch.object(orch, "_plan", new=AsyncMock(return_value=dag)), \
         patch.object(orch, "_techlead_review", new=AsyncMock()), \
         patch.object(orch, "_persist_dag", new=AsyncMock()), \
         patch.object(orch, "_create_steps", new=AsyncMock(return_value=task)), \
         patch.object(orch, "_execute", new=AsyncMock(return_value=task)):
        result = await orch.start_task(db_session, task.id, "x")

    # In-memory result
    assert result.status == TaskStatus.FAILED
    assert result.error and "无法分配队友" in result.error

    # DB落盘：early-return 已 commit，重新查库确认状态真的写了，
    # 不会静默丢。ponytail: 直接走 TaskModel 查询，不绕 SSE/缓存。
    await db_session.commit()
    row = (await db_session.execute(
        select(TaskModel).where(TaskModel.id == task.id)
    )).scalar_one()
    assert row.status == TaskStatus.FAILED
    assert row.error and "无法分配队友" in row.error
    # runtime 不应被触碰（没进执行层）
    rt.start.assert_not_called()
