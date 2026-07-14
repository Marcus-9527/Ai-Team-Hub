"""Phase 25: TechLead Activation tests.

Covers:
  1. _techlead_review is called and saves structured decision to task
  2. Decision persistence (techlead_decision JSON field)
  3. _techlead_relay writes brain fragment + task summary
"""

import json
import types

import pytest
from unittest.mock import AsyncMock, patch

from backend.models import TaskStatus, Teammate, gen_uuid
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.task.task_executor import TaskExecutor
from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.runtime.executor import ExecutionRuntime

pytestmark = pytest.mark.asyncio


def _rt_mock(*, result="{}", status="COMPLETED"):
    return types.SimpleNamespace(
        id="rt1", status=status, result=result,
        git_commit="", review_status="pending", error="",
    )


@pytest.fixture
def mock_runtime():
    r = ExecutionRuntime(max_workers=4)
    r.start = AsyncMock()
    r.submit = AsyncMock(return_value="rt1")
    r.wait = AsyncMock(return_value=_rt_mock())
    return r


# ── Scenario 1: TechLead review saves decision ──

async def test_techlead_review_saves_decision(mock_runtime, db_session):
    """_techlead_review calls execute_direct → parses JSON → saves to task."""
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="加缓存", intent="为 API 加缓存",
        workspace_id="ws_demo", created_by="test",
    )
    # Create a techlead teammate so _pick_teammate finds one
    tl = Teammate(id=gen_uuid(), name="技术负责人", role="techlead",
                  system_prompt="You are TechLead", avatar_emoji="👑",
                  model_provider="openrouter", model_name="openrouter/auto")
    db_session.add(tl)
    await db_session.commit()

    decision = {
        "analysis": "Simple caching task",
        "risk_level": "LOW",
        "risk_factors": ["cache invalidation"],
        "teammate_recommendations": [
            {"step": 1, "teammate": "工程师", "reasoning": "best fit"}
        ],
        "overall_reasoning": "Engineer team is best equipped",
    }
    mock_runtime.wait = AsyncMock(return_value=_rt_mock(result=json.dumps(decision)))

    dag = DAGDefinition(name="impl")
    dag.add_node(DAGNode(description="实现缓存", teammate="engineer"))

    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._pick_teammate = AsyncMock(return_value=types.SimpleNamespace(
        id=tl.id, name="技术负责人", role="techlead",
    ))
    await orch._techlead_review(db_session, task, dag, "为 API 加缓存")

    assert task.techlead_decision is not None, "decision should be set"
    assert task.techlead_decision["analysis"] == "Simple caching task"
    assert task.techlead_decision["risk_level"] == "LOW"
    assert len(task.techlead_decision["risk_factors"]) == 1
    assert task.techlead_decision["overall_reasoning"] is not None
    print("✅ TechLead review: decision saved to task")


# ── Scenario 2: TechLead review is idempotent when no TL teammate ──

async def test_techlead_review_no_teammate_skips_gracefully(mock_runtime, db_session):
    """No techlead teammate → review skipped, task unchanged."""
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="测试", intent="测试", workspace_id="ws_demo", created_by="test",
    )
    await db_session.commit()

    dag = DAGDefinition(name="test")
    dag.add_node(DAGNode(description="测试步骤", teammate="engineer"))

    orch = TaskOrchestrator(runtime=mock_runtime)
    await orch._techlead_review(db_session, task, dag, "测试")

    assert task.techlead_decision is None
    print("✅ TechLead review: no teammate → graceful skip")


# ── Scenario 3: TechLead relay writes summary + Brain ──

async def test_techlead_relay_writes_summary(mock_runtime, db_session):
    """_techlead_relay writes task.techlead_summary from step outputs."""
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="缓存优化", intent="优化缓存",
        workspace_id="ws_demo", created_by="test",
    )
    await db_session.commit()

    # Create steps with output
    for i in range(2):
        step = await mgr.state.create_step(
            db_session, task_id=task.id, order=i + 1,
            objective=f"步骤{i+1}", teammate_id=f"eng{i}",
        )
        step.output = f"Output from step {i+1}: done"
    await db_session.commit()

    orch = TaskOrchestrator(runtime=mock_runtime)
    tl = types.SimpleNamespace(id="tl1", name="TechLead", role="techlead")
    orch._pick_teammate = AsyncMock(return_value=tl)

    await orch._techlead_relay(db_session, task)

    assert task.techlead_summary, "summary should be non-empty"
    assert "Step 1" in task.techlead_summary
    assert "Step 2" in task.techlead_summary
    print("✅ TechLead relay: summary written to task")


# ── Scenario 4: Full flow — TechLead review via start_task ──

async def test_techlead_full_flow(mock_runtime, db_session):
    """Full start_task: plan → review → execute → relay."""
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="API 重构", intent="重构 API 接口",
        workspace_id="ws_demo", created_by="test",
    )
    # Create techlead teammate
    tl = Teammate(id=gen_uuid(), name="技术负责人", role="techlead",
                  system_prompt="You are TechLead", avatar_emoji="👑",
                  model_provider="openrouter", model_name="openrouter/auto")
    db_session.add(tl)
    await db_session.commit()

    decision = {
        "analysis": "API refactoring needed",
        "risk_level": "MEDIUM",
        "risk_factors": ["breaking changes"],
        "teammate_recommendations": [
            {"step": 1, "teammate": "工程师", "reasoning": "owns codebase"}
        ],
        "overall_reasoning": "Engineer team recommended",
    }
    mock_runtime.wait = AsyncMock(return_value=_rt_mock(result=json.dumps(decision)))

    dag = DAGDefinition(name="refactor")
    dag.add_node(DAGNode(description="重构", teammate="engineer"))

    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._plan = AsyncMock(return_value=dag)
    orch._pick_teammate = AsyncMock(return_value=types.SimpleNamespace(
        id=tl.id, name="技术负责人", role="techlead",
    ))
    # Skip execution + relay — we're testing the review phase here
    orch._execute = AsyncMock(return_value=task)
    orch._techlead_relay = AsyncMock()
    orch._review_relay = AsyncMock()

    result = await orch.start_task(db_session, task.id, "重构 API 接口")
    await db_session.commit()

    assert result.techlead_decision is not None
    assert result.techlead_decision["analysis"] == "API refactoring needed"
    print("✅ Full flow: TechLead review decision persisted")
