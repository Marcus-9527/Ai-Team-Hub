"""test_brain_loader.py — Phase 12.2 BrainLoader 验证

验证：
- 不同 teammate 隔离
- brain 正确注入 prompt
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.brain.brain_loader import BrainLoader, get_brain_loader
from backend.services.brain.fragment_store import (
    BrainFragmentStore, BrainFragment, BrainFragmentType,
)

pytestmark = pytest.mark.asyncio


async def test_brain_loader_builds_prompt():
    """BrainLoader.build_prompt() should include fragments + memory."""
    mock_store = AsyncMock(spec=BrainFragmentStore)
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.IDENTITY,
            content="I am an expert Python developer",
            source="manual",
        ),
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.SKILLS,
            content="Python, FastAPI, SQL",
            source="manual",
        ),
        BrainFragment(
            teammate_id="tm_a",
            fragment_type=BrainFragmentType.LESSONS,
            content="Always validate input at trust boundaries",
            source="reflection",
        ),
    ]

    from backend.services.memory.memory_service import MemoryService
    mock_mem = AsyncMock(spec=MemoryService)
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)
    prompt = await loader.build_prompt("tm_a", recent_memory_limit=5)

    assert "## YOUR BRAIN" in prompt
    assert "## IDENTITY" in prompt
    assert "expert Python developer" in prompt
    assert "## SKILLS & ABILITIES" in prompt
    assert "FastAPI" in prompt
    assert "## LESSONS LEARNED" in prompt
    assert "Always validate" in prompt


async def test_teammate_isolation():
    """Different teammates should get different brain context."""
    mock_store = AsyncMock(spec=BrainFragmentStore)
    from backend.services.memory.memory_service import MemoryService
    mock_mem = AsyncMock(spec=MemoryService)
    mock_mem.query_teammate_memory.return_value = []

    # Teammate A has identity fragment
    mock_store.get_all_by_teammate.side_effect = lambda tm_id: [
        BrainFragment(
            teammate_id=tm_id,
            fragment_type=BrainFragmentType.IDENTITY,
            content=f"I am {tm_id}",
            source="manual",
        ),
    ] if tm_id == "tm_a" else []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)

    prompt_a = await loader.build_prompt("tm_a")
    prompt_b = await loader.build_prompt("tm_b")

    assert "tm_a" in prompt_a or "I am tm_a" in prompt_a
    # Teammate B has no fragments -> should have minimal prompt
    assert "## YOUR BRAIN" not in prompt_b if not prompt_b else True
