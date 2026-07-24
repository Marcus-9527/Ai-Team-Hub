"""Phase 6.1 identity feedback tests — post-run evolution, trend, failure safety."""

import pytest

from backend.models.chat import Teammate
from backend.models.session import SessionTrigger, SessionTurn
from backend.models.organization_run import OrganizationRun
from backend.services.memory.memory_service import get_memory_service


# ═══════════════════════════════════════════
# 1. process_run → MEMBER_KNOWLEDGE created
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_finished_run_updates_identity(db_session):
    """process_run creates MEMBER_KNOWLEDGE from SessionTurns."""
    run = OrganizationRun(id="fb-run-1", run_type="chat", status="active")
    db_session.add(run)
    db_session.add(SessionTrigger(id="fb-trg-1", trigger_type="chat",
                                  run_id="fb-run-1"))
    db_session.add(SessionTurn(teammate_id="fb-tm-1", trigger_id="fb-trg-1",
                               action="responded"))
    db_session.add(SessionTurn(teammate_id="fb-tm-1", trigger_id="fb-trg-1",
                               action="responded", failure="timeout"))
    await db_session.commit()

    from backend.services.organization.identity_feedback import IdentityFeedbackService
    await IdentityFeedbackService(db_session).process_run("fb-run-1")

    from backend.services.memory.memory_types import MemoryType
    items = await get_memory_service().query(
        memory_type=MemoryType.MEMBER_KNOWLEDGE.value,
        source_id="fb-tm-1", limit=5,
    )
    assert len(items) >= 1
    assert "completed=1" in items[-1].content
    assert "failed=1" in items[-1].content


# ═══════════════════════════════════════════
# 2. identity reads performance
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_identity_reads_performance(db_session):
    """get_identity returns recent_performance from SessionTurn."""
    db_session.add(Teammate(id="pf-tm-1", name="Perf", role="engineer",
                            model_provider="test", model_name="test"))
    run = OrganizationRun(id="pf-run-1", run_type="chat", status="active")
    db_session.add(run)
    db_session.add(SessionTrigger(id="pf-trg-1", trigger_type="chat",
                                  run_id="pf-run-1"))
    db_session.add(SessionTurn(teammate_id="pf-tm-1", trigger_id="pf-trg-1",
                               action="responded"))
    await db_session.commit()

    from backend.services.organization.identity import TeammateIdentityService
    ident = await TeammateIdentityService(db_session).get_identity("pf-tm-1")

    assert "recent_performance" in ident
    assert ident["recent_performance"]["completed"] >= 1


# ═══════════════════════════════════════════
# 3. identity trend from MEMBER_KNOWLEDGE
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_identity_trend(db_session):
    """get_identity parses performance_trend from MEMBER_KNOWLEDGE."""
    from backend.services.memory.memory_types import MemoryItem, MemoryType
    mem_svc = get_memory_service()
    # Use unique source_id so test is independent of leftover data
    await mem_svc.store(MemoryItem(
        memory_type=MemoryType.MEMBER_KNOWLEDGE.value,
        content="[performance] completed=10 failed=2 rate=0.83",
        source_id="tr-trend-1",
        metadata={"scope": "member", "teammate_id": "tr-trend-1"},
    ))

    from backend.services.organization.identity import TeammateIdentityService
    ident = await TeammateIdentityService(db_session).get_identity("tr-trend-1")

    assert "performance_trend" in ident
    assert ident["performance_trend"]["current"]["success_rate"] == 0.83
    assert ident["performance_trend"]["trend"]["completed"] >= 0
    assert ident["performance_trend"]["trend"]["failed"] >= 0

# ═══════════════════════════════════════════
# 4. finish_run failure safety
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_finish_run_failure_safe(db_session):
    """process_run failure does not propagate."""
    run = OrganizationRun(id="fail-run-1", run_type="chat", status="active")
    db_session.add(run)
    await db_session.commit()

    from unittest.mock import patch
    with patch.object(get_memory_service(), "store",
                      side_effect=RuntimeError("boom")):
        from backend.services.organization.identity_feedback import IdentityFeedbackService
        svc = IdentityFeedbackService(db_session)
        # Should not raise despite mock failure
        await svc.process_run("fail-run-1")

    await db_session.refresh(run)
    assert run.status == "active"


# ═══════════════════════════════════════════
# 5. brain prompt includes trend
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_brain_prompt_contains_trend(db_session):
    """build_prompt with db includes performance trend in TEAMMATE IDENTITY."""
    db_session.add(Teammate(id="bt-tm-1", name="Bot", role="engineer",
                            model_provider="test", model_name="test"))
    await db_session.commit()

    from backend.services.memory.memory_types import MemoryItem, MemoryType
    await get_memory_service().store(MemoryItem(
        memory_type=MemoryType.MEMBER_KNOWLEDGE.value,
        content="[performance] completed=20 failed=1 rate=0.95",
        source_id="bt-tm-1",
        metadata={"scope": "member", "teammate_id": "bt-tm-1"},
    ))

    from backend.services.brain.brain_loader import BrainLoader
    prompt = await BrainLoader().build_prompt("bt-tm-1", db=db_session)

    assert "Performance trend" in prompt
    assert "95%" in prompt


# ═══════════════════════════════════════════
# 6. no new ORM models
# ═══════════════════════════════════════════

def test_no_new_models():
    """Verify no new ORM model added by Phase 6.1."""
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
