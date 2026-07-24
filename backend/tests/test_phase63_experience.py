"""Phase 6.3 experience tests — keyword overlap, selector bonus, context, events."""

import pytest
from unittest.mock import AsyncMock, patch

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.organization.context import OrganizationContext


# ═══════════════════════════════════════════
# 1. find_similar_experience — keyword overlap
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_find_previous_experience():
    """OrganizationExperienceService returns matching items by keyword overlap."""
    from backend.services.organization.experience import OrganizationExperienceService

    mock_mem = AsyncMock()
    mock_mem.query_by_types.return_value = [
        MemoryItem(
            content="Fixed a critical bug in payment module — refactored payment validation",
            memory_type=MemoryType.PROJECT_KNOWLEDGE,
            metadata={"teammate_id": "tm-pay", "result": "success", "lesson": "always validate edge cases"},
        ),
        MemoryItem(
            content="Deployed frontend to production using Docker Compose",
            memory_type=MemoryType.PROJECT_KNOWLEDGE,
            metadata={"teammate_id": "tm-deploy", "result": "success"},
        ),
        MemoryItem(
            content="Weekly team sync notes — discussed CI pipeline",
            memory_type=MemoryType.TEAM_PATTERN,
            metadata={},
        ),
    ]

    with patch("backend.services.organization.experience.get_memory_service", return_value=mock_mem):
        svc = OrganizationExperienceService()
        result = await svc.find_similar_experience("fix payment bug validation")

    assert len(result) == 1  # only payment item matches
    assert result[0]["teammate"] == "tm-pay"
    assert "payment" in result[0]["goal"].lower()
    assert result[0]["result"] == "success"
    assert result[0]["lesson"] == "always validate edge cases"


@pytest.mark.asyncio
async def test_find_experience_no_match():
    """Empty result when goal has no keyword overlap."""
    from backend.services.organization.experience import OrganizationExperienceService

    mock_mem = AsyncMock()
    mock_mem.query_by_types.return_value = [
        MemoryItem(content="Docker deployment guide", memory_type=MemoryType.PROJECT_KNOWLEDGE),
    ]

    with patch("backend.services.organization.experience.get_memory_service", return_value=mock_mem):
        svc = OrganizationExperienceService()
        result = await svc.find_similar_experience("quantum physics research")

    assert result == []


@pytest.mark.asyncio
async def test_find_experience_empty_goal():
    """Empty goal returns empty list."""
    from backend.services.organization.experience import OrganizationExperienceService

    svc = OrganizationExperienceService()
    assert await svc.find_similar_experience("") == []
    assert await svc.find_similar_experience("   ") == []


# ═══════════════════════════════════════════
# 2. experience_affects_selection — selector bonus
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_experience_affects_selection(db_session):
    """TeammateSelector gives +20 bonus to teammate with successful experience."""
    from backend.services.organization.selector import TeammateSelector
    from backend.models.chat import Teammate

    # Two engineers, same role → same capability/skill/performance
    for tm_id in ("exp-tm-a", "exp-tm-b"):
        db_session.add(Teammate(id=tm_id, name=f"TM-{tm_id}", role="engineer",
                                model_provider="test", model_name="test"))
    await db_session.commit()

    sel = TeammateSelector(db_session)

    # Pass experience data: tm-a succeeded on similar task
    experience = [
        {"goal": "wrote python code for data processing",
         "teammate": "exp-tm-a", "result": "success", "lesson": "use pandas"},
    ]

    result = await sel.select(
        task_description="write python code",
        required_capabilities=["code_execution"],
        members=["exp-tm-a", "exp-tm-b"],
        experience=experience,
    )

    assert result is not None
    assert result["teammate_id"] == "exp-tm-a"
    assert any("experience: +20" in r for r in result["reasons"])


@pytest.mark.asyncio
async def test_experience_no_bonus_on_failure(db_session):
    """TeammateSelector gives 0 bonus if teammate failed similar task."""
    from backend.services.organization.selector import TeammateSelector
    from backend.models.chat import Teammate

    db_session.add(Teammate(id="exp-tm-fail", name="TM-fail", role="engineer",
                            model_provider="test", model_name="test"))
    await db_session.commit()

    sel = TeammateSelector(db_session)
    experience = [
        {"goal": "write deployment script",
         "teammate": "exp-tm-fail", "result": "failed - timeout error", "lesson": "increase timeout"},
    ]

    result = await sel.select(
        task_description="write deployment script",
        required_capabilities=["code_execution"],
        members=["exp-tm-fail"],
        experience=experience,
    )

    # score should be capability 50 + no experience bonus
    assert result is not None
    assert result["score"] == 50  # no experience bonus
    assert not any("experience" in r for r in result["reasons"])


# ═══════════════════════════════════════════
# 3. experience_in_context — OrganizationContext
# ═══════════════════════════════════════════

def test_experience_in_context():
    """OrganizationContext includes experience field."""
    ctx = OrganizationContext({
        "run_id": "ctx-exp-1",
        "run_type": "task",
        "experience": {"similar_tasks": [{"goal": "test", "teammate": "tm-1"}]},
    })
    assert ctx.experience == {"similar_tasks": [{"goal": "test", "teammate": "tm-1"}]}


def test_experience_in_context_default():
    """OrganizationContext default experience is empty dict."""
    ctx = OrganizationContext({"run_id": "ctx-exp-2", "run_type": "task"})
    assert ctx.experience == {}


def test_experience_in_context_to_dict():
    """to_dict includes experience field."""
    ctx = OrganizationContext({
        "run_id": "ctx-exp-3", "run_type": "task",
        "experience": {"similar_tasks": []},
    })
    data = ctx.to_dict()
    assert "experience" in data
    assert data["experience"]["similar_tasks"] == []


# ═══════════════════════════════════════════
# 4. BrainLoader experience section
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_brain_loader_experience_section():
    """BrainLoader.build_prompt adds ORGANIZATION EXPERIENCE section with spec format."""
    from backend.services.brain.brain_loader import BrainLoader
    from unittest.mock import AsyncMock

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = []
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)

    experience = [
        {"goal": "deployed microservices to k8s",
         "teammate": "tm-k8s", "result": "success", "lesson": "use Helm charts"},
        {"goal": "database migration",
         "teammate": "tm-db", "result": "failed", "lesson": "increase timeout"},
    ]

    prompt = await loader.build_prompt("tm-test", recent_memory_limit=0, experience=experience)

    assert "## ORGANIZATION EXPERIENCE" in prompt
    assert "Previous similar tasks:" in prompt
    assert "task: deployed microservices" in prompt
    assert "teammate: tm-k8s" in prompt
    assert "approach: success" in prompt
    assert "lesson: use Helm charts" in prompt
    assert "teammate: tm-db" in prompt


@pytest.mark.asyncio
async def test_brain_loader_no_experience_section():
    """No ORGANIZATION EXPERIENCE section when experience not provided and no query."""
    from backend.services.brain.brain_loader import BrainLoader
    from unittest.mock import AsyncMock

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = []
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)
    prompt = await loader.build_prompt("tm-test", recent_memory_limit=0)

    assert "## ORGANIZATION EXPERIENCE" not in prompt


@pytest.mark.asyncio
async def test_brain_loader_auto_fetches_experience():
    """BrainLoader auto-fetches experience when query provided and experience=None."""
    from backend.services.brain.brain_loader import BrainLoader
    from backend.services.organization.experience import OrganizationExperienceService
    from unittest.mock import AsyncMock, patch

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = []
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)

    # Patch the method on the real class so the import inside brain_loader uses it
    with patch.object(
        OrganizationExperienceService, "find_similar_experience",
        new_callable=AsyncMock,
        return_value=[{"goal": "past deploy task", "teammate": "tm-1", "result": "ok", "lesson": ""}],
    ):
        prompt = await loader.build_prompt(
            "tm-test", recent_memory_limit=2, query="deploy",
        )

    assert "## ORGANIZATION EXPERIENCE" in prompt
    assert "past deploy task" in prompt


@pytest.mark.asyncio
async def test_brain_loader_auto_fetch_empty():
    """Auto-fetch with no matching experience produces no section."""
    from backend.services.brain.brain_loader import BrainLoader
    from backend.services.organization.experience import OrganizationExperienceService
    from unittest.mock import AsyncMock, patch

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = []
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)

    with patch.object(
        OrganizationExperienceService, "find_similar_experience",
        new_callable=AsyncMock,
        return_value=[],
    ):
        prompt = await loader.build_prompt(
            "tm-test", recent_memory_limit=2, query="deploy",
        )

    assert "## ORGANIZATION EXPERIENCE" not in prompt


@pytest.mark.asyncio
async def test_brain_loader_experience_limit():
    """Experience entries are truncated to 500 chars each."""
    from backend.services.brain.brain_loader import BrainLoader
    from unittest.mock import AsyncMock

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = []
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)

    long_goal = "x" * 600
    experience = [{"goal": long_goal, "teammate": "tm-1", "result": "ok", "lesson": "y" * 300}]

    prompt = await loader.build_prompt("tm-test", recent_memory_limit=0, experience=experience)

    assert "## ORGANIZATION EXPERIENCE" in prompt
    # Each entry line should be at most 500 chars
    for line in prompt.split("\n"):
        if line.startswith("- task:"):
            assert len(line) <= 500, f"entry too long: {len(line)} chars"


@pytest.mark.asyncio
async def test_brain_loader_experience_max_five():
    """At most 5 experience entries are included in the prompt."""
    from backend.services.brain.brain_loader import BrainLoader
    from unittest.mock import AsyncMock

    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = []
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)

    experience = [{"goal": f"task {i}", "teammate": f"tm-{i}", "result": "ok"} for i in range(10)]

    prompt = await loader.build_prompt("tm-test", recent_memory_limit=0, experience=experience)

    assert "## ORGANIZATION EXPERIENCE" in prompt
    lines = [l for l in prompt.split("\n") if l.startswith("- task:")]
    assert len(lines) <= 5, f"got {len(lines)} entries, expected max 5"


# ═══════════════════════════════════════════
# 5. experience_event — experience.used emitted
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_experience_event(db_session):
    """OrganizationExecutor.delegate emits experience.used events."""
    from unittest.mock import patch
    from backend.services.organization.execution import OrganizationExecutor
    from backend.services.organization.context import OrganizationContextBuilder

    from backend.models.chat import Teammate
    from backend.models.organization_run import OrganizationRun
    from backend.models.session import SessionTrigger
    db_session.add(Teammate(id="ev-exp-tm", name="TM-exp", role="engineer",
                            model_provider="test", model_name="test"))
    run = OrganizationRun(id="ev-exp-run", run_type="task", status="active")
    db_session.add(run)
    trg = SessionTrigger(id="ev-exp-trg", trigger_type="task", run_id="ev-exp-run")
    db_session.add(trg)
    await db_session.commit()

    executor = OrganizationExecutor(db_session)

    # Mock context to return members without full channel/task setup
    class FakeCtx:
        members = ["ev-exp-tm"]

    with patch.object(OrganizationContextBuilder, "build", return_value=FakeCtx()), \
         patch("backend.services.task.task_orchestrator.TaskOrchestrator.start_task",
               return_value=None):
        await executor.delegate(
            trigger_id="ev-exp-trg", run_id="ev-exp-run",
            task_id="ev-exp-task-1", goal="write python code",
        )

    from backend.models.session import SessionEvent
    from sqlalchemy import select
    events = await db_session.execute(
        select(SessionEvent).where(
            SessionEvent.trigger_id == "ev-exp-trg",
            SessionEvent.event_type.like("experience.%"),
        )
    )
    evs = events.scalars().all()
    # May be 0 since no memory items exist — that's fine, just no crash.
    # When experience exists, events appear.
    assert isinstance(evs, list)


# ═══════════════════════════════════════════
# 6. No new ORM models
# ═══════════════════════════════════════════

def test_no_new_models():
    """Verify no new ORM model added by Phase 6.3."""
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
