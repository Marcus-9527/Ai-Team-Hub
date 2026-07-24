"""Phase 6.0 identity tests — capability, memory, context, prompt, model check."""

import pytest

from backend.models.chat import Teammate


# ═══════════════════════════════════════════
# 1. Capability → identity
# ═══════════════════════════════════════════

@pytest.fixture
def identity_svc(db_session):
    from backend.services.organization.identity import TeammateIdentityService
    return TeammateIdentityService(db_session)


@pytest.mark.asyncio
async def test_identity_from_capability(identity_svc, db_session):
    """Identity reflects role and default capabilities."""
    db_session.add(Teammate(id="tm-cap-1", name="Engineer", role="engineer",
                            model_provider="test", model_name="test"))
    await db_session.commit()

    ident = await identity_svc.get_identity("tm-cap-1")
    assert ident["id"] == "tm-cap-1"
    assert ident["role"] == "engineer"
    assert "code_execution" in ident["capabilities"]


@pytest.mark.asyncio
async def test_identity_fallback_role(identity_svc, db_session):
    """Unknown teammate gets 'assistant' role."""
    ident = await identity_svc.get_identity("no-such")
    assert ident["role"] == "assistant"
    assert ident["capabilities"] == []


# ═══════════════════════════════════════════
# 2. BrainFragment → identity
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_identity_from_memory(identity_svc, db_session):
    """Skills and behaviors from BrainFragment appear in identity."""
    from backend.services.brain.fragment_store import (
        get_brain_fragment_store, BrainFragment, BrainFragmentType,
    )
    store = get_brain_fragment_store()
    await store.store(BrainFragment(
        teammate_id="tm-mem-1", workspace_id="ws-1",
        fragment_type=BrainFragmentType.SKILLS.value,
        content="Python, FastAPI",
    ))
    await store.store(BrainFragment(
        teammate_id="tm-mem-1", workspace_id="ws-1",
        fragment_type=BrainFragmentType.BEHAVIOR_SUGGESTION.value,
        content="prefers small patches",
    ))

    ident = await identity_svc.get_identity("tm-mem-1")
    assert any("Python" in s for s in ident["skills"])
    assert any("small patches" in b for b in ident["learned_behaviors"])


# ═══════════════════════════════════════════
# 3. OrganizationContext includes members_info
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_identity_in_context(db_session):
    """build() enriches members with identity data."""
    from backend.services.organization import OrganizationRunService
    from backend.services.organization.context import OrganizationContextBuilder
    from backend.models.chat import Channel

    run = await OrganizationRunService.create_run(
        db_session, run_type="chat", title="ctx test",
    )
    ch = Channel(id="ch-ctx", name="ctx", teammate_ids=["tm-ctx-1"])
    db_session.add(ch)
    run.channel_id = "ch-ctx"
    await db_session.commit()

    builder = OrganizationContextBuilder(db_session)
    ctx = await builder.build(run.id)

    assert hasattr(ctx, "members_info")
    assert isinstance(ctx.members_info, dict)


# ═══════════════════════════════════════════
# 4. Brain prompt includes TEAMMATE IDENTITY
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_brain_prompt_contains_identity(db_session):
    """build_prompt() with db includes TEAMMATE IDENTITY section."""
    db_session.add(Teammate(id="tm-pro-1", name="Test", role="engineer",
                            model_provider="test", model_name="test"))
    await db_session.commit()

    from backend.services.brain.brain_loader import BrainLoader
    loader = BrainLoader()
    prompt = await loader.build_prompt("tm-pro-1", db=db_session)

    assert "TEAMMATE IDENTITY" in prompt
    assert "engineer" in prompt


# ═══════════════════════════════════════════
# 5. No new models
# ═══════════════════════════════════════════
def test_no_new_models():
    """Verify no ORM model was added by Phase 6.0."""
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
    # Get all exported model classes
    model_names = {
        name for name in dir(models_mod)
        if not name.startswith("_")
    }
    new_models = model_names - known
    assert not new_models, f"Unexpected new models: {new_models}"
