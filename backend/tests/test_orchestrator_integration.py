"""Orchestrator integration tests — exercises real TaskExecutor with mocked runtime."""
import pytest
from unittest.mock import AsyncMock, patch

from backend.models import TaskStatus
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.runtime.executor import ExecutionRuntime


def _mock_task(*, task_id="m1", result="done", status="COMPLETED", error=""):
    return type("MockTask", (), {
        "id": task_id, "status": status, "result": result, "error": error,
    })()


@pytest.fixture
def mock_runtime():
    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(return_value="m1")
    r.wait = AsyncMock(return_value=_mock_task())
    return r


# ── Scenario 1: Empty goal ──

@pytest.mark.asyncio
async def test_empty_goal(db_session):
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="", intent="", created_by="test")
    await db_session.commit()

    with patch_orch_plan(return_value=None):
        result = await TaskOrchestrator().start_task(db_session, task.id, goal="")
    assert result.status == TaskStatus.PLANNING
    print("✅ Empty goal → stays PLANNING")


# ── Scenario 2: Plan fails, no fallback ──

@pytest.mark.asyncio
async def test_plan_fails(db_session):
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="test", intent="test", created_by="test")
    await db_session.commit()

    with patch_orch_plan(return_value=None):
        result = await TaskOrchestrator().start_task(db_session, task.id, goal="test")
    assert result.status == TaskStatus.PLANNING
    print("✅ Plan fails → stays PLANNING")


# ── Scenario 3: Plan + save + create_steps (skip _execute) ──

@pytest.mark.asyncio
async def test_plan_save_create_steps(db_session):
    """Mock _execute → skips execution. Verifies plan persists correctly."""
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="电商", intent="设计电商网站", created_by="test")
    await db_session.commit()

    dag = DAGDefinition(name="电商设计")
    dag.add_node(DAGNode(description="需求分析", teammate="pm"))
    dag.add_node(DAGNode(description="架构设计", teammate="arch"))

    async def noop_execute(self, db, t):
        return t

    orch = TaskOrchestrator()
    with patch_orch_plan(return_value=dag), \
         patch.object(TaskOrchestrator, "_execute", new=noop_execute):
        result = await orch.start_task(db_session, task.id, "设计电商网站")
        await db_session.commit()

    steps = await mgr.state.list_steps(db_session, task.id)
    print(f"Status: {result.status}, Steps: {len(steps)}")
    for s in steps:
        print(f"  step #{s.order}: {s.objective} [{s.status}]")
    assert len(steps) == 2
    assert result.status == TaskStatus.ASSIGNED
    print("✅ Plan→save→create_steps OK (status ASSIGNED)")


# ── Scenario 4: Full orchestrator + real executor (mocked runtime) ──

@pytest.mark.asyncio
async def test_full_executor(mock_runtime, db_session):
    """Exercises the actual TaskExecutor.execute_task with mocked submit/wait."""
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="电商", intent="设计电商网站", created_by="test")
    await db_session.commit()

    dag = DAGDefinition(name="电商设计")
    dag.add_node(DAGNode(description="需求分析", teammate="pm"))
    dag.add_node(DAGNode(description="架构设计", teammate="arch"))

    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._plan = AsyncMock(return_value=dag)

    result = await orch.start_task(db_session, task.id, "设计电商网站")
    await db_session.commit()

    steps = await mgr.state.list_steps(db_session, task.id)
    print(f"Status: {result.status}, Steps: {len(steps)}")
    for s in steps:
        print(f"  step #{s.order}: {s.objective} [{s.status}] output={s.output[:50]!r}")
    assert len(steps) == 2
    assert result.status == TaskStatus.COMPLETED
    assert all(s.output for s in steps), "Steps should have output"
    print("✅ Full executor OK — COMPLETED, 2 steps with output")


# ── Scenario 5: Step failure (runtime returns error) ──

@pytest.mark.asyncio
async def test_step_failure(db_session):
    """Runtime returns error → executor should handle step failure."""
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="电商", intent="设计", created_by="test")
    await db_session.commit()

    dag = DAGDefinition(name="电商设计")
    dag.add_node(DAGNode(description="需求分析", teammate="pm"))

    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(return_value="m1")
    r.wait = AsyncMock(return_value=_mock_task(status="FAILED", error="LLM timeout"))

    orch = TaskOrchestrator(runtime=r)
    orch._plan = AsyncMock(return_value=dag)

    result = await orch.start_task(db_session, task.id, "设计")
    await db_session.commit()

    steps = await mgr.state.list_steps(db_session, task.id)
    assert len(steps) == 1
    assert result.status == TaskStatus.FAILED, f"Got {result.status}"
    print(f"✅ Step failure → FAILED: {len(steps)} step(s), status={result.status}")


# ── Scenario 6: Multiple steps, sequential execution ──

@pytest.mark.asyncio
async def test_multiple_steps(db_session):
    """3 sequential steps all complete."""
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="全栈电商", intent="开发全栈电商", created_by="test")
    await db_session.commit()

    call_count = 0

    async def counting_wait(*a, **kw):
        nonlocal call_count
        call_count += 1
        return _mock_task(task_id=f"m{call_count}", result=f"Step{call_count} done")

    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(side_effect=lambda **kw: f"m{call_count + 1}")
    r.wait = counting_wait

    dag = DAGDefinition(name="电商开发")
    dag.add_node(DAGNode(description="前端开发", teammate="fe"))
    dag.add_node(DAGNode(description="后端开发", teammate="be"))
    dag.add_node(DAGNode(description="部署上线", teammate="ops"))

    orch = TaskOrchestrator(runtime=r)
    orch._plan = AsyncMock(return_value=dag)

    result = await orch.start_task(db_session, task.id, "开发电商")
    await db_session.commit()

    steps = await mgr.state.list_steps(db_session, task.id)
    assert len(steps) == 3
    assert result.status == TaskStatus.COMPLETED
    assert call_count == 3, f"Expected 3 submits, got {call_count}"
    for s in steps:
        assert s.output and s.status == "COMPLETED", f"Step {s.order}: {s.status}"
    print(f"✅ 3 steps OK — {call_count} submits, all COMPLETED")


# ── Helpers ──

def patch_orch_plan(**kwargs):
    """Convenience: patch TaskOrchestrator._plan with an AsyncMock."""
    return patch.object(TaskOrchestrator, "_plan", new=AsyncMock(**kwargs))
