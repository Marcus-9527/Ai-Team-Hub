"""
Phase 8 — Organization Memory Consolidation.

Verification:
1. Multiple runs generate cross-run knowledge
2. New teammate automatically forms capability knowledge
3. Same workspace accumulates project knowledge
4. Brain prompt includes knowledge sections
5. Chat and Task produce the same knowledge types
"""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.consolidator import MemoryConsolidator
from backend.services.brain.brain_loader import BrainLoader


@pytest_asyncio.fixture(autouse=True)
async def _clean_memory():
    from backend.database import engine
    from sqlalchemy import text
    svc = get_memory_service()
    svc._ready = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS memory_items"))
            await conn.commit()
    except Exception:
        pass
    yield


async def _seed_member_items(svc, teammate_id, n, outcome="completed"):
    """Seed n scope=member MemoryItems for a teammate."""
    for i in range(n):
        await svc.store(MemoryItem(
            memory_type=MemoryType.TEAMMATE,
            content=f"[chat] teammate {teammate_id} {outcome}",
            source_id=f"run_{i}",
            metadata={
                "scope": "member",
                "teammate_id": teammate_id,
                "turn_type": "chat",
                "outcome": outcome,
                "tool_calls": 2,
                "tokens_total": 500,
                "source": "session_event",
            },
        ))


async def _seed_team_items(svc, n, teammate_ids=None, trigger_type="chat"):
    """Seed n scope=team MemoryItems."""
    for i in range(n):
        await svc.store(MemoryItem(
            memory_type=MemoryType.TEAMMATE,
            content=f"[team] demo collaboration",
            source_id=f"run_{i}",
            metadata={
                "scope": "team",
                "teammate_ids": teammate_ids or ["tm_a", "tm_b"],
                "total_turns": 4,
                "failed_turns": 1 if i > 0 else 0,
                "trigger_type": trigger_type,
                "source": "session_event",
            },
        ))


async def _seed_project_items(svc, n, workspace_id="ws1"):
    """Seed n scope=project MemoryItems."""
    for i in range(n):
        await svc.store(MemoryItem(
            memory_type=MemoryType.TASK,
            content=f"[project] demo project fact",
            source_id=f"run_{i}",
            metadata={
                "scope": "project",
                "workspace_id": workspace_id,
                "task_id": f"task_{i}",
                "tokens_in": 400,
                "tokens_out": 200,
                "failures": 0,
                "source": "session_event",
            },
        ))


# ── 1. Multiple runs → knowledge ──


async def test_multiple_runs_generate_knowledge():
    """After several runs, consolidator aggregates cross-run knowledge."""
    svc = get_memory_service()

    # Simulate 3 runs worth of member + team + project data
    await _seed_member_items(svc, "engineer_1", 3)
    await _seed_member_items(svc, "engineer_2", 1)
    await _seed_team_items(svc, 3)
    await _seed_project_items(svc, 3)

    cons = MemoryConsolidator()
    count = await cons.consolidate_run("test_run")
    assert count > 0, "Should generate knowledge items"

    # Verify member knowledge
    mk_items = await svc.query(memory_type=MemoryType.MEMBER_KNOWLEDGE, limit=10)
    assert len(mk_items) == 2  # engineer_1 + engineer_2
    eng1 = [m for m in mk_items if m.metadata.get("teammate_id") == "engineer_1"][0]
    assert eng1.metadata["total"] == 3
    assert eng1.metadata["successes"] == 3

    # Verify team pattern
    tp_items = await svc.query(memory_type=MemoryType.TEAM_PATTERN, limit=10)
    assert len(tp_items) >= 1
    assert tp_items[0].metadata["total_runs"] == 3

    # Verify project knowledge
    pk_items = await svc.query(memory_type=MemoryType.PROJECT_KNOWLEDGE, limit=10)
    assert len(pk_items) >= 1
    assert pk_items[0].metadata["total_runs"] == 3


# ── 2. New teammate → auto capability ──


async def test_new_teammate_auto_capability():
    """New teammate automatically forms capability knowledge."""
    svc = get_memory_service()
    await _seed_member_items(svc, "new_dev", 2, outcome="completed")
    await _seed_member_items(svc, "new_dev", 1, outcome="failed")

    cons = MemoryConsolidator()
    await cons.consolidate_run("test_run")

    items = await svc.query(memory_type=MemoryType.MEMBER_KNOWLEDGE, limit=10)
    new_dev = [m for m in items if m.metadata.get("teammate_id") == "new_dev"]
    assert len(new_dev) == 1
    nd = new_dev[0]
    assert nd.metadata["total"] == 3
    assert nd.metadata["successes"] == 2
    assert nd.metadata["failures"] == 1
    assert "chat" in nd.metadata["turn_types"]


# ── 3. Same workspace → project knowledge ──


async def test_workspace_accumulates_project_knowledge():
    """Same workspace runs accumulate project knowledge."""
    svc = get_memory_service()
    await _seed_project_items(svc, 2, workspace_id="ws_prod")
    await _seed_project_items(svc, 1, workspace_id="ws_staging")

    cons = MemoryConsolidator()
    await cons.consolidate_run("test_run")

    items = await svc.query(memory_type=MemoryType.PROJECT_KNOWLEDGE, limit=10)
    ws_prod = [m for m in items if m.metadata.get("workspace_id") == "ws_prod"]
    ws_staging = [m for m in items if m.metadata.get("workspace_id") == "ws_staging"]
    assert len(ws_prod) == 1
    assert ws_prod[0].metadata["total_runs"] == 2
    assert len(ws_staging) == 1
    assert ws_staging[0].metadata["total_runs"] == 1


# ── 4. Brain prompt includes knowledge ──


async def test_brain_prompt_includes_knowledge():
    """BrainLoader.build_prompt() includes knowledge sections."""
    svc = get_memory_service()

    # Seed member knowledge
    await svc.store(MemoryItem(
        memory_type=MemoryType.MEMBER_KNOWLEDGE,
        content="[member] eng_1 runs=5 success=4/5",
        source_id="eng_1",
    ))
    await svc.store(MemoryItem(
        memory_type=MemoryType.PROJECT_KNOWLEDGE,
        content="[project] ws1 runs=3 failures=0",
        source_id="ws1",
    ))

    loader = BrainLoader(memory_service=svc)
    prompt = await loader.build_prompt(
        "tm_a", workspace_id="ws1", recent_memory_limit=5,
    )

    assert "## PROJECT KNOWLEDGE" in prompt
    assert "## MEMBER KNOWLEDGE" in prompt
    assert "runs=5" in prompt
    assert "ws1" in prompt
    # Order: knowledge before regular memory
    if "## RECENT EXPERIENCE" in prompt:
        assert prompt.index("## PROJECT KNOWLEDGE") < prompt.index(
            "## RECENT EXPERIENCE"
        )


# ── 5. Chat and Task produce same knowledge types ──


async def test_chat_and_task_unified_knowledge():
    """Chat and Task runs produce the same knowledge type outputs."""
    svc = get_memory_service()

    # Chat runs
    await _seed_member_items(svc, "bot_a", 2)
    await _seed_team_items(svc, 1, ["bot_a", "bot_b"], trigger_type="chat")
    # Task runs
    await _seed_member_items(svc, "engineer_x", 2)
    await _seed_team_items(svc, 1, ["engineer_x", "reviewer_y"], trigger_type="task")

    cons = MemoryConsolidator()
    await cons.consolidate_run("test_run")

    items = await svc.query(limit=50)
    types_found = {i.memory_type for i in items}
    assert MemoryType.MEMBER_KNOWLEDGE in types_found
    assert MemoryType.TEAM_PATTERN in types_found

    # Verify chat & task both contributed
    mk = await svc.query(memory_type=MemoryType.MEMBER_KNOWLEDGE, limit=10)
    teammates = {m.metadata.get("teammate_id") for m in mk}
    assert "bot_a" in teammates
    assert "engineer_x" in teammates
