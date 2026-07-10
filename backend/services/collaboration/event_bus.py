"""
collaboration/event_bus.py — Global Event Bus (Slack-like Event System)

Architecture:
  - All system actions emit events to a central bus
  - Events are persisted to event log (event-sourced)
  - Subscribers can listen to specific event types
  - Supports async delivery for real-time updates

Event Types:
  - user_message: User sends a message
  - teammate_message: Agent produces output
  - task_created: New task initiated
  - task_updated: Task state changed
  - teammate_completed: Agent finished execution
  - context_updated: Shared context modified
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("event_bus")


# ── Event Types ──

class EventType(str, Enum):
    USER_MESSAGE = "user_message"
    TEAMMATE_MESSAGE = "teammate_message"
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TEAMMATE_COMPLETED = "teammate_completed"
    CONTEXT_UPDATED = "context_updated"
    STATE_TRANSITION = "state_transition"
    STREAM_CHUNK = "stream_chunk"
    ERROR = "error"


# ── Event Data Model ──

@dataclass
class Event:
    """Immutable event record."""
    event_type: str
    source: str           # "user:123", "teammate:strategy", "system:fsm"
    task_id: str = ""
    data: dict = field(default_factory=dict)
    event_id: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.event_id:
            self.event_id = str(uuid.uuid4())[:16]
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ── Subscriber Type ──

EventHandler = Callable[[Event], Awaitable[None]]


# ── Event Bus ──

class EventBus:
    """
    Global event bus with async pub/sub.

    Usage:
        bus = get_event_bus()
        bus.subscribe(EventType.TASK_UPDATED, my_handler)
        bus.emit(EventType.TEAMMATE_COMPLETED, source="teammate:engineer", task_id="...", data={...})
    """

    def __init__(self, max_history: int = 10000):
        self._subscribers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._subscribers[event_type].append(handler)
        logger.debug(f"[EVENT_BUS] subscribe {event_type.value} → {handler.__name__}")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler."""
        handlers = self._subscribers[event_type]
        if handler in handlers:
            handlers.remove(handler)

    async def emit(
        self,
        event_type: EventType,
        source: str = "system",
        task_id: str = "",
        data: Optional[dict] = None,
    ) -> Event:
        """
        Emit an event to all subscribers.

        The event is:
        1. Persisted to in-memory history
        2. Delivered to all matching subscribers (concurrent)
        """
        event = Event(
            event_type=event_type.value,
            source=source,
            task_id=task_id,
            data=data or {},
        )

        async with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # Deliver to subscribers concurrently
        handlers = self._subscribers.get(event_type, [])
        if handlers:
            tasks = [h(event) for h in handlers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[EVENT_BUS] handler {handlers[i].__name__} "
                        f"failed on {event_type.value}: {result}"
                    )

        logger.debug(
            f"[EVENT_BUS] emit {event_type.value} src={source} "
            f"task={task_id} subs={len(handlers)}"
        )
        return event

    def get_history(
        self,
        task_id: Optional[str] = None,
        event_type: Optional[EventType] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query event history with optional filtering."""
        events = self._history
        if task_id:
            events = [e for e in events if e.task_id == task_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type.value]
        return events[-limit:]

    def get_all_events(self) -> list[Event]:
        """Get all events in chronological order."""
        return list(self._history)

    @property
    def subscriber_count(self) -> int:
        return sum(len(h) for h in self._subscribers.values())

    @property
    def event_count(self) -> int:
        return len(self._history)


# ── Singleton ──

_bus: Optional[EventBus] = None


def get_event_bus(max_history: int = 10000) -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus(max_history=max_history)
    return _bus
