"""test_task_claim_integration.py — Step 2: claim-aware assignment (A, B, C).

No DB / no real LLM for the claim-logic tests (B's registration is asserted
against the in-memory state manager). One real-run test proves the winner
executes exactly once.

Covers:
  A — existing claim → _assign_and_save pins the claimed teammate, skips selector
  B — create_teammate registers teammate as available in state manager
  C — start_task awaits the competition (no fire-and-forget race); runs once
"""
import pytest
from unittest.mock import AsyncMock, patch
import uuid

from sqlalchemy import select

from backend.models import TaskStatus, TaskModel
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.autonomous.teammate_state import get_state_manager
from backend.services.autonomous.task_claim import get_claim_manager


@pytest.fixture(autouse=True)
def reset_singletons():
    """Isolate process-wide claim + state singletons between tests."""
    cm = get_claim_manager()
    cm._claims = {}
    cm._owners = {}
    get_state_manager()._states = {}
    yield
    cm._claims = {}
    cm._owners = {}
    get_state_manager()._states = {}


async def _seed_state(count: int):
    sm = get_state_manager()
    tids = []
    for i in range(count):
        tid = f"tm_{i}_{uuid.uuid4().hex[:6]}"
        await sm.set_active(tid)
        tids.append(tid)
    return tids


# ── B: registration on create ──

@pytest.mark.asyncio
async def test_create_teammate_registers_available(db_session):
    from backend.routes.teammates import create_teammate
    sm = get_state_manager()
    data = {
        "name": "B-test", "role": "engineer",
        "model_provider": "openrouter", "model_name": "openrouter/auto",
    }
    res = await create_teammate(data, db_session)
    tid = res["id"]
    st = await sm.get(tid)
    assert st is not None and st.is_available


# ── A: existing claim honored, selector skipped ──

@pytest.mark.asyncio
async def test_assign_honors_existing_claim(db_session):
    tids = await _seed_state(3)
    task = await TaskManager().create_task(
        db_session, title="t", description="x", created_by="u")
    await db_session.commit()

    node = DAGNode(description="do")
    dag = DAGDefinition(name="d")
    dag.add_node(node)

    orch = TaskOrchestrator()
    winner = tids[0]
    await get_claim_manager().claim(task.id, winner, teammate_name=winner,
                                     reason="preset")

    with patch.object(orch, "_plan", new=AsyncMock(return_value=dag)), \
         patch.object(orch, "_techlead_review", new=AsyncMock()), \
         patch.object(orch, "_persist_dag", new=AsyncMock()), \
         patch.object(orch, "_create_steps", new=AsyncMock(return_value=task)), \
         patch.object(orch, "_execute", new=AsyncMock(return_value=task)):
        await orch.start_task(db_session, task.id, "x")

    assert node.selected_teammate_id == winner
    assert node.teammate == winner


@pytest.mark.asyncio
async def test_assign_falls_back_to_selector_when_no_available(db_session):
    # New semantics: a claim only exists if a teammate was available to race.
    # "No claim" therefore means NO available teammates → selector/round-robin
    # is the fallback. Seed a DB teammate + patch selector to return it.
    db_tid = f"db_{uuid.uuid4().hex[:8]}"
    from backend.models import Teammate
    db_session.add(Teammate(id=db_tid, name="S", role="engineer",
                    model_provider="openrouter", model_name="openrouter/auto",
                    system_prompt="x", skills=[]))
    await db_session.commit()

    task = await TaskManager().create_task(
        db_session, title="t", description="x", created_by="u")
    await db_session.commit()

    node = DAGNode(description="do", required_skills=["python"])
    dag = DAGDefinition(name="d")
    dag.add_node(node)

    orch = TaskOrchestrator()
    # state manager empty → run_claim_competition makes no claim → A skipped
    with patch.object(orch, "_plan", new=AsyncMock(return_value=dag)), \
         patch.object(orch, "_techlead_review", new=AsyncMock()), \
         patch.object(orch, "_persist_dag", new=AsyncMock()), \
         patch.object(orch, "_create_steps", new=AsyncMock(return_value=task)), \
         patch.object(orch, "_execute", new=AsyncMock(return_value=task)), \
         patch("backend.services.task.task_orchestrator.TeammateSelector"
               ".recommend_by_skills",
               new=AsyncMock(return_value=[type("P", (), {"id": db_tid, "name": "S"})])):
        await orch.start_task(db_session, task.id, "x")

    # no claim → selector assigns db_tid (behavior unchanged)
    assert node.selected_teammate_id == db_tid


# ── C + single execution: real run, wakeup winner executes once ──

@pytest.mark.asyncio
async def test_claim_winner_executes_once(db_session):
    tids = await _seed_state(2)
    orch = TaskOrchestrator(runtime=None)  # REAL ExecutionRuntime
    task = await _make_task(db_session)
    await db_session.commit()

    winner = tids[0]
    node = DAGNode(description="do")  # unassigned → A will assign winner
    dag = DAGDefinition(name="d")
    dag.add_node(node)

    tm_dict = {
        "id": winner, "name": "TL", "role": "techlead",
        "model_provider": "openrouter", "model_name": "openrouter/auto",
        "api_key_ref": None, "system_prompt": "x",
    }
    with patch("backend.services.pipeline.stream_ai_response",
               new=lambda *a, **k: _fake_stream()), \
         patch("backend.services.runtime.executor._load_teammate",
               new=AsyncMock(return_value=tm_dict)), \
         patch("backend.services.runtime.teammate_runner.resolve_api_key",
               new=AsyncMock(return_value=("fake-key", "", "openrouter", None))), \
         patch("backend.services.brain.brain_loader.get_brain_loader") as gbl:
        gbl.return_value.build_prompt = AsyncMock(return_value="")
        with patch.object(orch, "_plan", new=AsyncMock(return_value=dag)), \
             patch.object(orch, "_techlead_review", new=AsyncMock()):
            await get_claim_manager().claim(task.id, winner, teammate_name=winner)
            result = await orch.start_task(db_session, task.id, "x")

    assert result.status == TaskStatus.COMPLETED
    claims = await get_claim_manager().get_claims(task.id)
    assert len([c for c in claims if c.status == "claimed"]) == 1
    assert any(c.teammate_id == winner for c in claims)


async def _fake_stream(system_prompt="", messages=None, **_):
    yield "done"


def _make_task(db, title="t"):
    return TaskManager().create_task(
        db, title=title, description="x", created_by="u", priority=2)
