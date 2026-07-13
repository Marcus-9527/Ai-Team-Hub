"""
test_pipeline_verification.py — QA-1: Verify full pipeline creates all DB entities.

After POST /api/tasks → background TaskOrchestrator → PlanningEngine → DAG
→ TeammateSelector → ExecutionRuntime, these entities MUST exist:

  - TaskModel (tasks)
  - DAGDefinitionModel (dag_definitions)
  - DAGNodeModel (dag_nodes)
  - Teammate assignment on step (task_steps.teammate_id)
  - TaskExecutionModel (task_executions)
  - TaskPlanModel (task_plans)

Each test exercises the real TaskOrchestrator with a mocked _plan
(fallback path bypassing real LLM) and mocked runtime submit/wait.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskExecutionModel,
    DAGDefinitionModel,
    DAGNodeModel,
    TaskPlanModel,
    Teammate,
    TaskStatus,
    TaskStepStatus,
)
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.runtime.executor import ExecutionRuntime


# ── Helpers ──


def _mock_rtask(*, task_id="m1", result="done", status="COMPLETED", error=""):
    return type("MockTask", (), {
        "id": task_id, "status": status, "result": result, "error": error,
    })()


def _make_dag(name="电商设计"):
    """Build a 2-node DAG — teammate assignment happens via TeammateSelector."""
    dag = DAGDefinition(name=name)
    n1 = DAGNode(description="需求分析", required_skills=["analysis"])
    n2 = DAGNode(description="架构设计", required_skills=["architecture"])
    dag.add_node(n1)
    dag.add_node(n2)
    return dag


@pytest.fixture
def mock_runtime():
    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(return_value="m1")
    r.wait = AsyncMock(return_value=_mock_rtask())
    return r


@pytest_asyncio.fixture
async def seed_teammates(db_session):
    """Create test teammates so TeammateSelector has profiles to assign."""
    t1 = Teammate(
        name="分析专家", role="analyst",
        skills=["analysis"],
        model_provider="openrouter", model_name="openrouter/auto",
    )
    t2 = Teammate(
        name="架构师", role="architect",
        skills=["architecture"],
        model_provider="openrouter", model_name="openrouter/auto",
    )
    db_session.add_all([t1, t2])
    await db_session.commit()
    for t in (t1, t2):
        await db_session.refresh(t)
    return [t1, t2]


# ── Test: All entity types exist after full pipeline ──


@pytest.mark.asyncio
async def test_all_entities_after_full_pipeline(db_session, seed_teammates, mock_runtime):
    """Full orchestrator pipeline creates every required DB entity."""
    mgr = TaskManager()

    # 1. Create task
    task = await mgr.create_task(
        db_session, title="电商", intent="设计电商网站", created_by="test",
    )
    await db_session.commit()
    task_id = task.id

    # 2. Run orchestrator with mocked plan + runtime
    dag = _make_dag()
    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._plan = AsyncMock(return_value=dag)

    result = await orch.start_task(db_session, task_id, "设计电商网站")
    await db_session.commit()

    # 3. Verify Task exists with proper status
    task_db = await db_session.get(TaskModel, task_id)
    assert task_db is not None, "Task must exist in DB"
    assert task_db.status == TaskStatus.COMPLETED, (
        f"Expected COMPLETED, got {task_db.status}"
    )
    print(f"  ✅ Task: id={task_id[:8]} status={task_db.status}")

    # 4. Verify DAGDefinition exists
    stmt = select(DAGDefinitionModel).limit(10)
    dags = (await db_session.execute(stmt)).scalars().all()
    assert len(dags) >= 1, "DAGDefinition must exist in DB"
    dag_db = dags[0]
    print(f"  ✅ DAGDefinition: id={dag_db.id[:8]} name={dag_db.name}")

    # 5. Verify DAGNode exists (linked to DAG)
    stmt = select(DAGNodeModel).where(DAGNodeModel.dag_id == dag_db.id)
    nodes = (await db_session.execute(stmt)).scalars().all()
    assert len(nodes) == 2, f"Expected 2 DAGNodes, got {len(nodes)}"
    for n in nodes:
        assert n.description, f"DAGNode {n.id[:8]} must have description"
    print(f"  ✅ DAGNode: {len(nodes)} nodes under DAG {dag_db.id[:8]}")

    # 6. Verify TaskSteps exist with teammate_id assigned
    steps = await mgr.state.list_steps(db_session, task_id)
    assert len(steps) == 2, f"Expected 2 steps, got {len(steps)}"
    for s in steps:
        assert s.teammate_id, (
            f"Step {s.id[:8]} must have teammate_id assigned"
        )
    print(f"  ✅ TaskStep: {len(steps)} steps, all with teammate_id")

    # 7. Verify TaskExecution records exist for each step
    for s in steps:
        exes = await mgr.state.list_executions(db_session, s.id)
        assert len(exes) >= 1, (
            f"Step {s.id[:8]} must have at least 1 execution record"
        )
        ex = exes[0]
        assert ex.maeos_task_id, (
            f"Execution {ex.id[:8]} must have maeos_task_id"
        )
    print(f"  ✅ TaskExecution: each step has execution record")

    # 8. Verify TaskPlan exists
    stmt = select(TaskPlanModel).where(TaskPlanModel.task_id == task_id)
    plans = (await db_session.execute(stmt)).scalars().all()
    assert len(plans) >= 1, "TaskPlan must exist in DB"
    print(f"  ✅ TaskPlan: {len(plans)} plan(s) for task")

    print(f"\n{'='*50}")
    print(f"✅ ALL DB ENTITIES VERIFIED: Task, DAGDefinition, DAGNode, "
          f"TaskStep, TaskExecution, TaskPlan")


# ── Test: DAG persisted even if execution fails ──


@pytest.mark.asyncio
async def test_dag_persisted_even_if_execution_fails(db_session, seed_teammates):
    """DAG is persisted to DB before execution starts — verify on failure."""
    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="测试", intent="测试任务", created_by="test",
    )
    await db_session.commit()
    task_id = task.id

    dag = _make_dag()
    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(return_value="m1")
    r.wait = AsyncMock(return_value=_mock_rtask(status="FAILED", error="fail"))

    orch = TaskOrchestrator(runtime=r)
    orch._plan = AsyncMock(return_value=dag)

    result = await orch.start_task(db_session, task_id, "测试")
    await db_session.commit()

    # DAG must exist even though execution failed
    stmt = select(DAGDefinitionModel).limit(10)
    dags = (await db_session.execute(stmt)).scalars().all()
    assert len(dags) >= 1, "DAGDefinition must exist even on execution failure"

    dag_db = dags[0]
    stmt = select(DAGNodeModel).where(DAGNodeModel.dag_id == dag_db.id)
    nodes = (await db_session.execute(stmt)).scalars().all()
    assert len(nodes) == 2, "DAGNodes must exist even on execution failure"

    print(f"  ✅ DAG persists through execution failure: "
          f"{dag_db.id[:8]}, {len(nodes)} nodes")
