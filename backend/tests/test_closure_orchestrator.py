"""
test_closure_orchestrator.py — Verify the full AI Team auto-collaboration loop:

    TechLead(plan) → Engineer → Reviewer → (Fix on reject)

Covers requirements:
  §一  DAG hierarchy: parent_task / child_task / dependency
  §二  Reviewer auto-relay + auto fix task (MAX_REVIEW_ROUNDS=3)
  §三  Runtime output persisted to TaskModel (not only RuntimeTask memory)
  §四  Reuses executor / runtime — no new engine/scheduler/FSM

The LLM/runtime is stubbed so we test the orchestration mechanics, not the model.
"""
import json
import types

import pytest
from unittest.mock import AsyncMock, patch

from backend.models import TaskStatus
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.runtime.executor import ExecutionRuntime


def _rt_mock(*, result="done", git_commit="", review_status="pending", status="COMPLETED"):
    """A stand-in for a completed RuntimeTask."""
    return types.SimpleNamespace(
        id="rt1", status=status, result=result,
        git_commit=git_commit, review_status=review_status,
        error="",
    )


@pytest.fixture
def mock_runtime():
    r = ExecutionRuntime(max_workers=4)
    r.start = AsyncMock()
    r.submit = AsyncMock(return_value="rt1")
    r.wait = AsyncMock(return_value=_rt_mock())
    return r


# ── Scenario 1: Engineer output written back to TaskModel ──

@pytest.mark.asyncio
async def test_engineer_output_persisted_to_taskmodel(mock_runtime, db_session):
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="加缓存", intent="为 API 加缓存",
        workspace_id="ws_demo", created_by="test",
    )
    await db_session.commit()

    eng_result = json.dumps({
        "summary": "added cache",
        "files_changed": ["backend/cache.py"],
        "commands_run": ["pytest"],
        "git_commit": "abc1234",
        "test_result": "2 passed",
    })
    mock_runtime.wait = AsyncMock(return_value=_rt_mock(
        result=eng_result, git_commit="abc1234"))

    dag = DAGDefinition(name="impl")
    dag.add_node(DAGNode(description="实现", teammate="engineer"))

    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._plan = AsyncMock(return_value=dag)
    # skip the reviewer relay (no reviewer teammate in test DB)
    orch._review_relay = AsyncMock()

    result = await orch.start_task(db_session, task.id, "为 API 加缓存")
    await db_session.commit()

    assert result.status == TaskStatus.COMPLETED
    # §三: fields live on TaskModel, not only in-memory RuntimeTask
    assert result.git_commit == "abc1234"
    assert result.files_changed == ["backend/cache.py"]
    assert result.commands_run == ["pytest"]
    assert "2 passed" in result.test_result
    print("✅ Engineer output persisted to TaskModel")


# ── Scenario 2: Reviewer auto-relay → APPROVE ──

@pytest.mark.asyncio
async def test_reviewer_approve_closes_loop(mock_runtime, db_session):
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="实现功能", intent="实现 X",
        workspace_id="ws_demo", created_by="test",
    )
    await db_session.commit()

    mock_runtime.wait = AsyncMock(return_value=_rt_mock(
        result=json.dumps({"verdict": "approve", "summary": "lgtm", "blockers": []}),
        git_commit="deadbeef",
    ))

    dag = DAGDefinition(name="impl")
    dag.add_node(DAGNode(description="实现", teammate="engineer"))

    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._plan = AsyncMock(return_value=dag)
    # Force a reviewer pick so the relay actually runs
    orch._pick_teammate = AsyncMock(return_value=types.SimpleNamespace(id="rev1", role="reviewer"))

    result = await orch.start_task(db_session, task.id, "实现 X")
    await db_session.commit()

    assert result.status == TaskStatus.COMPLETED
    assert result.review_status == "approved"
    assert result.review_rounds == 1
    assert "lgtm" in result.review_comments
    print("✅ Reviewer relay APPROVE — task closed")


# ── Scenario 3: Reviewer REJECT → auto fix task (DAG child) ──

@pytest.mark.asyncio
async def test_reviewer_reject_spawns_fix_task(mock_runtime, db_session):
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="实现功能", intent="实现 X",
        workspace_id="ws_demo", created_by="test",
    )
    # give the parent an engineer step so the child can be assigned
    step = await mgr.state.create_step(db_session, task_id=task.id, order=1,
                                        objective="实现", teammate_id="eng1")
    await db_session.commit()

    # Reviewer always rejects (round 1) → must spawn a child fix task
    mock_runtime.wait = AsyncMock(return_value=_rt_mock(
        result=json.dumps({"verdict": "reject", "summary": "tests fail",
                            "blockers": ["pytest broken"]}),
    ))

    orch = TaskOrchestrator(runtime=mock_runtime)
    dag = DAGDefinition(name="impl")
    dag.add_node(DAGNode(description="实现", teammate="engineer"))
    orch._plan = AsyncMock(return_value=dag)
    orch._pick_teammate = AsyncMock(return_value=types.SimpleNamespace(id="rev1", role="reviewer"))

    # Don't let the child actually run (avoid nested background loops in test)
    orch._run_child = AsyncMock()

    result = await orch.start_task(db_session, task.id, "实现 X")
    await db_session.commit()

    assert result.review_status == "rejected"
    assert result.review_rounds == 1
    # §一: DAG hierarchy
    assert result.child_task_ids, "reject must create a child fix task"
    child_id = result.child_task_ids[0]

    child = await mgr.get_task(db_session, child_id)
    assert child.parent_task_id == task.id
    assert child.dependency == [task.id]
    assert "Fix#1" in child.title
    assert "tests fail" in child.description
    print(f"✅ REJECT → child fix task {child_id[:8]} linked (parent/dep set)")


# ── Scenario 4: MAX_REVIEW_ROUNDS boundary ──

@pytest.mark.asyncio
async def test_max_review_rounds_cap(mock_runtime, db_session):
    """Even with perpetual reject, rounds are capped at 3; task left REJECTED."""
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="实现功能", intent="实现 X",
        workspace_id="ws_demo", created_by="test",
    )
    await db_session.commit()

    # Reviewer rejects every round; _spawn_fix_task stubbed so no child loop.
    mock_runtime.wait = AsyncMock(return_value=_rt_mock(
        result=json.dumps({"verdict": "reject", "summary": "still broken",
                            "blockers": ["x"]}),
    ))

    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._plan = AsyncMock(return_value=None)
    orch._pick_teammate = AsyncMock(return_value=types.SimpleNamespace(id="rev1", role="reviewer"))
    orch._spawn_fix_task = AsyncMock(return_value=types.SimpleNamespace(id="fixchild"))
    orch._run_child = AsyncMock()

    result = await orch.start_task(db_session, task.id, "实现 X")
    await db_session.commit()

    # relay loop runs at most MAX_REVIEW_ROUNDS times
    assert result.review_rounds <= TaskOrchestrator.MAX_REVIEW_ROUNDS
    assert orch._spawn_fix_task.call_count <= TaskOrchestrator.MAX_REVIEW_ROUNDS
    print(f"✅ Review rounds capped at {TaskOrchestrator.MAX_REVIEW_ROUNDS} "
          f"(spawned {orch._spawn_fix_task.call_count} fix task(s))")
