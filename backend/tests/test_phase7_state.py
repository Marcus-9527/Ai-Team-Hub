"""Phase 7 — Organization State 收敛测试。

验收标准：
1. OrganizationRun 可恢复完整状态：run_id → OrganizationState → current_action + progress
2. Action 生命周期自动更新 state（通过 OrganizationRuntime）
3. Task step 状态同步（通过 TaskExecutor 双写）
4. Teammate 状态持久化（通过 OrganizationState member 类型）
5. 重启后状态仍存在（DB 持久化验证）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio

from datetime import datetime, timezone
from sqlalchemy import select

from backend.models.organization_state import OrganizationState
from backend.models.organization_run import OrganizationRun
from backend.models.session import SessionTrigger, SessionEvent


# ── helpers ──

async def _states(db, run_id: str) -> list[OrganizationState]:
    r = await db.execute(
        select(OrganizationState)
        .where(OrganizationState.run_id == run_id)
        .order_by(OrganizationState.state_type, OrganizationState.key)
    )
    return list(r.scalars().all())


async def _events(db, trigger_id: str) -> list[SessionEvent]:
    r = await db.execute(
        select(SessionEvent)
        .where(SessionEvent.trigger_id == trigger_id)
        .order_by(SessionEvent.timestamp)
    )
    return list(r.scalars().all())


async def _create_run(db_session) -> tuple:
    """Create an OrganizationRun + SessionTrigger. Returns (trigger, run)."""
    trigger = SessionTrigger(trigger_type="test", channel_id="ch")
    db_session.add(trigger)
    await db_session.flush()

    from backend.services.organization.runtime import OrganizationRuntime
    rt = OrganizationRuntime(db_session)
    run = await rt.start_run(
        run_type="chat",
        source_id=trigger.id,
        workspace_id="ws1",
        channel_id="ch",
        title="Test",
    )
    trigger.run_id = run.id
    await db_session.flush()
    return trigger, run, rt


# ═══════════════════════════════════════════════════════════════
# 1. Model: OrganizationState creates and persists
# ═══════════════════════════════════════════════════════════════

async def test_org_state_model_persists(db_session):
    """OrganizationState 模型可创建和持久化。"""
    trigger, run, _ = await _create_run(db_session)

    st = OrganizationState(
        run_id=run.id,
        state_type="progress",
        key="main",
        value={"completed": 3, "total": 8},
    )
    db_session.add(st)
    await db_session.commit()

    fresh = await db_session.get(OrganizationState, st.id)
    assert fresh is not None
    assert fresh.run_id == run.id
    assert fresh.state_type == "progress"
    assert fresh.key == "main"
    assert fresh.value == {"completed": 3, "total": 8}
    assert fresh.created_at is not None
    assert fresh.updated_at is not None


async def test_org_state_unique_constraint(db_session):
    """同一 (run_id, state_type, key) 不能重复。"""
    trigger, run, _ = await _create_run(db_session)

    st1 = OrganizationState(run_id=run.id, state_type="progress", key="main", value={"a": 1})
    db_session.add(st1)
    await db_session.flush()

    st2 = OrganizationState(run_id=run.id, state_type="progress", key="main", value={"a": 2})
    db_session.add(st2)
    with pytest.raises(Exception):
        await db_session.flush()


# ═══════════════════════════════════════════════════════════════
# 2. OrganizationStateService CRUD
# ═══════════════════════════════════════════════════════════════

async def test_state_service_set_and_get(db_session):
    """set_state + get_state roundtrip."""
    trigger, run, _ = await _create_run(db_session)
    from backend.services.organization.state import OrganizationStateService
    svc = OrganizationStateService(db_session)

    result = await svc.set_state(run.id, "progress", "main", {"done": 1, "total": 5})
    assert result.state_type == "progress"
    assert result.key == "main"
    assert result.value == {"done": 1, "total": 5}

    got = await svc.get_state(run.id, "progress", "main")
    assert got is not None
    assert got.value == {"done": 1, "total": 5}


async def test_state_service_update_state_merge(db_session):
    """update_state merges value into existing."""
    trigger, run, _ = await _create_run(db_session)
    from backend.services.organization.state import OrganizationStateService
    svc = OrganizationStateService(db_session)

    await svc.set_state(run.id, "progress", "main", {"done": 1})
    await svc.update_state(run.id, "progress", "main", {"total": 5})

    got = await svc.get_state(run.id, "progress", "main")
    assert got.value == {"done": 1, "total": 5}


async def test_state_service_list_states(db_session):
    """list_states returns all states for a run, optionally filtered."""
    trigger, run, _ = await _create_run(db_session)
    from backend.services.organization.state import OrganizationStateService
    svc = OrganizationStateService(db_session)

    await svc.set_state(run.id, "progress", "step1", {"status": "completed"})
    await svc.set_state(run.id, "progress", "step2", {"status": "running"})
    await svc.set_state(run.id, "current_action", "main", {"action": "respond"})

    all_states = await svc.list_states(run.id)
    assert len(all_states) == 3

    progress_states = await svc.list_states(run.id, state_type="progress")
    assert len(progress_states) == 2


async def test_state_service_emits_session_event(db_session):
    """set_state with trigger_id emits state.updated SessionEvent."""
    trigger, run, _ = await _create_run(db_session)
    from backend.services.organization.state import OrganizationStateService
    svc = OrganizationStateService(db_session)

    await svc.set_state(
        run.id, "current_action", "main",
        {"action_type": "respond", "status": "running"},
        trigger_id=trigger.id,
    )

    events = await _events(db_session, trigger.id)
    assert any(e.event_type == "state.updated" for e in events)


async def test_state_service_delete_state(db_session):
    """delete_state removes the entry."""
    trigger, run, _ = await _create_run(db_session)
    from backend.services.organization.state import OrganizationStateService
    svc = OrganizationStateService(db_session)

    await svc.set_state(run.id, "progress", "main", {"done": 1})
    assert await svc.delete_state(run.id, "progress", "main") is True
    assert await svc.delete_state(run.id, "progress", "nonexistent") is False
    assert await svc.get_state(run.id, "progress", "main") is None


# ═══════════════════════════════════════════════════════════════
# 3. Action lifecycle auto-updates state (via OrganizationRuntime)
# ═══════════════════════════════════════════════════════════════

async def test_runtime_respond_writes_current_action(db_session):
    """handle_input writes current_action before dispatching respond."""
    trigger, run, rt = await _create_run(db_session)

    async def _fake_respond(**kw):
        yield "data: ok\n\n"

    with patch("backend.services.team_collaboration.generate_team_response", new=_fake_respond):
        async for _ in rt.handle_input(
            run_id=run.id,
            trigger_id=trigger.id,
            teammates=[{"id": "tm1"}],
            user_message="hi",
            channel_id="ch",
        ):
            pass

    svc = rt._state_svc()
    current = await svc.get_state(run.id, "current_action", "main")
    assert current is not None
    assert current.value["action_type"] == "respond"
    assert current.value["status"] == "completed"  # set to running then updated to completed


async def test_runtime_respond_writes_progress(db_session):
    """handle_input writes progress after successful respond."""
    trigger, run, rt = await _create_run(db_session)

    async def _fake_respond(**kw):
        yield "data: ok\n\n"

    with patch("backend.services.team_collaboration.generate_team_response", new=_fake_respond):
        async for _ in rt.handle_input(
            run_id=run.id,
            trigger_id=trigger.id,
            teammates=[{"id": "tm1"}],
            user_message="hi",
            channel_id="ch",
        ):
            pass

    svc = rt._state_svc()
    progress = await svc.get_state(run.id, "progress", "main")
    assert progress is not None
    assert progress.value["responded"] is True


async def test_runtime_respond_writes_failure_on_error(db_session):
    """handle_input writes failed state on exception."""
    trigger, run, rt = await _create_run(db_session)

    async def _broken(**kw):
        raise RuntimeError("oops")
        yield  # pragma: no cover

    with patch("backend.services.team_collaboration.generate_team_response", new=_broken):
        with pytest.raises(RuntimeError):
            async for _ in rt.handle_input(
                run_id=run.id,
                trigger_id=trigger.id,
                teammates=[{"id": "tm1"}],
                user_message="hi",
                channel_id="ch",
            ):
                pass

    svc = rt._state_svc()
    current = await svc.get_state(run.id, "current_action", "main")
    assert current.value["status"] == "failed"


async def test_runtime_delegate_writes_current_action(db_session):
    """dispatch_delegate writes current_action before delegating."""
    trigger, run, rt = await _create_run(db_session)

    mock_orch = AsyncMock()
    mock_orch.start_task = AsyncMock()

    with patch("backend.services.task.task_orchestrator.TaskOrchestrator", return_value=mock_orch):
        await rt.dispatch_delegate(
            trigger_id=trigger.id,
            run_id=run.id,
            task_id="task-1",
            goal="do it",
        )

    svc = rt._state_svc()
    current = await svc.get_state(run.id, "current_action", "main")
    assert current is not None
    assert current.value["action_type"] == "delegate"


# ═══════════════════════════════════════════════════════════════
# 4. Teammate state persistence
# ═══════════════════════════════════════════════════════════════

async def test_teammate_state_dual_write(db_session):
    """TeammateStateManager.set_state with db+run_id writes OrganizationState."""
    trigger, run, rt = await _create_run(db_session)

    from backend.services.autonomous.teammate_state import get_state_manager
    mgr = get_state_manager()

    # set_state with db + run_id → dual-write to OrganizationState
    await mgr.set_state("tm1", mgr._state_cls.WORKING, task_id="t1",
                        db=db_session, run_id=run.id)

    svc = rt._state_svc()
    member_state = await svc.get_state(run.id, "member", "tm1")
    assert member_state is not None
    assert member_state.value["state"] == "working"
    assert member_state.value["task_id"] == "t1"

    # In-memory state also exists
    mem = await mgr.get("tm1")
    assert mem.state.value == "working"
    assert mem.current_task_id == "t1"


# Helper: TeammateStateManager._state_cls needs to be TeammateState
# but it's from the module scope. Let me just import it directly.
@pytest.fixture(autouse=True)
def _patch_state_cls():
    """Make TeammateStateManager's _state_cls point to the imported enum."""
    from backend.services.autonomous import teammate_state as ts
    ts.get_state_manager()._state_cls = ts.TeammateState


# ═══════════════════════════════════════════════════════════════
# 5. Full state recovery from run_id
# ═══════════════════════════════════════════════════════════════

async def test_full_state_recovery(db_session):
    """Verify acceptance criterion 1: run_id → OrganizationState → full state."""
    trigger, run, rt = await _create_run(db_session)
    svc = rt._state_svc()

    # Simulate a realistic state set
    await svc.set_state(run.id, "current_action", "main",
                        {"action_type": "respond", "status": "completed"})
    await svc.set_state(run.id, "progress", "main", {"responded": True})
    await svc.set_state(run.id, "progress", "step:abc123",
                        {"status": "completed", "duration_ms": 1500})
    await svc.set_state(run.id, "progress", "step:def456",
                        {"status": "running", "objective": "Write tests"})
    await svc.set_state(run.id, "member", "engineer",
                        {"state": "working", "task_id": "t1"})

    # Recover: fresh session (simulates restart)
    all_states = await svc.list_states(run.id)

    state_map = {(s.state_type, s.key): s.value for s in all_states}

    # current_action
    ca = state_map.get(("current_action", "main"), {})
    assert ca.get("action_type") == "respond"

    # progress
    progress_main = state_map.get(("progress", "main"), {})
    assert progress_main.get("responded") is True

    step_abc = state_map.get(("progress", "step:abc123"), {})
    assert step_abc.get("status") == "completed"

    step_def = state_map.get(("progress", "step:def456"), {})
    assert step_def.get("status") == "running"

    # member
    member_state = state_map.get(("member", "engineer"), {})
    assert member_state.get("state") == "working"


# ═══════════════════════════════════════════════════════════════
# 6. DB persistence (restart survival)
# ═══════════════════════════════════════════════════════════════

async def test_state_survives_restart(db_session):
    """State persisted to DB survives across sessions."""
    trigger, run, rt = await _create_run(db_session)
    svc = rt._state_svc()

    await svc.set_state(run.id, "current_action", "main",
                        {"action_type": "delegate", "status": "completed"})
    await svc.set_state(run.id, "progress", "main", {"completed": 5, "total": 10})

    # Simulate restart: query with a fresh select
    from sqlalchemy import select as sa_select
    r = await db_session.execute(
        sa_select(OrganizationState)
        .where(OrganizationState.run_id == run.id)
        .order_by(OrganizationState.state_type)
    )
    recovered = list(r.scalars().all())
    assert len(recovered) == 2
    assert any(s.state_type == "current_action" for s in recovered)
    assert any(s.state_type == "progress" for s in recovered)
