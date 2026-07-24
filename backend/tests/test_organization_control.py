"""OrganizationControl tests — pause/resume/cancel + status query.

No new models, no execution chain modification.
"""

import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio

from backend.models.organization_run import OrganizationRun
from backend.models.session import SessionTrigger, SessionEvent
from backend.models.organization_state import OrganizationState


@pytest.fixture
def control(db_session):
    from backend.services.organization.control import OrganizationControl
    return OrganizationControl(db_session)


async def _seed_run(db_session, status: str = "active") -> tuple[OrganizationRun, SessionTrigger]:
    """Create a run + trigger for control tests."""
    run = OrganizationRun(id="ctrl-run-1", run_type="chat", status=status)
    db_session.add(run)
    trigger = SessionTrigger(
        id="ctrl-trg-1", trigger_type="chat", channel_id="ch-ctrl",
        run_id="ctrl-run-1",
        trigger_time=datetime.now(timezone.utc),
    )
    db_session.add(trigger)
    await db_session.commit()
    return run, trigger


# ═══════════════════════════════════════════
# 1. Status query
# ═══════════════════════════════════════════


async def test_get_status_active(control, db_session):
    await _seed_run(db_session)
    status = await control.get_status("ctrl-run-1")
    assert status["run_id"] == "ctrl-run-1"
    assert status["status"] == "active"


async def test_get_status_not_found(control, db_session):
    status = await control.get_status("nonexistent")
    assert status["status"] == "not_found"


async def test_get_status_with_state_and_event(control, db_session):
    await _seed_run(db_session)
    db_session.add(OrganizationState(
        run_id="ctrl-run-1", state_type="current_action", key="main",
        value={"action_type": "respond", "status": "running"},
    ))
    db_session.add(OrganizationState(
        run_id="ctrl-run-1", state_type="progress", key="main",
        value={"responded": False},
    ))
    await db_session.flush()

    # Add an event so latest_event is populated
    from sqlalchemy import select
    trig = (await db_session.execute(
        select(SessionTrigger).where(SessionTrigger.run_id == "ctrl-run-1")
    )).scalar_one()
    db_session.add(SessionEvent(
        id="ctrl-ev-1", trigger_id=trig.id,
        event_type="action.completed",
        payload={"action_type": "respond"},
        timestamp=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    status = await control.get_status("ctrl-run-1")
    assert status["current_action"]["status"] == "running"
    assert status["progress_state"]["responded"] is False
    assert status["latest_event"]["event_type"] == "action.completed"


# ═══════════════════════════════════════════
# 2. Pause
# ═══════════════════════════════════════════


async def test_pause_run(control, db_session):
    await _seed_run(db_session)
    run = await control.pause_run("ctrl-run-1")
    assert run is not None
    assert run.status == "paused"


async def test_pause_emits_event(control, db_session):
    await _seed_run(db_session)
    await control.pause_run("ctrl-run-1")
    from sqlalchemy import select
    r = await db_session.execute(
        select(SessionEvent).where(SessionEvent.event_type == "run.paused")
    )
    events = list(r.scalars().all())
    assert len(events) == 1
    assert events[0].payload.get("run_id") == "ctrl-run-1"


# ═══════════════════════════════════════════
# 3. Resume
# ═══════════════════════════════════════════


async def test_resume_run(control, db_session):
    await _seed_run(db_session, status="paused")
    run = await control.resume_run("ctrl-run-1")
    assert run is not None
    assert run.status == "running"


async def test_resume_emits_event(control, db_session):
    await _seed_run(db_session, status="paused")
    await control.resume_run("ctrl-run-1")
    from sqlalchemy import select
    r = await db_session.execute(
        select(SessionEvent).where(SessionEvent.event_type == "run.resumed")
    )
    events = list(r.scalars().all())
    assert len(events) == 1


# ═══════════════════════════════════════════
# 4. Cancel
# ═══════════════════════════════════════════


async def test_cancel_run(control, db_session):
    await _seed_run(db_session)
    run = await control.cancel_run("ctrl-run-1")
    assert run is not None
    assert run.status == "cancelled"
    assert run.ended_at is not None


async def test_cancel_emits_event(control, db_session):
    await _seed_run(db_session)
    await control.cancel_run("ctrl-run-1")
    from sqlalchemy import select
    r = await db_session.execute(
        select(SessionEvent).where(SessionEvent.event_type == "run.cancelled")
    )
    events = list(r.scalars().all())
    assert len(events) == 1
    assert events[0].payload.get("run_id") == "ctrl-run-1"


# ═══════════════════════════════════════════
# 5. Missing run — all return None
# ═══════════════════════════════════════════


async def test_control_missing_run(control, db_session):
    assert await control.pause_run("no-such") is None
    assert await control.resume_run("no-such") is None
    assert await control.cancel_run("no-such") is None
