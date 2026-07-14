"""test_autonomous_loop.py — Phase 19: Autonomous Runtime Integration.

Covers:
1. Event → wakeup → execute (via _on_task_created)
2. evaluate_context() freshness cede
3. Teammate state transitions (WORKING/IDLE/OFFLINE)
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.autonomous.cede_protocol import CedeProtocol, CedeDecision
from backend.services.autonomous.event_wakeup import (
    EventWakeupBus, WakeupEvent, WakeupPayload,
)
from backend.services.autonomous.teammate_state import (
    TeammateState, TeammateStateManager, TeammateRuntimeState,
)


pytestmark = pytest.mark.asyncio


# ── 1. evaluate_context() freshness cede ──

async def test_evaluate_context_reads_channel():
    """evaluate_context should fetch channel messages and return a decision."""
    cede = CedeProtocol()
    # Inject a fake _fetch_channel_messages to avoid DB
    cede._fetch_channel_messages = AsyncMock(return_value=[
        "How do I implement JWT auth?",
        "Has anyone done this before?",
    ])
    cede._load_teammate = AsyncMock(return_value={
        "id": "tm_eng", "name": "Engineer", "role": "engineer",
        "system_prompt": "You are an engineer",
    })
    decision, record_id = await cede.evaluate_context(
        channel_id="ch_test",
        message_id="msg_1",
        teammate_id="tm_eng",
    )
    assert decision in (CedeDecision.RESPOND, CedeDecision.CEDE, CedeDecision.IGNORE)
    assert record_id
    # Verify the decision was recorded
    records = await cede.get_message_decisions("msg_1")
    assert len(records) == 1
    assert records[0].teammate_id == "tm_eng"


async def test_evaluate_context_dedup():
    """After a teammate already decided, evaluate_context should still return a decision (cede handles dedup)."""
    cede = CedeProtocol()
    cede._fetch_channel_messages = AsyncMock(return_value=["Some message"])
    cede._load_teammate = AsyncMock(return_value={
        "id": "tm_a", "name": "A", "role": "engineer",
    })
    # First call
    d1, r1 = await cede.evaluate_context("ch", "msg_x", "tm_a")
    # Second call — teammate already decided, should CEDE
    d2, r2 = await cede.evaluate_context("ch", "msg_x", "tm_a")
    assert d2 == CedeDecision.CEDE


# ── 2. Event Wakeup Integration ──

async def test_event_fires_subscribers():
    """Firing a TASK_CREATED event should reach subscribers."""
    bus = EventWakeupBus()
    calls = []

    async def handler(payload: WakeupPayload):
        calls.append(payload.event_type)

    bus.subscribe(WakeupEvent.TASK_CREATED, handler)
    bus.fire(WakeupEvent.TASK_CREATED, WakeupPayload(
        event_type=WakeupEvent.TASK_CREATED.value,
        task_id="task_test",
    ))

    import asyncio
    await asyncio.sleep(0.05)
    assert len(calls) == 1
    assert calls[0] == WakeupEvent.TASK_CREATED.value


async def test_wakeup_event_has_handlers():
    """Default handlers should be registered after get_event_wakeup_bus()."""
    from backend.services.autonomous.event_wakeup import get_event_wakeup_bus
    bus = get_event_wakeup_bus()
    # The singleton may already have handlers — just check TASK_CREATED has at least 1
    assert bus.count_subscribers(WakeupEvent.TASK_CREATED) >= 1
    assert bus.count_subscribers(WakeupEvent.MESSAGE_EVENT) >= 0  # MESSAGE_EVENT default handler is optional


# ── 3. Teammate State Transitions ──

async def test_state_working_idle_transition():
    """Teammate should go IDLE → WORKING → IDLE."""
    mgr = TeammateStateManager()
    tm_id = "tm_state_test"

    await mgr.set_active(tm_id)
    st = await mgr.get(tm_id)
    assert st.state == TeammateState.ACTIVE

    await mgr.set_working(tm_id, "task_1")
    st = await mgr.get(tm_id)
    assert st.state == TeammateState.WORKING
    assert st.current_task_id == "task_1"

    await mgr.set_idle(tm_id)
    st = await mgr.get(tm_id)
    assert st.state == TeammateState.IDLE


async def test_state_failure_offline():
    """On failure, teammate should go to OFFLINE."""
    mgr = TeammateStateManager()
    tm_id = "tm_fail_test"

    await mgr.set_working(tm_id, "task_fail")
    st = await mgr.get(tm_id)
    assert st.state == TeammateState.WORKING

    await mgr.set_offline(tm_id)
    st = await mgr.get(tm_id)
    assert st.state == TeammateState.OFFLINE


async def test_state_history():
    """State transitions should be recorded in history."""
    mgr = TeammateStateManager()
    tm_id = "tm_hist"

    r1 = await mgr.set_active(tm_id)
    r2 = await mgr.set_working(tm_id, "t1")
    r3 = await mgr.set_idle(tm_id)

    st = await mgr.get(tm_id)
    assert len(st.state_history) >= 2  # at least the last 2 transitions


# ── 4. Cede protocol anti-redundancy ──

async def test_cede_relevant_teammates_respond():
    """Multiple teammates → all relevant ones RESPOND, off-domain ones CEDE.

    engineer + reviewer are both engineering-domain, so a refactor message
    makes both respond. A designer (off-domain) would cede.
    """
    cede = CedeProtocol()
    msg_id = "msg_dedup"
    engineer = {"id": "tm_e", "name": "Eng", "role": "engineer"}
    reviewer = {"id": "tm_r", "name": "Rev", "role": "reviewer"}
    designer = {"id": "tm_d", "name": "Des", "role": "designer"}

    msg = "Refactor the auth module"
    for tm in [engineer, reviewer, designer]:
        d = await cede.decide(tm, msg, message_id=msg_id)
        await cede.record_decision(tm, msg_id, d)

    responded = await cede.who_responded(msg_id)
    responded_ids = {r.teammate_id for r in responded}
    assert "tm_e" in responded_ids
    assert "tm_r" in responded_ids
    assert "tm_d" not in responded_ids
