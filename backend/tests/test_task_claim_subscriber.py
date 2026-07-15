"""test_task_claim_subscriber.py — Step 1 skeleton: TASK_CREATED → claim race.

Verifies (no DB / no API / no real LLM):
  - bus.fire(TASK_CREATED) dispatches to the handler
  - handler pulls N available teammates from the in-memory state manager
  - each candidate calls claim() exactly once (the competition)
"""
import pytest

from backend.services.autonomous.event_wakeup import (
    get_event_wakeup_bus, WakeupEvent, WakeupPayload,
)
from backend.services.autonomous.task_claim_subscriber import handle_task_created
from backend.services.autonomous.teammate_state import (
    get_state_manager, TeammateState, TeammateRuntimeState,
)
from backend.services.autonomous.task_claim import get_claim_manager


@pytest.fixture(autouse=True)
def reset_singletons():
    cm = get_claim_manager()
    cm._claims = {}
    cm._owners = {}
    get_state_manager()._states = {}
    yield
    cm._claims = {}
    cm._owners = {}
    get_state_manager()._states = {}


@pytest.mark.asyncio
async def test_task_created_fires_claim_race():
    bus = get_event_wakeup_bus()
    bus.reset()
    sm = get_state_manager()

    n = 3
    for i in range(n):
        await sm.set_active(f"tm_{i}")

    bus.subscribe(WakeupEvent.TASK_CREATED, handle_task_created)
    task_id = "task_race_1"
    bus.fire(WakeupEvent.TASK_CREATED, WakeupPayload(
        event_type=WakeupEvent.TASK_CREATED.value, task_id=task_id,
    ))

    import asyncio
    for _ in range(20):
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)

    claims = await get_claim_manager().get_claims(task_id)
    assert len(claims) == n, f"expected {n} claim attempts, got {len(claims)}"
    winners = [c for c in claims if c.status == "claimed"]
    assert len(winners) == 1


@pytest.mark.asyncio
async def test_task_created_no_candidates_is_noop():
    bus = get_event_wakeup_bus()
    bus.reset()
    sm = get_state_manager()
    sm._states = {"off": TeammateRuntimeState("off")}
    await sm.set_offline("off")

    bus.subscribe(WakeupEvent.TASK_CREATED, handle_task_created)
    bus.fire(WakeupEvent.TASK_CREATED, WakeupPayload(
        event_type=WakeupEvent.TASK_CREATED.value, task_id="task_none",
    ))
    import asyncio
    await asyncio.sleep(0.05)

    claims = await get_claim_manager().get_claims("task_none")
    assert claims == []
