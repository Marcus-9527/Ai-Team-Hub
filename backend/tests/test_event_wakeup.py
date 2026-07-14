"""test_event_wakeup.py — Event Wakeup Bus 验证 (updated Phase 24)

验证：
- BRAIN_UPDATED 事件分发到订阅者
- 无订阅者时无错误
- 事件历史记录

Phase 24: removed dead handlers (TASK_CREATED/FAILED/REJECTED),
只保留 BRAIN_UPDATED。
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.autonomous.event_wakeup import (
    EventWakeupBus, WakeupEvent, WakeupPayload, get_event_wakeup_bus,
)

pytestmark = pytest.mark.asyncio


async def test_event_dispatch():
    """Events should reach subscribed handlers."""
    bus = EventWakeupBus()

    calls = []

    async def handler(payload: WakeupPayload):
        calls.append(payload.event_type)

    bus.subscribe(WakeupEvent.BRAIN_UPDATED, handler)

    bus.fire(WakeupEvent.BRAIN_UPDATED, WakeupPayload(
        event_type=WakeupEvent.BRAIN_UPDATED.value,
        teammate_id="tm_1",
        reason="test",
    ))

    import asyncio
    await asyncio.sleep(0.05)

    assert len(calls) == 1
    assert calls[0] == WakeupEvent.BRAIN_UPDATED.value


async def test_no_subscribers_no_error():
    """Firing an event with no subscribers should not error."""
    bus = EventWakeupBus()
    bus.fire(WakeupEvent.BRAIN_UPDATED, WakeupPayload(
        event_type=WakeupEvent.BRAIN_UPDATED.value,
        teammate_id="tm_2",
    ))
    # No assertion needed — just no exception


async def test_history():
    """Fired events should appear in history."""
    bus = EventWakeupBus()

    for i in range(5):
        bus.fire(WakeupEvent.BRAIN_UPDATED, WakeupPayload(
            event_type=WakeupEvent.BRAIN_UPDATED.value,
            teammate_id=f"tm_{i}",
        ))

    import asyncio
    await asyncio.sleep(0.05)

    history = bus.get_history(limit=3)
    assert len(history) == 3

    filtered = bus.get_history(event_type=WakeupEvent.BRAIN_UPDATED.value, limit=10)
    assert len(filtered) >= 3
