"""Organization API tests — HTTP-level: status, timeline, summary, control.

Relies on Phase 3.0/3.1 unit tests for service correctness; this file
only verifies HTTP wiring.
"""

import pytest
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.models.organization_run import OrganizationRun
from backend.models.session import SessionTrigger, SessionEvent
from backend.models.organization_state import OrganizationState


@pytest.fixture
def app(db_session):
    """Mini FastAPI app with get_db overridden to the test session."""
    from backend.database import get_db
    from backend.routes.organization import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_session
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


async def _seed(db_session) -> None:
    """Create a realistic run with trigger, events, and state."""
    run = OrganizationRun(id="api-run-1", run_type="chat", title="API test", status="active")
    db_session.add(run)
    trigger = SessionTrigger(
        id="api-trg-1", trigger_type="chat", channel_id="ch-api",
        run_id="api-run-1", trigger_time=datetime.now(timezone.utc),
    )
    db_session.add(trigger)
    db_session.add(SessionEvent(
        id="api-ev-1", trigger_id="api-trg-1", event_type="run.created",
        payload={"run_id": "api-run-1"},
        timestamp=datetime.now(timezone.utc),
    ))
    db_session.add(OrganizationState(
        run_id="api-run-1", state_type="current_action", key="main",
        value={"action_type": "respond", "status": "completed"},
    ))
    await db_session.commit()


def test_organization_api(client, db_session):
    """One linear flow: status → timeline → summary → pause → resume → cancel."""

    # Seed runs synchronously via event loop
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed(db_session))

    # ── 1. GET status ──
    r = client.get("/api/organization/runs/api-run-1/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "active"
    assert data["current_action"]["status"] == "completed"

    # ── 2. GET timeline ──
    r = client.get("/api/organization/runs/api-run-1/timeline")
    assert r.status_code == 200
    tl = r.json()
    assert isinstance(tl, list)
    assert any(e["event_type"] == "run.created" for e in tl)

    # ── 3. GET summary ──
    r = client.get("/api/organization/runs/api-run-1/summary")
    assert r.status_code == 200
    s = r.json()
    assert s["run_id"] == "api-run-1"
    assert s["status"] == "active"

    # ── 4. POST pause → resume → cancel ──
    r = client.post("/api/organization/runs/api-run-1/pause")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    r = client.post("/api/organization/runs/api-run-1/resume")
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    r = client.post("/api/organization/runs/api-run-1/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # ── 5. 404 for nonexistent run ──
    r = client.post("/api/organization/runs/no-such/pause")
    assert r.status_code == 404
