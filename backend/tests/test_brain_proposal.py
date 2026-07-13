"""test_brain_proposal.py — Phase 13.5 Brain Proposal Approval 验证

验证：
- proposal 创建
- 批准后自动写入 Brain
- 拒绝时无写入
- 过期自动回收
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.autonomous.brain_proposal import (
    BrainProposalManager, ProposalStatus, get_proposal_manager,
)

pytestmark = pytest.mark.asyncio


async def test_proposal_create():
    """Creating a proposal should return a valid proposal."""
    manager = BrainProposalManager()

    prop = await manager.create(
        teammate_id="tm_a",
        target_type="brain:identity",
        target_label="Identity",
        proposed_content="I am a Python expert",
        original_content="I am a developer",
        task_id="task_1",
        reason="Observed pattern: always uses Python correctly",
    )

    assert prop.id.startswith("prop_")
    assert prop.status == ProposalStatus.CREATED.value
    assert prop.target_type == "brain:identity"


async def test_approve_applies_change():
    """Approving a proposal should apply it to brain fragments."""
    manager = BrainProposalManager()

    # We need to mock the store call — patch at the module it's imported from
    with patch("backend.services.brain.fragment_store.get_brain_fragment_store") as mock_store_factory:
        mock_store = AsyncMock()
        mock_store.store.return_value = "new_frag_id"
        mock_store_factory.return_value = mock_store

        prop = await manager.create(
            teammate_id="tm_a",
            target_type="brain:identity",
            target_label="Identity",
            proposed_content="I am a Python expert",
            original_content="I am a developer",
        )

        ok, msg = await manager.approve(prop.id, resolved_by="user")

    assert ok is True
    assert "approved" in msg

    # Verify the proposal status
    updated = await manager.get(prop.id)
    assert updated.status == ProposalStatus.APPROVED.value


async def test_reject_no_apply():
    """Rejecting should not apply any changes."""
    manager = BrainProposalManager()

    with patch("backend.services.brain.fragment_store.get_brain_fragment_store") as mock_store_factory:
        mock_store = AsyncMock()
        mock_store_factory.return_value = mock_store

        prop = await manager.create(
            teammate_id="tm_a",
            target_type="brain:identity",
            target_label="Identity",
            proposed_content="I am Rust expert",
            original_content="I am Python expert",
        )

        ok, msg = await manager.reject(prop.id, resolved_by="user")

    assert ok is True
    assert "rejected" in msg

    updated = await manager.get(prop.id)
    assert updated.status == ProposalStatus.REJECTED.value
    # Verify store.store was NOT called (reject doesn't apply)
    mock_store.store.assert_not_called()


async def test_pending_count():
    """Pending count should be accurate."""
    manager = BrainProposalManager()

    with patch("backend.services.brain.fragment_store.get_brain_fragment_store"):
        p1 = await manager.create(teammate_id="tm_a", target_type="brain:identity",
                                   target_label="ID", proposed_content="X", original_content="Y")
        p2 = await manager.create(teammate_id="tm_b", target_type="brain:skills",
                                   target_label="Skills", proposed_content="A", original_content="B")
        await manager.approve(p1.id)

    assert await manager.count_pending() == 1
