"""Phase 3.2 — Brain context integration.

Ultra ponytail: build_prompt già funzionava. Test solo la nuova
sezione team/project context e l'inject in task path.
"""
import pytest
import pytest_asyncio
pytestmark = pytest.mark.asyncio

from backend.services.brain.brain_loader import get_brain_loader
from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.event_processor import MemoryEventProcessor
from backend.models.session import SessionTrigger, TurnAction, TriggerType
from backend.services.session.session_hooks import SessionHooks
from backend.database import engine
from sqlalchemy import text


@pytest_asyncio.fixture(autouse=True)
async def _clean_memory():
    """Clean raw memory_items table between tests."""
    svc = get_memory_service()
    svc._ready = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS memory_items"))
            await conn.commit()
    except Exception:
        pass
    yield


async def _seed_memory(db_session) -> str:
    """Create a trigger + turns → process memory → return teammate_id."""
    hooks = SessionHooks(db_session)
    trig = await hooks.open_trigger(
        channel_id="ch", user_msg_id="",
        workspace_id="ws1", trigger_type=TriggerType.TASK,
    )
    t1 = await hooks.start_turn(trig.id, teammate_id="tm_a")
    t1.turn_type = "plan"
    await db_session.flush()
    await hooks.close_turn(t1.id, action=TurnAction.RESPONDED, tokens_in=10, tokens_out=5)

    t2 = await hooks.start_turn(trig.id, teammate_id="tm_b")
    t2.turn_type = "task"
    await db_session.flush()
    await hooks.close_turn(t2.id, action=TurnAction.RESPONDED, tokens_in=20, tokens_out=15)

    await hooks.close_trigger(trig.id, status="completed")
    await db_session.commit()

    proc = MemoryEventProcessor()
    await proc.process_trigger(db_session, trig.id)
    return "tm_a"


async def test_build_prompt_includes_team_context(db_session):
    """Con workspace_id, build_prompt include TEAM STATE section."""
    tm_id = await _seed_memory(db_session)
    prompt = await get_brain_loader().build_prompt(
        tm_id, workspace_id="ws1", query="test",
    )
    assert "## TEAM STATE" in prompt


async def test_build_prompt_includes_project_context(db_session):
    """Con workspace_id, build_prompt include PROJECT CONTEXT section."""
    tm_id = await _seed_memory(db_session)
    prompt = await get_brain_loader().build_prompt(
        tm_id, workspace_id="ws1", query="test",
    )
    assert "## PROJECT CONTEXT" in prompt
    assert "[project]" in prompt


async def test_no_workspace_skips_team_project(db_session):
    """Senza workspace_id, non ci sono team/project sections."""
    prompt = await get_brain_loader().build_prompt(
        "tm_a", query="test",
    )
    assert "## TEAM STATE" not in prompt
    assert "## PROJECT CONTEXT" not in prompt


async def test_brain_loader_works_without_fragments(db_session):
    """build_prompt non crasha anche senza brain fragments."""
    prompt = await get_brain_loader().build_prompt(
        "nonexistent", workspace_id="ws1", query="test",
    )
    # Senza fragments ma con workspace_id → solo context sections (se ci sono memorie)
    assert isinstance(prompt, str)
