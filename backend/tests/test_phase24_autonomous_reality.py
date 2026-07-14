"""test_phase24_autonomous_reality.py — Phase 24 Reality Patch 验证

验证:
1. 两个 teammate 竞争同一 task → 先到先得
2. offline teammate 不会被 TeammateSelector 选中
3. proposal approve 写入 brain fragment
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.autonomous.task_claim import TaskClaimManager
from backend.services.autonomous.teammate_state import TeammateStateManager, TeammateState
from backend.services.autonomous.brain_proposal import BrainProposalManager

pytestmark = pytest.mark.asyncio


# ── 1. Task Claim Competition ──

async def test_competition_first_claim_wins():
    """两个 teammate 竞争同一 task → 先到先得."""
    mgr = TaskClaimManager()
    task_id = "p24_comp_1"

    ok_a, _ = await mgr.claim(task_id, "tm_alpha", "Alpha", "I want this")
    assert ok_a is True
    assert await mgr.get_owner(task_id) == "tm_alpha"

    ok_b, msg_b = await mgr.claim(task_id, "tm_beta", "Beta", "Me too")
    assert ok_b is False
    assert "Already claimed" in msg_b
    assert await mgr.get_owner(task_id) == "tm_alpha"  # 没变


async def test_competition_claim_sets_state():
    """Claim 成功后 teammate 状态变为 WORKING."""
    mgr = TaskClaimManager()
    from backend.services.autonomous.teammate_state import get_state_manager as _get_sm
    state_mgr = _get_sm()
    task_id = "p24_comp_2"

    ok, _ = await mgr.claim(task_id, "tm_gamma", "Gamma")
    assert ok is True

    # ponytail: claim sets state via ensure_future, yield for it
    import asyncio
    await asyncio.sleep(0.01)

    st = await state_mgr.get("tm_gamma")
    assert st is not None
    assert st.state == TeammateState.WORKING
    assert st.current_task_id == task_id


# ── 2. TeammateSelector 排除 offline ──

async def test_selector_skips_offline_teammate(db_session):
    """Offline teammate 不会被 TeammateSelector 选中."""
    from sqlalchemy import select
    from backend.models import Teammate

    # 创建两个 teammate，一个有 engineering skills
    tm_eng = Teammate(
        id="eng_p24", name="Engineer P24", role="engineer",
        skills=["python", "coding"], model_provider="test", model_name="test",
    )
    tm_offline = Teammate(
        id="off_p24", name="Offline P24", role="engineer",
        skills=["python", "coding"], model_provider="test", model_name="test",
    )
    db_session.add_all([tm_eng, tm_offline])
    await db_session.commit()

    # 通过 singleton 设置状态（TeammateSelector 读 singleton）
    from backend.services.autonomous.teammate_state import get_state_manager as _get_sm
    state_mgr = _get_sm()
    await state_mgr.set_state("off_p24", TeammateState.OFFLINE)
    await state_mgr.set_state("eng_p24", TeammateState.ACTIVE)

    from backend.services.teammate_intelligence import TeammateSelector

    top = await TeammateSelector.recommend_by_skills(
        ["python", "coding"], top_n=5, db=db_session,
    )

    ids = [p.id for p in top]
    assert "off_p24" not in ids, "offline teammate 不应出现在结果中"
    assert "eng_p24" in ids, "active 队友应该被选中"


async def test_selector_working_gets_lower_score(db_session):
    """WORKING 状态的 teammate 评分低于 ACTIVE 的."""
    from sqlalchemy import select
    from backend.models import Teammate

    tm_a = Teammate(
        id="active_p24", name="Active P24", role="engineer",
        skills=["python", "coding"], model_provider="test", model_name="test",
    )
    tm_w = Teammate(
        id="working_p24", name="Working P24", role="engineer",
        skills=["python", "coding"], model_provider="test", model_name="test",
    )
    db_session.add_all([tm_a, tm_w])
    await db_session.commit()

    from backend.services.autonomous.teammate_state import get_state_manager as _get_sm
    state_mgr = _get_sm()
    await state_mgr.set_state("active_p24", TeammateState.ACTIVE)
    await state_mgr.set_state("working_p24", TeammateState.WORKING, "task_x")

    from backend.services.teammate_intelligence import TeammateSelector

    top = await TeammateSelector.recommend_by_skills(
        ["python", "coding"], top_n=5, db=db_session,
    )

    ids = [p.id for p in top]
    # Both should appear, but active should be first
    assert "active_p24" in ids
    assert "working_p24" in ids
    assert ids.index("active_p24") < ids.index("working_p24"), \
        "ACTIVE teammate 应在 WORKING 之前"


# ── 3. Proposal Approve 写入 Brain ──

async def test_proposal_approve_updates_brain():
    """Approval 写入 brain fragment store."""
    mgr = BrainProposalManager()

    with patch("backend.services.brain.fragment_store.get_brain_fragment_store") as mock_factory:
        mock_store = AsyncMock()
        mock_store.store.return_value = "frag_abc"
        mock_factory.return_value = mock_store

        prop = await mgr.create(
            teammate_id="tm_brain",
            target_type="brain:identity",
            target_label="Identity",
            proposed_content="I am a Rust expert",
            original_content="I am a Python expert",
            reason="Learning Rust",
        )

        ok, msg = await mgr.approve(prop.id)

    assert ok is True
    assert "approved" in msg
    # verify the store was called with the proposed content
    args, _ = mock_store.store.call_args
    assert args[0].content == "I am a Rust expert"
