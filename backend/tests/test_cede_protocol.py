"""test_cede_protocol.py — Phase 13.1 Cede Protocol 验证

验证：
- 多 AI 消息只有一个 RESPOND
- 相同 teammate 不会重复回应
- 决策记录正确
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.autonomous.cede_protocol import (
    CedeProtocol, CedeDecision, get_cede_protocol,
)

pytestmark = pytest.mark.asyncio


async def test_only_one_responds():
    """Multiple teammates → only one should RESPOND to a message."""
    cede = CedeProtocol()
    message_id = "msg_test_1"
    channel_id = "ch_test"

    engineer = {"id": "tm_eng", "name": "Engineer", "role": "engineer"}
    designer = {"id": "tm_des", "name": "Designer", "role": "designer"}

    msg_with_code = "Can you implement a REST API for user authentication?"

    # Engineer should RESPOND (relevant to engineering)
    d1 = await cede.decide(engineer, msg_with_code, channel_id, message_id)
    await cede.record_decision(engineer, message_id, d1, channel_id)

    # Designer should CEDE or IGNORE (not primarily a design task)
    d2 = await cede.decide(designer, msg_with_code, channel_id, message_id)
    await cede.record_decision(designer, message_id, d2, channel_id)

    responded = await cede.who_responded(message_id)

    # Only one RESPOND
    assert len(responded) == 1
    assert responded[0].teammate_id == "tm_eng"
    assert d1 == CedeDecision.RESPOND


async def test_no_duplicate_response():
    """Same teammate should not respond twice to same message."""
    cede = CedeProtocol()
    msg_id = "msg_test_2"

    eng = {"id": "tm_eng", "name": "Engineer", "role": "engineer"}
    msg = "Fix the CSS layout issues"

    # First call → RESPOND
    d1 = await cede.decide(eng, msg, message_id=msg_id)
    assert d1 == CedeDecision.RESPOND
    await cede.record_decision(eng, msg_id, d1)

    # Second call (same teammate, same message) → CEDE
    d2 = await cede.decide(eng, msg, message_id=msg_id)
    assert d2 == CedeDecision.CEDE


async def test_all_decisions_recorded():
    """All respond/cede/ignore decisions should be persisted."""
    cede = CedeProtocol()
    msg_id = "msg_test_3"

    tms = [
        {"id": f"tm_{i}", "name": f"TM{i}", "role": "engineer" if i == 0 else "designer"}
        for i in range(3)
    ]

    msg = "Design a landing page hero section"

    for tm in tms:
        d = await cede.decide(tm, msg, message_id=msg_id)
        await cede.record_decision(tm, msg_id, d)

    decisions = await cede.get_message_decisions(msg_id)

    assert len(decisions) == 3
    assert sum(1 for d in decisions if d.decision == "respond") >= 1
