"""autonomous/task_claim_subscriber.py — TASK_CREATED → claim competition.

Step 1 (skeleton): on TASK_CREATED every available teammate races to
claim the task via TaskClaimManager. This handler ONLY competes for the
claim and logs — it does NOT enter the execution layer. Step 2 wires the
winner into _assign_and_save.

ponytail: candidates come from in-memory TeammateStateManager.list_available();
if no teammate is registered there (the common case today — they're only
added at execution time via executor.set_working), this is a safe no-op and
the existing _background_orchestrate path runs untouched. The collision with
_assign_and_save's own claim() only matters once step 2 lands.
"""
from __future__ import annotations

import logging

from backend.services.autonomous.event_wakeup import WakeupPayload

logger = logging.getLogger("autonomous.task_claim_subscriber")


async def handle_task_created(payload: WakeupPayload) -> None:
    task_id = payload.task_id
    if not task_id:
        return

    from backend.services.autonomous.teammate_state import get_state_manager
    candidates = await get_state_manager().list_available()
    if not candidates:
        logger.debug("[ClaimWakeup] no available teammates to compete for %s",
                     task_id[:8])
        return

    from backend.services.autonomous.task_claim import get_claim_manager
    claim_mgr = get_claim_manager()
    for c in candidates:
        await claim_mgr.claim(
            task_id, c.teammate_id, teammate_name=c.teammate_id,
            reason="TASK_CREATED wakeup competition",
        )
    logger.info("[ClaimWakeup] %d teammates competed for task %s",
                len(candidates), task_id[:8])
