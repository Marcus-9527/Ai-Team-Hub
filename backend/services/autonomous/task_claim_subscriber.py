"""autonomous/task_claim_subscriber.py — TASK_CREATED → claim competition.

Step 1 (skeleton): on TASK_CREATED every available teammate races to
claim the task via TaskClaimManager. This handler ONLY competes for the
claim and logs — it does NOT enter the execution layer. Step 2 wires the
winner into _assign_and_save.

ponytail: candidates come from in-memory TeammateStateManager.list_available();
if no teammate is registered there (the common case before B landed — they're
only added at execution time via executor.set_working), this is a safe no-op.

Race fix (C): the fire-and-forget handler only *triggers* the competition.
The orchestrator awaits run_claim_competition() itself before assigning, so
we never bet on which background task reaches claim() first. The handler is a
thin wrapper that calls the same awaitable helper.
"""
from __future__ import annotations

import logging

from backend.services.autonomous.event_wakeup import WakeupPayload

logger = logging.getLogger("autonomous.task_claim_subscriber")


async def run_claim_competition(task_id: str) -> None:
    """Awaitable competition. Every available teammate claims once.

    Pure claim racing — no execution, no state mutation beyond the claim
    lock. Safe to call from start_task (awaited) or from the wakeup handler.
    """
    if not task_id:
        return

    from backend.services.autonomous.teammate_state import get_state_manager
    candidates = await get_state_manager().list_available()
    if not candidates:
        logger.debug("[Claim] no available teammates to compete for %s",
                     task_id[:8])
        return

    from backend.services.autonomous.task_claim import get_claim_manager
    claim_mgr = get_claim_manager()
    for c in candidates:
        await claim_mgr.claim(
            task_id, c.teammate_id, teammate_name=c.teammate_id,
            reason="TASK_CREATED wakeup competition",
        )
    logger.info("[Claim] %d teammates competed for task %s",
                len(candidates), task_id[:8])


async def handle_task_created(payload: WakeupPayload) -> None:
    """Fire-and-forget entry point for the wakeup bus."""
    await run_claim_competition(payload.task_id)
