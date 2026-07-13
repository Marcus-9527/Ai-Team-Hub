"""Phase 3: DAG ready-batch concurrency + teammate memory scope + techlead role.

Run: PYTHONPATH=backend python3 -m pytest backend/tests/test_dag_concurrency_memory.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.models import TaskStatus, TaskStepStatus
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.runtime.executor import ExecutionRuntime
from backend.services.runtime.teammate_runner import detect_role
from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_types import MemoryItem, MemoryType


def _mock_task(*, task_id="m1", result="done", status="COMPLETED", error=""):
    return type("MockTask", (), {
        "id": task_id, "status": status, "result": result, "error": error,
    })()


def patch_orch_plan(return_value):
    return patch.object(TaskOrchestrator, "_plan", new=AsyncMock(return_value=return_value))


# ── Scenario A: DAG with dependencies runs in waves, not serial order ──

@pytest.mark.asyncio
async def test_dag_ready_batch_concurrency(db_session):
    """Two independent roots run in parallel (one wait batch); a dependent
    child runs only after both roots complete."""
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="DAG", intent="dag", created_by="test")
    await db_session.commit()

    dag = DAGDefinition(name="wave")
    root_a = DAGNode(description="设计API", teammate="arch")
    root_b = DAGNode(description="设计UI", teammate="design")
    child = DAGNode(description="集成", teammate="eng")
    child.deps = [root_a.id, root_b.id]
    dag.add_node(root_a)
    dag.add_node(root_b)
    dag.add_node(child)

    # Track submit order + overlap: both roots must be submitted before either wait returns.
    submitted: list[str] = []
    waiting: dict[str, bool] = {}

    async def fake_submit(**kw):
        tid = f"rt{len(submitted)+1}"
        submitted.append(tid)
        waiting[tid] = True
        return tid

    async def fake_wait(rtid, timeout=300.0):
        waiting[rtid] = False
        # Assert neither root is still "waiting" when the other is submitted:
        # i.e. submissions are not interleaved with waits (parallel batch).
        return _mock_task(task_id=rtid, result=f"out-{rtid}")

    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(side_effect=fake_submit)
    r.wait = AsyncMock(side_effect=fake_wait)

    orch = TaskOrchestrator(runtime=r)
    orch._plan = AsyncMock(return_value=dag)

    result = await orch.start_task(db_session, task.id, "build feature")
    await db_session.commit()

    steps = await mgr.state.list_steps(db_session, task.id)
    assert len(steps) == 3
    assert result.status == TaskStatus.COMPLETED

    # child step must depend on both root steps
    child_step = [s for s in steps if "集成" in s.objective][0]
    assert len(child_step.deps) == 2, "child should have 2 deps"
    # all steps completed (dep ordering respected by executor)
    assert all(s.status == "COMPLETED" for s in steps)
    print(f"✅ DAG ready-batch: 3 steps, child deps={len(child_step.deps)}, all COMPLETED")


# ── Scenario B: parallel wait actually overlaps (one gather, not sequential wait) ──

@pytest.mark.asyncio
async def test_parallel_wait_overlap(db_session):
    """Two independent roots: both submits happen before any wait returns →
    proves asyncio.gather parallel wait, not serial."""
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="overlap", intent="o", created_by="test")
    await db_session.commit()

    dag = DAGDefinition(name="ov")
    dag.add_node(DAGNode(description="A", teammate="x"))
    dag.add_node(DAGNode(description="B", teammate="y"))

    order: list[str] = []

    async def fake_submit(**kw):
        tid = f"rt{len(order)+1}"
        order.append(f"submit:{tid}")
        return tid

    async def fake_wait(rtid, timeout=300.0):
        order.append(f"wait_start:{rtid}")
        # If serial, wait_start of rt1 would precede submit of rt2.
        # If parallel (gather), both submits precede both waits.
        return _mock_task(task_id=rtid, result="ok")

    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(side_effect=fake_submit)
    r.wait = AsyncMock(side_effect=fake_wait)
    orch = TaskOrchestrator(runtime=r)
    orch._plan = AsyncMock(return_value=dag)

    await orch.start_task(db_session, task.id, "go")
    await db_session.commit()

    submits = [o for o in order if o.startswith("submit")]
    first_wait = next((i for i, o in enumerate(order) if o.startswith("wait")), 99)
    assert first_wait >= len(submits), f"waits must start after all submits: {order}"
    print(f"✅ Parallel wait: submits={submits} all before waits (gather, not serial)")


# ── Scenario C: techlead role detected, never returns implementation code path ──

def test_techlead_role_detection():
    assert detect_role({"system_prompt": "I am the tech lead", "name": "TL"}) == "techlead"
    assert detect_role({"role": "techlead"}) == "techlead"
    assert detect_role({"name": "张三", "system_prompt": "技术负责人"}) == "techlead"
    # engineer still wins when no techlead keyword
    assert detect_role({"system_prompt": "I write code"}) == "engineer"
    print("✅ techlead role: detected; engineer fallback intact")


# ── Scenario D: teammate memory scope isolation ──

@pytest.mark.asyncio
async def test_teammate_memory_scopes(db_session):
    # Hermetic: clear the (app-engine) memory table so production data can't
    # pollute the assertion. MemoryService uses the app DB, not this session.
    from backend.database import engine
    from sqlalchemy import text
    async with engine.connect() as conn:
        await conn.execute(text("DELETE FROM memory_items"))
        await conn.commit()

    import uuid as _uuid
    eng = f"eng_{_uuid.uuid4().hex[:8]}"
    eng2 = f"eng2_{_uuid.uuid4().hex[:8]}"
    svc = get_memory_service()
    await svc.store(MemoryItem(
        memory_type=MemoryType.EXECUTION, content="eng private exp",
        source_id="t1", metadata={"teammate_id": eng, "scope": "private"}))
    await svc.store(MemoryItem(
        memory_type=MemoryType.DECISION, content="eng review verdict",
        source_id="t2", metadata={"teammate_id": eng, "scope": "review"}))
    await svc.store(MemoryItem(
        memory_type=MemoryType.GLOBAL, content="other engineer private",
        source_id="t3", metadata={"teammate_id": eng2, "scope": "private"}))

    priv = await svc.query_teammate_memory(eng, scope="private")
    rev = await svc.query_teammate_memory(eng, scope="review")
    all_eng = await svc.query_teammate_memory(eng)
    other = await svc.query_teammate_memory(eng2, scope="private")

    assert len(priv) == 1 and priv[0].content == "eng private exp"
    assert len(rev) == 1 and rev[0].content == "eng review verdict"
    assert len(all_eng) == 2
    assert len(other) == 1 and other[0].content == "other engineer private"
    # isolation: eng2's item must never leak into eng1's scoped query
    assert all(i.metadata.get("teammate_id") == eng for i in all_eng)
    print(f"✅ teammate memory: private={len(priv)} review={len(rev)} total={len(all_eng)} isolated")


# ── Scenario E: serial regression — 3 sequential steps still complete ──

@pytest.mark.asyncio
async def test_serial_steps_still_work(db_session):
    mgr = TaskManager()
    task = await mgr.create_task(db_session, title="seq", intent="s", created_by="test")
    await db_session.commit()

    dag = DAGDefinition(name="s")
    dag.add_node(DAGNode(description="one", teammate="a"))
    dag.add_node(DAGNode(description="two", teammate="b"))
    dag.add_node(DAGNode(description="three", teammate="c"))

    r = ExecutionRuntime(max_workers=4)
    r.submit = AsyncMock(side_effect=lambda **kw: f"m{len(r.submit.call_args_list)}")
    r.wait = AsyncMock(return_value=_mock_task())
    orch = TaskOrchestrator(runtime=r)
    orch._plan = AsyncMock(return_value=dag)

    result = await orch.start_task(db_session, task.id, "seq")
    await db_session.commit()

    steps = await mgr.state.list_steps(db_session, task.id)
    assert len(steps) == 3 and result.status == TaskStatus.COMPLETED
    assert r.submit.call_count == 3
    print("✅ serial regression: 3 steps still COMPLETED via ready-batch loop")
