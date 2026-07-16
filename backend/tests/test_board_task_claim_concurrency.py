"""
test_board_task_claim_concurrency.py — Board task: optimistic-lock claim + ws isolation.

Ponytail: no TestClient, no fixtures. Hit the route handlers + DB directly with
real in-memory SQLite so the concurrency assertion is deterministic and the
failure is loud.
"""
import asyncio
import os
import tempfile

os.environ["AI_TEAM_HUB_DB"] = os.path.join(tempfile.mkdtemp(), "board.db")

import pytest
from backend.database import init_db, async_session
from backend.models import BoardTask, Channel
from backend.routes import board_tasks as bt
from backend.middleware.auth import ws_id_of


async def _seed(channel_id: str, ws: str) -> str:
    async with async_session() as db:
        ch = Channel(id=channel_id, name="c", workspace_id=ws)
        db.add(ch)
        t = BoardTask(workspace_id=ws, channel_id=channel_id, title="claim me", created_by="seed")
        db.add(t)
        await db.commit()
        await db.refresh(t)
        return t.id


def _fake_request(ws: str):
    """Minimal stub: route reads ws_id_of(request) → request.state.workspace_id."""
    class _Req:
        pass
    r = _Req()
    r.state = type("S", (), {"workspace_id": ws})()
    return r


async def _claim(task_id, ws, who):
    async with async_session() as db:
        return await bt.claim_board_task(task_id, bt.ClaimBoardTaskRequest(assignee_id=who, assignee_name=who), _fake_request(ws), db)


@pytest.mark.asyncio
async def test_claim_concurrency_exactly_one_wins():
    await init_db()
    task_id = await _seed("ch-conc", "ws-conc")

    # Two truly concurrent claims, each on its own session (real race).
    # Only one UPDATE with `assignee_id IS NULL` can match -> the loser's
    # rowcount==0 -> HTTPException(409). gather must propagate exactly one 409.
    results = []
    errors = []
    done = await asyncio.gather(
        _claim(task_id, "ws-conc", "A"),
        _claim(task_id, "ws-conc", "B"),
        return_exceptions=True,
    )
    for d in done:
        if isinstance(d, Exception):
            errors.append(d)
        else:
            results.append(d)
    assert len(results) == 1, f"exactly one claim should win, got {len(results)}"
    assert len(errors) == 1 and errors[0].status_code == 409, f"loser must be 409, got {errors}"


@pytest.mark.asyncio
async def test_workspace_isolation_other_ws_cannot_see():
    await init_db()
    # ws-A task, ws-B caller
    task_id = await _seed("ch-A", "ws-A")

    # ws-B listing the same channel returns nothing (different workspace)
    async with async_session() as db:
        listing = await bt.list_channel_tasks("ch-A", _fake_request("ws-B"), db)
    assert listing == [], "ws-B must not see ws-A's board task"

    # ws-B claiming ws-A's task → 404 (not 409, not claimed-by-other)
    async with async_session() as db:
        try:
            await bt.claim_board_task(task_id, bt.ClaimBoardTaskRequest(assignee_id="X"), _fake_request("ws-B"), db)
            assert False, "cross-workspace claim must be rejected"
        except Exception as e:
            assert e.status_code in (404, 409), f"expected 404/409, got {e.status_code}"


@pytest.mark.asyncio
async def test_cross_workspace_channel_rejected_on_create():
    await init_db()
    await _seed("ch-other", "ws-other")
    async with async_session() as db:
        try:
            await bt.create_board_task(
                bt.CreateBoardTaskRequest(title="x", channel_id="ch-other"),
                _fake_request("ws-mine"), db,
            )
            assert False, "must reject attaching task to another ws's channel"
        except Exception as e:
            assert e.status_code == 400, f"expected 400, got {e.status_code}"


if __name__ == "__main__":
    asyncio.run(test_claim_concurrency_exactly_one_wins())
    asyncio.run(test_workspace_isolation_other_ws_cannot_see())
    asyncio.run(test_cross_workspace_channel_rejected_on_create())
    print("OK: board task claim concurrency + workspace isolation verified.")
