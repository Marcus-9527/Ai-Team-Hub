"""Fail-fast + happy-path for TaskOrchestrator.start_task.

The real bug: an unassigned DAG node carried an empty teammate_id into the
runtime and silently hung the task at PLANNING until the 120s wait_for
timeout, with no error written. Fixed by a single guard after _assign_and_save
that covers every start_task caller (tasks.py, automation.py, demo.py).

Tests (no real API key needed):
  - happy-path-real-runtime: runs the REAL ExecutionRuntime + TaskExecutor +
    _run_task + detect_role -> run_pipeline -> the real planner/executor/
    reviewer steps. The ONLY mocked logic boundary is stream_ai_response
    (the LLM client). Three *environment stubs* (load_teammate / resolve_api_key
    / brain_loader) stand in for "a techlead teammate with a key and no brain
    rows exists in the DB" — they are data-prep, not business-logic mocks.
    This proves the real execution layer still completes after fail-fast was
    inserted into start_task.
  - fail-fast: no teammate -> FAILED + error persisted to DB (not silently lost).
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


# ── happy path: REAL runtime, only the LLM client is mocked ──

async def _fake_stream(system_prompt="", messages=None, **_):
    """Stand-in for stream_ai_response — the only real LLM boundary."""
    yield "done"


@pytest.mark.asyncio
async def test_happy_path_real_runtime(db_session):
    orch = TaskOrchestrator(runtime=None)  # force a real ExecutionRuntime

    task = await _make_task(db_session)
    await db_session.commit()

    node = DAGNode(description="do", selected_teammate_id=uuid.uuid4().hex)
    dag = DAGDefinition(name="d")
    dag.add_node(node)

    # Environment stubs — equivalent to "a techlead teammate with a key and no
    # brain rows exists in the DB". Not business-logic mocks.
    tm_dict = {
        "id": node.selected_teammate_id,
        "name": "TL",
        "role": "techlead",
        "model_provider": "openrouter",
        "model_name": "openrouter/auto",
        "api_key_ref": None,
        "system_prompt": "You are the TechLead. Decompose the goal.",
    }

    with patch("backend.services.ai_service.stream_ai_response", _fake_stream), \
         patch("backend.services.runtime.executor._load_teammate",
               new=AsyncMock(return_value=tm_dict)), \
         patch("backend.services.runtime.executor.resolve_api_key",
               new=AsyncMock(return_value=("fake-key", "", "openrouter", None))), \
         patch("backend.services.brain.brain_loader.get_brain_loader") as gbl:
        gbl.return_value.build_prompt = AsyncMock(return_value="")
        # plan + techlead_review are LLM calls — keep mocked.
        # _persist_dag / _create_steps are orchestration (DB writes),
        # run REAL so the executor sees real steps.
        with patch.object(orch, "_plan", new=AsyncMock(return_value=dag)), \
             patch.object(orch, "_techlead_review", new=AsyncMock()):
            result = await orch.start_task(db_session, task.id, "x")

    assert result.status == TaskStatus.COMPLETED


# ── fail-fast: no teammate -> FAILED + error persisted to DB ──

@pytest.mark.asyncio
async def test_failfast_on_unassigned_node(db_session):
    rt = AsyncMock()
    orch = TaskOrchestrator(runtime=rt)

    task = await _make_task(db_session)
    await db_session.commit()

    node = DAGNode(description="do something")
    dag = DAGDefinition(name="d")
    dag.add_node(node)

    with patch.object(orch, "_plan", new=AsyncMock(return_value=dag)), \
         patch.object(orch, "_techlead_review", new=AsyncMock()), \
         patch.object(orch, "_persist_dag", new=AsyncMock()), \
         patch.object(orch, "_create_steps", new=AsyncMock(return_value=task)), \
         patch.object(orch, "_execute", new=AsyncMock(return_value=task)):
        result = await orch.start_task(db_session, task.id, "x")

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
    rt.start.assert_not_called()
