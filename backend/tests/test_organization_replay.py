"""OrganizationRunInspector tests — read-only, no chain modification."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio

from backend.models.organization_run import OrganizationRun
from backend.models.organization_state import OrganizationState
from backend.models.session import SessionEvent, SessionTrigger, SessionTurn


@pytest.fixture
def inspector(db_session):
    from backend.services.organization.inspector import OrganizationRunInspector
    return OrganizationRunInspector(db_session)


async def _seed_run(db_session) -> tuple:
    """Create a realistic run with triggers, events, turns, and state."""
    run = OrganizationRun(
        id="run-inspect-1",
        run_type="chat",
        title="Test run",
        status="completed",
        created_at=datetime(2026, 7, 23, 10, 0, 0),
        ended_at=datetime(2026, 7, 23, 10, 5, 30),
    )
    db_session.add(run)

    trigger = SessionTrigger(
        id="trg-1", trigger_type="chat", channel_id="ch-1",
        run_id="run-inspect-1",
        trigger_time=datetime(2026, 7, 23, 10, 0, 5, tzinfo=timezone.utc),
    )
    db_session.add(trigger)

    # Events: run.created → action.created → action.started → action.completed
    for i, (etype, ts_off) in enumerate([
        ("run.created", 0),
        ("action.created", 1),
        ("action.started", 2),
        ("action.completed", 4),
    ]):
        db_session.add(SessionEvent(
            id=f"ev-{i}", trigger_id="trg-1",
            event_type=etype,
            payload={"run_id": "run-inspect-1", "action_type": "respond"},
            timestamp=datetime(2026, 7, 23, 10, 0, ts_off, tzinfo=timezone.utc),
        ))

    # Failed action in a second trigger
    trigger2 = SessionTrigger(
        id="trg-2", trigger_type="chat", channel_id="ch-1",
        run_id="run-inspect-1",
        trigger_time=datetime(2026, 7, 23, 10, 3, 0, tzinfo=timezone.utc),
    )
    db_session.add(trigger2)
    db_session.add(SessionEvent(
        id="ev-fail", trigger_id="trg-2",
        event_type="action.failed",
        payload={"run_id": "run-inspect-1", "action_type": "execute", "error": "LLM timeout"},
        timestamp=datetime(2026, 7, 23, 10, 3, 10, tzinfo=timezone.utc),
    ))

    # Turns
    db_session.add(SessionTurn(
        id="turn-1", trigger_id="trg-1", teammate_id="tm-eng",
        action="responded", start_time=datetime(2026, 7, 23, 10, 0, 3, tzinfo=timezone.utc),
    ))
    db_session.add(SessionTurn(
        id="turn-2", trigger_id="trg-1", teammate_id="tm-pm",
        action="responded", start_time=datetime(2026, 7, 23, 10, 0, 5, tzinfo=timezone.utc),
    ))

    # State
    db_session.add(OrganizationState(
        run_id="run-inspect-1", state_type="current_action", key="main",
        value={"action_type": "respond", "status": "completed"},
    ))
    db_session.add(OrganizationState(
        run_id="run-inspect-1", state_type="progress", key="main",
        value={"responded": True},
    ))

    await db_session.commit()
    return run, trigger


# ═══════════════════════════════════════════
# 1. Timeline
# ═══════════════════════════════════════════

async def test_timeline_after_run_created(inspector, db_session):
    await _seed_run(db_session)
    tl = await inspector.get_timeline("run-inspect-1")
    assert len(tl) >= 4
    # Sorted by timestamp
    timestamps = [e["timestamp"] for e in tl]
    assert timestamps == sorted(timestamps)
    # Event types present
    types = [e["event_type"] for e in tl]
    assert "run.created" in types
    assert "action.created" in types
    assert "action.completed" in types


# ═══════════════════════════════════════════
# 2. Action lifecycle
# ═══════════════════════════════════════════

async def test_action_lifecycle(inspector, db_session):
    await _seed_run(db_session)
    tl = await inspector.get_timeline("run-inspect-1")
    action_events = [e for e in tl if e["event_type"].startswith("action.")]
    assert len(action_events) >= 3
    # Order: created → started → completed
    types = [e["event_type"] for e in action_events if not e["event_type"] == "action.failed"]
    assert types == ["action.created", "action.started", "action.completed"]
    # Failed action present too
    assert any(e["event_type"] == "action.failed" for e in action_events)


# ═══════════════════════════════════════════
# 3. State snapshot
# ═══════════════════════════════════════════

async def test_state_snapshot_recoverable(inspector, db_session):
    await _seed_run(db_session)
    snap = await inspector.get_state_snapshot("run-inspect-1")
    assert "current_action" in snap
    assert snap["current_action"]["main"]["status"] == "completed"
    assert "progress" in snap
    assert snap["progress"]["main"]["responded"] is True


# ═══════════════════════════════════════════
# 4. Failed action localization
# ═══════════════════════════════════════════

async def test_failed_action_detected(inspector, db_session):
    await _seed_run(db_session)
    summary = await inspector.summarize_run("run-inspect-1")
    assert summary["failure_count"] >= 1
    fail = summary["failed_actions"][0]
    assert fail["event_type"] == "action.failed"
    assert "error" in fail["payload"]


# ═══════════════════════════════════════════
# 5. Summary
# ═══════════════════════════════════════════

async def test_summary_fields(inspector, db_session):
    await _seed_run(db_session)
    s = await inspector.summarize_run("run-inspect-1")
    assert s["run_id"] == "run-inspect-1"
    assert s["run_type"] == "chat"
    assert s["status"] == "completed"
    assert s["duration_seconds"] == 330.0  # 5m30s
    assert "tm-eng" in s["teammates"]
    assert "tm-pm" in s["teammates"]
    assert s["action_count"] >= 4  # 4 action.* + 1 failed = 5
    assert s["trigger_count"] == 2


async def test_summary_not_found(inspector, db_session):
    s = await inspector.summarize_run("nonexistent")
    assert s["status"] == "not_found"


async def test_timeline_empty_run(inspector, db_session):
    # Run exists but no triggers
    run = OrganizationRun(id="run-empty", run_type="chat", status="active")
    db_session.add(run)
    await db_session.commit()

    tl = await inspector.get_timeline("run-empty")
    assert tl == []


async def test_state_snapshot_empty(inspector, db_session):
    snap = await inspector.get_state_snapshot("no-such-run")
    assert snap == {}
