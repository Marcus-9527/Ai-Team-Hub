"""test_autonomous_real_flow.py — Phase 15: event → cede → respond chain.

Verifies end-to-end autonomous flow:
1. Event/message arrives
2. Cede protocol evaluates each teammate
3. Only responding teammates proceed
4. Ceded teammates are excluded
"""
import pytest

from backend.services.autonomous.cede_protocol import CedeProtocol, CedeDecision

pytestmark = pytest.mark.asyncio


async def test_autonomous_event_cede_respond_chain():
    """Event → Cede → Respond chain works end-to-end."""
    cede = CedeProtocol()
    channel_id = "ch_auto"
    message_id = "msg_auto_1"

    engineer = {"id": "tm_e", "name": "Engineer", "role": "engineer",
                "system_prompt": "Engineer"}
    reviewer = {"id": "tm_r", "name": "Reviewer", "role": "reviewer",
                "system_prompt": "Reviewer"}

    content = "Refactor the auth module to use JWT"

    # Simulate messages.py flow: cede check for each teammate
    active = []
    for tm in [engineer, reviewer]:
        decision = await cede.decide(tm, content, channel_id=channel_id,
                                     message_id=message_id)
        await cede.record_decision(tm, message_id, decision, channel_id=channel_id)
        if decision.value == "respond":
            active.append(tm)

    # At least one should respond
    assert len(active) >= 1
    assert any(tm["id"] == "tm_e" for tm in active)

    # Verify cede records exist
    records = await cede.get_message_decisions(message_id)
    assert len(records) == 2  # both engineers and reviewers decided
    assert all(r.message_id == message_id for r in records)
