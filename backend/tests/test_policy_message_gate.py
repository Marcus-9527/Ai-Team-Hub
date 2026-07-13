"""test_policy_message_gate.py — Phase 15: Policy gate for messages.

Verifies that check_message_policy is wired and
blocks/skips teammates as configured.
"""
import pytest

from backend.services.task.task_policy import check_message_policy
from backend.database import async_session

pytestmark = pytest.mark.asyncio


async def test_policy_allows_by_default():
    """check_message_policy allows any teammate by default."""
    async with async_session() as db:
        ok, reason = await check_message_policy(
            db, {"id": "tm_a", "name": "Test"}, channel_id="ch_1",
        )
        assert ok is True
        assert reason == ""
