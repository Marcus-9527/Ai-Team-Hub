"""Phase 6.2 selector tests — capability priority, performance influence, fallback, events."""

import pytest

from backend.models.chat import Teammate
from backend.models.session import SessionTrigger, SessionTurn
from backend.models.organization_run import OrganizationRun
from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import get_memory_service


# ── Helpers ──


async def _seed_teammate(db, id_, role="engineer", **kw):
    db.add(Teammate(id=id_, name=f"TM-{id_}", role=role,
                    model_provider="test", model_name="test", **kw))
    await db.commit()


# ═══════════════════════════════════════════
# 1. Capability match gets highest priority
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_capability_match_priority(db_session):
    """Member with matching capability scores +50, beats member without."""
    from backend.services.organization.selector import TeammateSelector

    await _seed_teammate(db_session, "cap-tm-a", role="engineer")
    await _seed_teammate(db_session, "cap-tm-b", role="assistant")

    sel = TeammateSelector(db_session)

    # "code" goal → _infer_capabilities → ["code"]
    # engineer has ["code_execution"] in DEFAULT_ROLE_CAPABILITIES
    result = await sel.select(
        task_description="write some python code",
        required_capabilities=["code_execution"],
        members=["cap-tm-a", "cap-tm-b"],
    )

    assert result is not None
    assert result["teammate_id"] == "cap-tm-a"
    assert result["score"] >= 50


# ═══════════════════════════════════════════
# 2. Performance affects ordering
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_performance_affects_score(db_session):
    """Higher success rate gets higher performance score."""
    from backend.services.organization.selector import TeammateSelector

    await _seed_teammate(db_session, "pf-tm-a", role="engineer")
    await _seed_teammate(db_session, "pf-tm-b", role="engineer")

    # Both have same role/capabilities, but different performance
    await _seed_turns(db_session, "pf-tm-b", completed=9, failed=1, run_id="perf-run-b")   # 90%
    await _seed_turns(db_session, "pf-tm-a", completed=5, failed=5, run_id="perf-run-a")   # 50%

    sel = TeammateSelector(db_session)
    result = await sel.select(
        task_description="write code",
        required_capabilities=["code_execution"],
        members=["pf-tm-a", "pf-tm-b"],
    )

    assert result is not None
    assert result["teammate_id"] == "pf-tm-b"  # higher success rate


async def _seed_turns(db, teammate_id, completed, failed, run_id="perf-run"):
    """Seed SessionTurns for performance stats."""
    db.add(OrganizationRun(id=run_id, run_type="chat", status="active"))
    db.add(SessionTrigger(id=f"trg-{teammate_id}", trigger_type="chat",
                          run_id=run_id))
    for i in range(completed):
        db.add(SessionTurn(teammate_id=teammate_id, trigger_id=f"trg-{teammate_id}",
                           action="responded"))
    for i in range(failed):
        db.add(SessionTurn(teammate_id=teammate_id, trigger_id=f"trg-{teammate_id}",
                           action="responded", failure="error"))
    await db.commit()


# ═══════════════════════════════════════════
# 3. Fallback when no match
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_selector_fallback(db_session):
    """No matching capability or skill → returns None."""
    from backend.services.organization.selector import TeammateSelector

    await _seed_teammate(db_session, "fb-tm-1", role="assistant")

    sel = TeammateSelector(db_session)
    result = await sel.select(
        task_description="quantum physics research",
        required_capabilities=["quantum"],
        members=[],
    )
    assert result is None


# ═══════════════════════════════════════════
# 4. Selection emits team.member.selected event
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_selection_event(db_session):
    """OrganizationExecutor.delegate emits team.member.selected event."""
    from unittest.mock import patch
    from backend.services.organization.context import OrganizationContextBuilder
    from backend.services.task.task_orchestrator import TaskOrchestrator

    await _seed_teammate(db_session, "ev-tm-1", role="engineer")
    run = OrganizationRun(id="ev-run-1", run_type="task", status="active")
    db_session.add(run)
    trg = SessionTrigger(id="ev-trg-1", trigger_type="task", run_id="ev-run-1")
    db_session.add(trg)
    await db_session.commit()

    from backend.services.organization.execution import OrganizationExecutor
    executor = OrganizationExecutor(db_session)

    # Mock context builder to return members (avoids full channel setup)
    class FakeCtx:
        members = ["ev-tm-1"]

    with patch.object(OrganizationContextBuilder, "build",
                      return_value=FakeCtx()), \
         patch.object(TaskOrchestrator, "start_task",
                      return_value=None):
        await executor.delegate(
            trigger_id="ev-trg-1", run_id="ev-run-1",
            task_id="ev-task-1", goal="review python code",
        )

    from backend.models.session import SessionEvent
    from sqlalchemy import select
    events = await db_session.execute(
        select(SessionEvent).where(
            SessionEvent.trigger_id == "ev-trg-1",
            SessionEvent.event_type == "team.member.selected",
        )
    )
    ev = events.scalars().first()
    assert ev is not None
    assert ev.event_type == "team.member.selected"
    assert ev.payload.get("teammate_id") == "ev-tm-1"
    assert "reasons" in ev.payload


# ═══════════════════════════════════════════
# 5. No new ORM models
# ═══════════════════════════════════════════

def test_no_new_models():
    """Verify no new ORM model added by Phase 6.2."""
    from backend.models import __init__ as models_mod
    known = {
        "Channel", "Teammate", "TeammateTemplate", "User",
        "ApiKey", "Message", "Workspace", "WorkspaceMember",
        "OrganizationRun", "OrganizationState", "OrganizationCapability",
        "SessionTrigger", "SessionEvent", "SessionTurn",
        "TaskModel", "TaskStep", "BrainFragment",
        "DAGNode", "DAGEdge", "DAGRun", "BoardTask",
        "AutomationJobModel", "AutomationRunModel",
        "MemoryItem",
    }
    model_names = {name for name in dir(models_mod) if not name.startswith("_")}
    new = model_names - known
    assert not new, f"Unexpected new models: {new}"
