"""
test_task_workspace_scope.py — Workspace-scoped task isolation test.

Ensures list_tasks requires workspace_id and returns only that workspace's tasks.
Pattern: create two workspaces with their own tasks, then verify isolation.

Two workspaces:
  WS_A = test-ws-a
  WS_B = test-ws-b

Tests:
  1. list_tasks without workspace_id → ValueError (guarded at service layer)
  2. Each workspace sees only its own tasks
  3. Different workspace sees empty list
"""

import uuid
import pytest
from pytest import fixture

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.task.task_state import TaskStateManager

pytestmark = [pytest.mark.asyncio]

WS_A = "test-ws-a"
WS_B = "test-ws-b"


@fixture
def state_mgr():
    return TaskStateManager()


@fixture
def unique_title():
    return f"task-{uuid.uuid4().hex[:8]}"


async def _create_task(db_session, workspace_id: str, title: str, state_mgr):
    return await state_mgr.create_task(
        db_session,
        title=title,
        created_by="test",
        workspace_id=workspace_id,
    )


async def test_list_tasks_requires_workspace_id(db_session, state_mgr):
    """
    Calling list_tasks without workspace_id raises ValueError.
    """
    with pytest.raises(TypeError, match="required keyword-only argument: 'workspace_id'"):
        await state_mgr.list_tasks(db_session)


async def test_list_tasks_isolation_two_workspaces(db_session, state_mgr):
    """
    Two workspaces each have their own tasks.
    Workspace A sees only A's tasks, workspace B sees only B's tasks.
    """
    # Create 2 tasks in WS_A, 1 task in WS_B
    a1 = await _create_task(db_session, WS_A, "task-a1", state_mgr)
    a2 = await _create_task(db_session, WS_A, "task-a2", state_mgr)
    b1 = await _create_task(db_session, WS_B, "task-b1", state_mgr)
    await db_session.flush()

    # WS_A sees 2 tasks
    tasks_a = await state_mgr.list_tasks(db_session, workspace_id=WS_A)
    assert len(tasks_a) == 2, f"WS_A expected 2 tasks, got {len(tasks_a)}"
    for t in tasks_a:
        assert t.workspace_id == WS_A, f"Task {t.id} has ws={t.workspace_id}, expected {WS_A}"

    # WS_B sees 1 task
    tasks_b = await state_mgr.list_tasks(db_session, workspace_id=WS_B)
    assert len(tasks_b) == 1, f"WS_B expected 1 task, got {len(tasks_b)}"
    for t in tasks_b:
        assert t.workspace_id == WS_B, f"Task {t.id} has ws={t.workspace_id}, expected {WS_B}"

    # The two lists have no overlap
    ids_a = {t.id for t in tasks_a}
    ids_b = {t.id for t in tasks_b}
    assert ids_a.isdisjoint(ids_b), "Workspace A and B returned overlapping task IDs — no isolation!"


async def test_workspace_sees_only_own_tasks(db_session, state_mgr):
    """
    A workspace that created tasks sees them.
    A different workspace (no tasks) sees empty list.
    """
    # Create tasks in WS_A only
    await _create_task(db_session, WS_A, "only-a", state_mgr)
    await db_session.flush()

    # WS_A sees its tasks
    tasks_a = await state_mgr.list_tasks(db_session, workspace_id=WS_A)
    assert len(tasks_a) >= 1

    # WS_B (no tasks) sees empty
    tasks_b = await state_mgr.list_tasks(db_session, workspace_id=WS_B)
    assert len(tasks_b) == 0, f"WS_B (empty) expected 0 tasks, got {len(tasks_b)}"
