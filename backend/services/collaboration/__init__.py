"""
collaboration — Collaboration Layer Package

Modules:
  event_bus.py       — Global event bus with pub/sub
  shared_context.py  — Event-sourced shared workspace
  __init__.py        — Package exports
"""

from backend.services.collaboration.event_bus import (
    Event,
    EventBus,
    EventType,
    get_event_bus,
)
from backend.services.collaboration.shared_context import (
    ContextStore,
    SharedContext,
    get_context_store,
)

__all__ = [
    # Event Bus
    "EventBus",
    "EventType",
    "Event",
    "get_event_bus",
    # Shared Context
    "ContextEntry",
    "SharedContext",
    "ContextStore",
    "get_context_store",
]
