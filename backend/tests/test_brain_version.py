"""test_brain_version.py — Phase 12.1 Brain Fragment 版本验证

验证：
- 修改可回滚
- 版本递增
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.brain.fragment_store import (
    BrainFragmentStore, BrainFragment, BrainFragmentType,
    get_brain_fragment_store,
)
from backend.services.memory.memory_types import MemoryItem, MemoryType

pytestmark = pytest.mark.asyncio


async def test_fragment_versioning():
    """Each store() call should auto-increment version."""
    mock_svc = AsyncMock()

    def _fake_query(memory_type=None, source_id=None, limit=100):
        return []

    mock_svc.query = AsyncMock(side_effect=_fake_query)
    mock_svc.query_by_types = AsyncMock(return_value=[])
    mock_svc.store = AsyncMock(return_value="new_id")

    store = BrainFragmentStore(svc=mock_svc)

    # First store → version 1
    f1 = BrainFragment(
        teammate_id="tm_a",
        fragment_type=BrainFragmentType.IDENTITY,
        content="version 1",
        source="manual",
    )
    await store.store(f1)

    saved = mock_svc.store.call_args[0][0]
    assert int(saved.metadata["fragment_version"]) == 1

    # Second store (simulate existing version 1)
    mock_svc.query = AsyncMock(return_value=[
        MemoryItem(
            id="v1",
            memory_type=BrainFragmentType.IDENTITY,
            content="version 1",
            source_id="tm_a",
            metadata={"teammate_id": "tm_a", "fragment_version": 1, "source": "manual"},
        ),
    ])

    f2 = BrainFragment(
        teammate_id="tm_a",
        fragment_type=BrainFragmentType.IDENTITY,
        content="version 2",
        source="manual",
    )
    await store.store(f2)

    saved2 = mock_svc.store.call_args[0][0]
    assert int(saved2.metadata["fragment_version"]) == 2


async def test_rollback():
    """Rollback should copy a previous version's content as a new version."""
    mock_svc = AsyncMock()

    v1_item = MemoryItem(
        id="v1",
        memory_type=BrainFragmentType.IDENTITY,
        content="original content",
        source_id="tm_a",
        metadata={"teammate_id": "tm_a", "fragment_version": 1, "source": "manual"},
    )
    v2_item = MemoryItem(
        id="v2",
        memory_type=BrainFragmentType.IDENTITY,
        content="updated content",
        source_id="tm_a",
        metadata={"teammate_id": "tm_a", "fragment_version": 2, "source": "manual"},
    )

    async def _query(memory_type=None, source_id=None, limit=100):
        return [v2_item, v1_item]  # both versions

    mock_svc.query = AsyncMock(side_effect=_query)
    mock_svc.query_by_types = AsyncMock(return_value=[])
    mock_svc.store = AsyncMock(return_value="new_rollback_id")

    store = BrainFragmentStore(svc=mock_svc)

    new_id = await store.rollback("tm_a", BrainFragmentType.IDENTITY, target_version=1)

    assert new_id is not None
    saved = mock_svc.store.call_args[0][0]
    assert saved.content == "original content"  # rolled-back content
    assert "rollback_from_v1" in saved.metadata["source"]


async def test_get_latest_returns_highest_version():
    """get_latest() should return the highest-versioned fragment."""
    mock_svc = AsyncMock()
    mock_svc.query = AsyncMock(return_value=[
        MemoryItem(
            id="v1",
            memory_type=BrainFragmentType.SKILLS,
            content="old skills",
            source_id="tm_a",
            metadata={"teammate_id": "tm_a", "fragment_version": 1, "source": "manual"},
        ),
        MemoryItem(
            id="v3",
            memory_type=BrainFragmentType.SKILLS,
            content="latest skills",
            source_id="tm_a",
            metadata={"teammate_id": "tm_a", "fragment_version": 3, "source": "manual"},
        ),
    ])
    mock_svc.query_by_types = AsyncMock(return_value=[])

    store = BrainFragmentStore(svc=mock_svc)
    latest = await store.get_latest("tm_a", BrainFragmentType.SKILLS)

    assert latest is not None
    assert latest.version == 3
    assert "latest skills" in latest.content
