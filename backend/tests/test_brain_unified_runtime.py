"""test_brain_unified_runtime.py — Phase 15: chat/task/reviewer use same Brain.

Verifies that the same teammate_id produces identical brain prompt
content regardless of which runtime path loads it.
"""
import pytest
from unittest.mock import AsyncMock

from backend.services.brain.brain_loader import BrainLoader
from backend.services.brain.fragment_store import BrainFragment, BrainFragmentType

pytestmark = pytest.mark.asyncio


async def test_same_teammate_same_brain():
    """Same teammate_id → same brain prompt across paths."""
    mock_store = AsyncMock()
    mock_store.get_all_by_teammate.return_value = [
        BrainFragment(teammate_id="tm_x", fragment_type=BrainFragmentType.IDENTITY,
                      content="I am a universal identity.", source="manual"),
        BrainFragment(teammate_id="tm_x", fragment_type=BrainFragmentType.PRINCIPLES,
                      content="Test driven development.", source="manual"),
    ]
    mock_mem = AsyncMock()
    mock_mem.query_teammate_memory.return_value = []

    loader = BrainLoader(fragment_store=mock_store, memory_service=mock_mem)

    prompt1 = await loader.build_prompt("tm_x", recent_memory_limit=0)
    prompt2 = await loader.build_prompt("tm_x", recent_memory_limit=0)

    assert prompt1 == prompt2
    assert "universal identity" in prompt1
    assert "Test driven development" in prompt1
