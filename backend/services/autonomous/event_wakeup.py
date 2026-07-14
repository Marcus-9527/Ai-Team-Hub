"""autonomous/event_wakeup.py — Event Wakeup Bus (Phase 13.3, cleaned Phase 24)

Pub/sub event bus for teammate wakeup.

Phase 24: removed dead handlers (TASK_CREATED/Failed/REJECTED) that were
never triggered. Only BRAIN_UPDATED remains (fired by brain_proposal on
approval). The bus infrastructure (subscribe/unsubscribe/fire) is kept for
future use.

Events:
  BRAIN_UPDATED      — Brain 片段更新，触发 teammate 重新读取

Design:
  - 事件总线模式 — fire → 订阅者收到通知
  - 每个 teammate 可注册对不同事件的兴趣
  - 不上新 scheduler/FSM — 复用 asyncio.create_task 做 fire-and-forget
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("autonomous.event_wakeup")


class WakeupEvent(Enum):
    BRAIN_UPDATED = "brain_updated"


@dataclass
class WakeupPayload:
    """Data carried with a wakeup event."""
    event_type: str
    task_id: str = ""
    teammate_id: str = ""           # affected teammate (if any)
    channel_id: str = ""
    reason: str = ""                 # additional context
    data: dict = field(default_factory=dict)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "task_id": self.task_id,
            "teammate_id": self.teammate_id,
            "channel_id": self.channel_id,
            "reason": self.reason[:200] if self.reason else "",
            "data": self.data,
            "timestamp": self.timestamp or time.time(),
        }


# Each handler is an async callable that takes a WakeupPayload
EventHandler = Callable[[WakeupPayload], None]  # None = fire-and-forget


class EventWakeupBus:
    """Pub/sub event bus for teammate wakeup.

    Usage:
        bus = get_event_wakeup_bus()
        bus.subscribe(WakeupEvent.BRAIN_UPDATED, handler_fn)
        bus.fire(WakeupEvent.BRAIN_UPDATED, WakeupPayload(teammate_id="..."))

    Each handler is fire-and-forget (via asyncio.ensure_future).
    """

    def __init__(self):
        self._subscribers: dict[WakeupEvent, list[EventHandler]] = {
            e: [] for e in WakeupEvent
        }
        self._history: list[WakeupPayload] = []
        self._max_history = 200

    # ── Subscribe / Unsubscribe ──

    def subscribe(self, event: WakeupEvent, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        if handler not in self._subscribers[event]:
            self._subscribers[event].append(handler)
            logger.debug("[Wakeup] subscriber registered for %s (%d total)",
                         event.value, len(self._subscribers[event]))

    def unsubscribe(self, event: WakeupEvent, handler: EventHandler) -> None:
        """Remove a handler for an event type."""
        if handler in self._subscribers[event]:
            self._subscribers[event].remove(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Remove a handler from all event types."""
        for event in WakeupEvent:
            self.unsubscribe(event, handler)

    # ── Fire Event ──

    def fire(self, event: WakeupEvent, payload: WakeupPayload) -> None:
        """Fire an event — all subscribers get called as fire-and-forget tasks.

        This is synchronous (returns immediately). Subscribers run in background.
        """
        payload.timestamp = payload.timestamp or time.time()

        # Record history
        self._history.append(payload)
        if len(self._history) > self._max_history:
            self._history = self._history[-100:]

        subscribers = list(self._subscribers.get(event, []))
        if not subscribers:
            logger.debug("[Wakeup] event %s fired — no subscribers", event.value)
            return

        for handler in subscribers:
            try:
                asyncio.ensure_future(self._call_handler(handler, payload))
            except Exception as e:
                logger.warning("[Wakeup] handler dispatch failed: %s", e)

        logger.info("[Wakeup] %s fired → %d handlers", event.value, len(subscribers))

    async def _call_handler(self, handler: EventHandler, payload: WakeupPayload) -> None:
        """Safely call a handler handler."""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(payload)
            else:
                handler(payload)
        except Exception as e:
            logger.warning("[Wakeup] handler failed on %s: %s", payload.event_type, e)

    # ── Query ──

    def count_subscribers(self, event: Optional[WakeupEvent] = None) -> int:
        """Return subscriber count. If event is None, return total across all."""
        if event:
            return len(self._subscribers.get(event, []))
        return sum(len(subs) for subs in self._subscribers.values())

    def get_history(
        self,
        event_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get recent wakeup history, optionally filtered by event type."""
        history = self._history
        if event_type:
            history = [p for p in history if p.event_type == event_type]
        return [p.to_dict() for p in history[-limit:]]

    def reset(self) -> None:
        """Clear all subscribers and history (for tests)."""
        self._subscribers = {e: [] for e in WakeupEvent}
        self._history = []


# ── Singleton ──

_wakeup_bus: Optional[EventWakeupBus] = None


def get_event_wakeup_bus() -> EventWakeupBus:
    global _wakeup_bus
    if _wakeup_bus is None:
        _wakeup_bus = EventWakeupBus()
    return _wakeup_bus
