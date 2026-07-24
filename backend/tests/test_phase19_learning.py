"""Phase 19: Organization Learning Loop — tests.

Verifies:
1. Successful run produces TEAM_PATTERN + MEMBER_KNOWLEDGE
2. Failed run produces failure pattern (failed_turns > 0)
3. Teammate contribution data is written per-teammate
4. Learning hook is called from finish_run (failure-safe)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.models.organization_run import OrganizationRun
from backend.models.session import SessionTrigger, SessionTurn

pytestmark = pytest.mark.asyncio


# ════════════════════════════════════════════════
# 1. Successful run → TEAM_PATTERN + MEMBER_KNOWLEDGE
# ════════════════════════════════════════════════


async def test_learn_from_run_success(db_session):
    """Successful run stores TEAM_PATTERN with success data."""
    from backend.services.organization.learning import OrganizationLearningService

    # Arrange: one run, one trigger, two successful turns
    run = OrganizationRun(id="lr-succ-run", run_type="chat", status="completed",
                          workspace_id="ws-lr")
    db_session.add(run)
    trig = SessionTrigger(id="lr-succ-trg", run_id="lr-succ-run", trigger_type="chat")
    db_session.add(trig)
    db_session.add(SessionTurn(
        id="lr-turn-1", trigger_id="lr-succ-trg", teammate_id="tm-a",
        action="responded", action_type="respond",
    ))
    db_session.add(SessionTurn(
        id="lr-turn-2", trigger_id="lr-succ-trg", teammate_id="tm-b",
        action="responded", action_type="respond",
    ))
    await db_session.commit()

    mock_mem = AsyncMock()

    with patch("backend.services.memory.memory_service.get_memory_service",
               return_value=mock_mem):
        svc = OrganizationLearningService(db_session)
        await svc.learn_from_run("lr-succ-run")

    # TEAM_PATTERN stored once
    team_calls = [
        c for c in mock_mem.store.call_args_list
        if c[0][0].memory_type == "TEAM_PATTERN"
    ]
    assert len(team_calls) == 1
    tp = team_calls[0][0][0]
    assert "lr-succ-run" in tp.source_id
    assert tp.metadata["total_turns"] == 2
    assert tp.metadata["successful_turns"] == 2
    assert tp.metadata["failed_turns"] == 0
    assert sorted(tp.metadata["teammate_ids"]) == ["tm-a", "tm-b"]
    assert tp.relevance_score == 1.0

    # MEMBER_KNOWLEDGE stored for each teammate
    mk_calls = [
        c for c in mock_mem.store.call_args_list
        if c[0][0].memory_type == "MEMBER_KNOWLEDGE"
    ]
    assert len(mk_calls) == 2
    for call in mk_calls:
        item = call[0][0]
        assert item.metadata["total_turns"] == 1
        assert item.metadata["successful_turns"] == 1
        assert item.metadata["failed_turns"] == 0


# ════════════════════════════════════════════════
# 2. Failed run → failure pattern in TEAM_PATTERN
# ════════════════════════════════════════════════


async def test_learn_from_run_failure(db_session):
    """Failed turns are reflected in TEAM_PATTERN metadata."""
    from backend.services.organization.learning import OrganizationLearningService

    run = OrganizationRun(id="lr-fail-run", run_type="task", status="failed",
                          workspace_id="ws-lr")
    db_session.add(run)
    trig = SessionTrigger(id="lr-fail-trg", run_id="lr-fail-run", trigger_type="task")
    db_session.add(trig)
    db_session.add(SessionTurn(
        id="lr-fail-t1", trigger_id="lr-fail-trg", teammate_id="tm-a",
        action="responded", action_type="respond",
    ))
    db_session.add(SessionTurn(
        id="lr-fail-t2", trigger_id="lr-fail-trg", teammate_id="tm-a",
        action="responded", action_type="respond",
        failure="TimeoutError",
    ))
    await db_session.commit()

    mock_mem = AsyncMock()

    with patch("backend.services.memory.memory_service.get_memory_service",
               return_value=mock_mem):
        svc = OrganizationLearningService(db_session)
        await svc.learn_from_run("lr-fail-run")

    team_calls = [
        c for c in mock_mem.store.call_args_list
        if c[0][0].memory_type == "TEAM_PATTERN"
    ]
    assert len(team_calls) == 1
    tp = team_calls[0][0][0]
    assert tp.metadata["total_turns"] == 2
    assert tp.metadata["successful_turns"] == 1
    assert tp.metadata["failed_turns"] == 1
    assert tp.relevance_score == 0.5  # 1/2

    # Per-teammate: tm-a had 1 failure
    mk_calls = [
        c for c in mock_mem.store.call_args_list
        if c[0][0].memory_type == "MEMBER_KNOWLEDGE"
    ]
    assert len(mk_calls) == 1
    item = mk_calls[0][0][0]
    assert item.metadata["teammate_id"] == "tm-a"
    assert item.metadata["total_turns"] == 2
    assert item.metadata["failed_turns"] == 1
    assert item.metadata["successful_turns"] == 1


# ════════════════════════════════════════════════
# 3. Teammate feedback — diverse contributions
# ════════════════════════════════════════════════


async def test_learn_from_run_teammate_feedback(db_session):
    """Each teammate gets correct individual stats."""
    from backend.services.organization.learning import OrganizationLearningService

    run = OrganizationRun(id="lr-tmfb-run", run_type="chat", status="completed",
                          workspace_id="ws-lr")
    db_session.add(run)
    trig = SessionTrigger(id="lr-tmfb-trg", run_id="lr-tmfb-run", trigger_type="chat")
    db_session.add(trig)

    # tm-a: 3 turns, 1 failure
    for i in range(2):
        db_session.add(SessionTurn(
            id=f"lr-tmfb-a{i}", trigger_id="lr-tmfb-trg", teammate_id="tm-a",
            action="responded", action_type="respond",
        ))
    db_session.add(SessionTurn(
        id="lr-tmfb-a2", trigger_id="lr-tmfb-trg", teammate_id="tm-a",
        action="ceded", action_type="tool_call", failure="API error",
    ))
    # tm-b: 1 turn, all success
    db_session.add(SessionTurn(
        id="lr-tmfb-b0", trigger_id="lr-tmfb-trg", teammate_id="tm-b",
        action="responded", action_type="respond",
    ))
    await db_session.commit()

    mock_mem = AsyncMock()

    with patch("backend.services.memory.memory_service.get_memory_service",
               return_value=mock_mem):
        svc = OrganizationLearningService(db_session)
        await svc.learn_from_run("lr-tmfb-run")

    mk_calls = {
        c[0][0].metadata["teammate_id"]: c[0][0]
        for c in mock_mem.store.call_args_list
        if c[0][0].memory_type == "MEMBER_KNOWLEDGE"
    }

    # tm-a: 3 total, 2 success, 1 fail
    a = mk_calls["tm-a"]
    assert a.metadata["total_turns"] == 3
    assert a.metadata["successful_turns"] == 2
    assert a.metadata["failed_turns"] == 1
    # tm-a had both "respond" and "tool_call" action types
    assert "respond" in a.metadata["action_types"]
    assert "tool_call" in a.metadata["action_types"]

    # tm-b: 1 total, 1 success
    b = mk_calls["tm-b"]
    assert b.metadata["total_turns"] == 1
    assert b.metadata["successful_turns"] == 1
    assert b.metadata["failed_turns"] == 0


# ════════════════════════════════════════════════
# 4. Hook in finish_run — failure-safe
# ════════════════════════════════════════════════


async def test_learning_hook_in_finish_run(db_session):
    """finish_run calls OrganizationLearningService.learn_from_run."""
    from backend.services.organization.runtime import OrganizationRuntime

    run = OrganizationRun(id="lr-hook-run", run_type="chat", status="active")
    db_session.add(run)
    await db_session.commit()

    rt = OrganizationRuntime(db_session)

    with patch(
        "backend.services.organization.learning.OrganizationLearningService",
    ) as mock_cls:
        mock_svc = AsyncMock()
        mock_cls.return_value = mock_svc

        await rt.finish_run("lr-hook-run", status="completed")

        mock_cls.assert_called_once_with(db_session)
        mock_svc.learn_from_run.assert_called_once_with("lr-hook-run")


async def test_learning_hook_does_not_affect_finish_run(db_session):
    """finish_run succeeds even when learning raises."""
    from backend.services.organization.runtime import OrganizationRuntime

    run = OrganizationRun(id="lr-crash-run", run_type="chat", status="active")
    db_session.add(run)
    await db_session.commit()

    rt = OrganizationRuntime(db_session)

    with patch(
        "backend.services.organization.learning.OrganizationLearningService",
    ) as mock_cls:
        mock_svc = AsyncMock()
        mock_svc.learn_from_run.side_effect = RuntimeError("learning crash")
        mock_cls.return_value = mock_svc

        # Must not raise — the hook is failure-safe
        await rt.finish_run("lr-crash-run", status="completed")

    # Run should still be closed
    updated = await db_session.get(OrganizationRun, "lr-crash-run")
    assert updated is not None
    assert updated.status == "completed"


# ════════════════════════════════════════════════
# 5. No data — no crash
# ════════════════════════════════════════════════


async def test_learn_from_run_no_triggers(db_session):
    """No triggers → no error, no memory writes."""
    from backend.services.organization.learning import OrganizationLearningService

    run = OrganizationRun(id="lr-notrg-run", run_type="chat", status="completed")
    db_session.add(run)
    await db_session.commit()

    mock_mem = AsyncMock()

    with patch("backend.services.memory.memory_service.get_memory_service",
               return_value=mock_mem):
        svc = OrganizationLearningService(db_session)
        await svc.learn_from_run("lr-notrg-run")

    mock_mem.store.assert_not_called()


async def test_learn_from_run_no_run(db_session):
    """Non-existent run → no error, no memory writes."""
    from backend.services.organization.learning import OrganizationLearningService

    mock_mem = AsyncMock()

    with patch("backend.services.memory.memory_service.get_memory_service",
               return_value=mock_mem):
        svc = OrganizationLearningService(db_session)
        await svc.learn_from_run("lr-nonexistent")

    mock_mem.store.assert_not_called()
