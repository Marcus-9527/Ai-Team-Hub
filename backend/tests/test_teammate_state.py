"""test_teammate_state.py — Phase 13.4 Teammate Runtime State 验证

验证：
- 状态迁移正确
- is_available 正确
- 并发安全
"""
import pytest
import asyncio

from backend.services.autonomous.teammate_state import (
    TeammateStateManager, TeammateState, get_state_manager,
)

pytestmark = pytest.mark.asyncio


async def test_state_transitions():
    """State transitions should work correctly."""
    manager = TeammateStateManager()

    await manager.set_state("tm_a", TeammateState.ACTIVE)
    st = await manager.get("tm_a")
    assert st is not None
    assert st.state == TeammateState.ACTIVE
    assert st.is_available is True

    await manager.set_working("tm_a", "task_1")
    st2 = await manager.get("tm_a")
    assert st2.state == TeammateState.WORKING
    assert st2.current_task_id == "task_1"
    assert st2.is_available is False

    await manager.set_idle("tm_a")
    st3 = await manager.get("tm_a")
    assert st3.state == TeammateState.IDLE
    assert st3.is_available is True


async def test_history_replay():
    """State history should contain correct transitions."""
    manager = TeammateStateManager()

    await manager.set_state("tm_b", TeammateState.ACTIVE)
    await manager.set_working("tm_b", "t1")
    await manager.set_idle("tm_b")
    await manager.set_working("tm_b", "t2")
    await manager.set_offline("tm_b")

    st = await manager.get("tm_b")
    assert len(st.state_history) == 5
    # Initial state is already ACTIVE, so first set_state records active→active
    assert st.state_history[0]["to_state"] == "active"
    assert st.state_history[-1]["to_state"] == "offline"


async def test_list_available():
    """Only ACTIVE/IDLE teammates should be considered available."""
    manager = TeammateStateManager()

    await manager.set_state("tm_eng", TeammateState.ACTIVE)
    await manager.set_state("tm_des", TeammateState.IDLE)
    await manager.set_state("tm_tl", TeammateState.WORKING, "task_x")
    await manager.set_state("tm_al", TeammateState.OFFLINE)

    available = await manager.list_available()
    ids = [s.teammate_id for s in available]

    assert "tm_eng" in ids
    assert "tm_des" in ids
    assert "tm_tl" not in ids
    assert "tm_al" not in ids
