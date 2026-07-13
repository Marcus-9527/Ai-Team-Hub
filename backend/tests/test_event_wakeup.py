"""test_event_wakeup.py — Phase 13.3 Event Wakeup 验证

验证：
- TASK_CREATED 事件触发 teammates
- REVIEW_REJECTED 事件发送通知
- 事件历史记录
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.autonomous.event_wakeup import (
    EventWakeupBus, WakeupEvent, WakeupPayload, get_event_wakeup_bus,
    register_default_handlers,
)

pytestmark = pytest.mark.asyncio


async def test_event_dispatch():
    """Events should reach subscribed handlers."""
    bus = EventWakeupBus()

    calls = []

    async def handler(payload: WakeupPayload):
        calls.append(payload.event_type)

    bus.subscribe(WakeupEvent.TASK_CREATED, handler)

    bus.fire(WakeupEvent.TASK_CREATED, WakeupPayload(
        event_type=WakeupEvent.TASK_CREATED.value,
        task_id="task_1",
        reason="test",
    ))

    # Short wait for async handler
    import asyncio
    await asyncio.sleep(0.05)

    assert len(calls) == 1
    assert calls[0] == WakeupEvent.TASK_CREATED.value


async def test_no_subscribers_no_error():
    """Firing an event with no subscribers should not error."""
    bus = EventWakeupBus()
    bus.fire(WakeupEvent.TASK_CREATED, WakeupPayload(
        event_type=WakeupEvent.TASK_CREATED.value,
        task_id="task_2",
    ))
    # No assertion needed — just no exception


async def test_history():
    """Fired events should appear in history."""
    bus = EventWakeupBus()

    for i in range(5):
        bus.fire(WakeupEvent.TASK_CREATED, WakeupPayload(
            event_type=WakeupEvent.TASK_CREATED.value,
            task_id=f"task_{i}",
        ))

    import asyncio
    await asyncio.sleep(0.05)

    history = bus.get_history(limit=3)
    assert len(history) == 3

    filtered = bus.get_history(event_type=WakeupEvent.TASK_CREATED.value, limit=10)
    assert len(filtered) >= 3


async def test_default_handlers():
    """Default handlers should be registered."""
    bus = EventWakeupBus()
    register_default_handlers(bus)

    assert bus.count_subscribers(WakeupEvent.TASK_CREATED) >= 1
    assert bus.count_subscribers(WakeupEvent.REVIEW_REJECTED) >= 1
