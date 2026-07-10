"""
collaboration/shared_context.py — Event-Sourced Shared Workspace

Each task gets a shared context that:
  - All teammates can read/write
  - Is event-sourced (append-only, never overwritten)
  - Supports timeline replay
  - Emits CONTEXT_UPDATED events on every change

Design:
  - ContextEntry: single immutable entry (append-only)
  - SharedContext: per-task workspace with event sourcing
  - ContextStore: manages all shared contexts
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.services.collaboration.event_bus import EventBus, EventType, get_event_bus

logger = logging.getLogger("shared_context")


# ── Context Entry (immutable) ──

@dataclass
class ContextEntry:
    """A single append-only entry in the shared context."""
    key: str
    value: Any
    teammate_id: str           # who wrote this
    entry_id: str = ""
    timestamp: float = 0.0
    previous_value: Any = None  # for audit trail

    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = str(uuid.uuid4())[:12]
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "key": self.key,
            "value": self.value,
            "teammate_id": self.teammate_id,
            "timestamp": self.timestamp,
            "previous_value": self.previous_value,
        }


# ── Shared Context (per-task workspace) ──

class SharedContext:
    """
    Event-sourced shared workspace for a single task.

    All teammates can read/write. Every write creates a new ContextEntry
    (append-only). The current state is derived from the full event log.
    """

    def __init__(self, task_id: str, event_bus: EventBus = None):
        self.task_id = task_id
        self._event_bus = event_bus or get_event_bus()
        self._entries: list[ContextEntry] = []
        self._lock = asyncio.Lock()

    async def write(self, key: str, value: Any, teammate_id: str = "system") -> ContextEntry:
        """
        Write a value to the shared context.

        Creates a new ContextEntry (append-only). Emits CONTEXT_UPDATED event.
        """
        async with self._lock:
            # Find previous value for audit
            previous = None
            for entry in reversed(self._entries):
                if entry.key == key:
                    previous = entry.value
                    break

            entry = ContextEntry(
                key=key,
                value=value,
                teammate_id=teammate_id,
                previous_value=previous,
            )
            self._entries.append(entry)

        # Emit event outside lock
        await self._event_bus.emit(
            event_type=EventType.CONTEXT_UPDATED,
            source=f"teammate:{teammate_id}",
            task_id=self.task_id,
            data={
                "key": key,
                "entry_id": entry.entry_id,
                "previous_value": previous,
            },
        )

        logger.debug(f"[SHARED_CTX] write {key} by {teammate_id} (entry={entry.entry_id})")
        return entry

    def read(self, key: str) -> Optional[Any]:
        """Read the latest value for a key."""
        for entry in reversed(self._entries):
            if entry.key == key:
                return entry.value
        return None

    def read_history(self, key: str) -> list[ContextEntry]:
        """Get full history for a key (timeline replay)."""
        return [e for e in self._entries if e.key == key]

    def read_all(self) -> dict[str, Any]:
        """Get current state (latest value for each key)."""
        state = {}
        for entry in self._entries:
            state[entry.key] = entry.value
        return state

    def get_timeline(self) -> list[dict]:
        """Get full event-sourced timeline for replay."""
        return [e.to_dict() for e in self._entries]

    def replay_to(self, timestamp: float) -> dict[str, Any]:
        """
        Reconstruct state at a specific point in time.
        Used for timeline replay / debugging.
        """
        state = {}
        for entry in self._entries:
            if entry.timestamp <= timestamp:
                state[entry.key] = entry.value
        return state

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def keys(self) -> list[str]:
        return list(set(e.key for e in self._entries))


# ── Context Store (manages all shared contexts) ──

class ContextStore:
    """
    Manages SharedContext instances per task.

    Usage:
        store = get_context_store()
        ctx = store.get_or_create("task_123")
        await ctx.write("plan", {...}, teammate_id="planner")
        current = ctx.read_all()
    """

    def __init__(self, event_bus: EventBus = None):
        self._contexts: dict[str, SharedContext] = {}
        self._event_bus = event_bus or get_event_bus()

    def get_or_create(self, task_id: str) -> SharedContext:
        """Get existing context or create new one."""
        if task_id not in self._contexts:
            self._contexts[task_id] = SharedContext(task_id, self._event_bus)
        return self._contexts[task_id]

    def get(self, task_id: str) -> Optional[SharedContext]:
        """Get existing context (None if not found)."""
        return self._contexts.get(task_id)

    def remove(self, task_id: str) -> bool:
        """Remove a context (cleanup after task completion)."""
        if task_id in self._contexts:
            del self._contexts[task_id]
            return True
        return False

    def list_active(self) -> list[str]:
        """List all active task IDs."""
        return list(self._contexts.keys())

    @property
    def active_count(self) -> int:
        return len(self._contexts)


# ── Singleton ──

_store: Optional[ContextStore] = None


def get_context_store(event_bus: EventBus = None) -> ContextStore:
    global _store
    if _store is None:
        _store = ContextStore(event_bus=event_bus)
    return _store
