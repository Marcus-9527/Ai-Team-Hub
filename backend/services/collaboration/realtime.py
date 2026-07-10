"""
collaboration/realtime.py — Real-Time State Sync

Provides:
  - Live task state broadcasting
  - Streaming teammate output delivery
  - Incremental result updates
  - WebSocket connection management

Architecture:
  - StateSync is a bridge between EventBus and WebSocket clients
  - Translates events into sync messages
  - Supports multiple concurrent subscribers per task
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.services.collaboration.event_bus import EventBus, EventType, Event, get_event_bus

logger = logging.getLogger("realtime")


# ── Sync Message Types ──

class SyncType(str, Enum):
    TASK_STATE = "task_state"
    TEAMMATE_OUTPUT = "teammate_output"
    STREAM_CHUNK = "stream_chunk"
    CONTEXT_UPDATE = "context_update"
    ERROR = "error"


# ── Sync Message ──

@dataclass
class SyncMessage:
    """Message sent to real-time subscribers."""
    sync_type: str
    task_id: str
    data: dict = field(default_factory=dict)
    message_id: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.message_id:
            self.message_id = str(uuid.uuid4())[:12]
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "sync_type": self.sync_type,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ── WebSocket Connection (abstract) ──

class Connection:
    """Abstract WebSocket connection wrapper."""

    def __init__(self, conn_id: str = ""):
        self.conn_id = conn_id or str(uuid.uuid4())[:12]
        self.subscribed_tasks: set[str] = set()
        self.connected_at = time.time()

    async def send(self, message: SyncMessage) -> None:
        """Send a sync message. Override in subclass for actual WebSocket."""
        raise NotImplementedError

    def subscribe(self, task_id: str) -> None:
        self.subscribed_tasks.add(task_id)

    def unsubscribe(self, task_id: str) -> None:
        self.subscribed_tasks.discard(task_id)


# ── In-Memory Connection (for testing / non-WS environments) ──

class InMemoryConnection(Connection):
    """In-memory connection that stores messages in a list."""

    def __init__(self, conn_id: str = ""):
        super().__init__(conn_id)
        self.messages: list[SyncMessage] = []

    async def send(self, message: SyncMessage) -> None:
        self.messages.append(message)


# ── State Sync Manager ──

class StateSync:
    """
    Real-time state sync manager.

    Bridges EventBus → WebSocket connections.
    Translates system events into sync messages for clients.

    Usage:
        sync = get_state_sync()
        conn = InMemoryConnection()
        sync.register_connection(conn)
        sync.subscribe_connection(conn.conn_id, "task_123")

        # Events emitted on EventBus are automatically forwarded
    """

    def __init__(self, event_bus: EventBus = None):
        self._event_bus = event_bus or get_event_bus()
        self._connections: dict[str, Connection] = {}
        self._task_subscribers: dict[str, set[str]] = {}  # task_id → {conn_id}

        # Register as event bus subscriber
        self._event_bus.subscribe(EventType.TASK_UPDATED, self._on_task_updated)
        self._event_bus.subscribe(EventType.TEAMMATE_COMPLETED, self._on_teammate_completed)
        self._event_bus.subscribe(EventType.CONTEXT_UPDATED, self._on_context_updated)
        self._event_bus.subscribe(EventType.STREAM_CHUNK, self._on_stream_chunk)
        self._event_bus.subscribe(EventType.ERROR, self._on_error)
        self._event_bus.subscribe(EventType.STATE_TRANSITION, self._on_state_transition)
        self._event_bus.subscribe(EventType.TEAMMATE_MESSAGE, self._on_teammate_message)

    # ── Connection Management ──

    def register_connection(self, conn: Connection) -> None:
        """Register a new connection."""
        self._connections[conn.conn_id] = conn
        logger.debug(f"[STATE_SYNC] register connection {conn.conn_id}")

    def unregister_connection(self, conn_id: str) -> None:
        """Remove a connection and clean up subscriptions."""
        if conn_id in self._connections:
            # Remove from all task subscriptions
            for task_id, subscribers in self._task_subscribers.items():
                subscribers.discard(conn_id)
            del self._connections[conn_id]
            logger.debug(f"[STATE_SYNC] unregister connection {conn_id}")

    def subscribe_connection(self, conn_id: str, task_id: str) -> bool:
        """Subscribe a connection to a specific task."""
        if conn_id not in self._connections:
            return False
        self._connections[conn_id].subscribe(task_id)
        if task_id not in self._task_subscribers:
            self._task_subscribers[task_id] = set()
        self._task_subscribers[task_id].add(conn_id)
        logger.debug(f"[STATE_SYNC] {conn_id} subscribed to {task_id}")
        return True

    def unsubscribe_connection(self, conn_id: str, task_id: str) -> None:
        """Unsubscribe from a task."""
        if conn_id in self._connections:
            self._connections[conn_id].unsubscribe(task_id)
        if task_id in self._task_subscribers:
            self._task_subscribers[task_id].discard(conn_id)

    # ── Event Handlers → Forward to Connections ──

    async def _on_task_updated(self, event: Event) -> None:
        msg = SyncMessage(
            sync_type=SyncType.TASK_STATE,
            task_id=event.task_id,
            data=event.data,
        )
        await self._broadcast(event.task_id, msg)

    async def _on_teammate_completed(self, event: Event) -> None:
        msg = SyncMessage(
            sync_type=SyncType.TEAMMATE_OUTPUT,
            task_id=event.task_id,
            data={"teammate": event.source, **event.data},
        )
        await self._broadcast(event.task_id, msg)

    async def _on_context_updated(self, event: Event) -> None:
        msg = SyncMessage(
            sync_type=SyncType.CONTEXT_UPDATE,
            task_id=event.task_id,
            data=event.data,
        )
        await self._broadcast(event.task_id, msg)

    async def _on_stream_chunk(self, event: Event) -> None:
        msg = SyncMessage(
            sync_type=SyncType.STREAM_CHUNK,
            task_id=event.task_id,
            data=event.data,
        )
        await self._broadcast(event.task_id, msg)

    async def _on_error(self, event: Event) -> None:
        msg = SyncMessage(
            sync_type=SyncType.ERROR,
            task_id=event.task_id,
            data=event.data,
        )
        await self._broadcast(event.task_id, msg)

    async def _on_state_transition(self, event: Event) -> None:
        msg = SyncMessage(
            sync_type=SyncType.TASK_STATE,
            task_id=event.task_id,
            data={"transition": event.data},
        )
        await self._broadcast(event.task_id, msg)

    async def _on_teammate_message(self, event: Event) -> None:
        msg = SyncMessage(
            sync_type=SyncType.TEAMMATE_OUTPUT,
            task_id=event.task_id,
            data={"teammate": event.source, **event.data},
        )
        await self._broadcast(event.task_id, msg)

    # ── Broadcasting ──

    async def _broadcast(self, task_id: str, message: SyncMessage) -> int:
        """Send a message to all subscribers of a task. Returns count sent."""
        subscriber_ids = self._task_subscribers.get(task_id, set())
        sent = 0
        for conn_id in subscriber_ids:
            conn = self._connections.get(conn_id)
            if conn:
                try:
                    await conn.send(message)
                    sent += 1
                except Exception as e:
                    logger.error(f"[STATE_SYNC] send to {conn_id} failed: {e}")
        return sent

    # ── Manual Push (for streaming teammates) ──

    async def push_stream_chunk(
        self, task_id: str, chunk: str, teammate_id: str = "system"
    ) -> int:
        """Push a streaming chunk to all task subscribers."""
        await self._event_bus.emit(
            event_type=EventType.STREAM_CHUNK,
            source=f"teammate:{teammate_id}",
            task_id=task_id,
            data={"chunk": chunk, "teammate_id": teammate_id},
        )
        subscriber_ids = self._task_subscribers.get(task_id, set())
        return len(subscriber_ids)

    async def push_task_state(
        self, task_id: str, state: str, extra: Optional[dict] = None
    ) -> int:
        """Push a task state update."""
        extra = extra or {}
        await self._event_bus.emit(
            event_type=EventType.TASK_UPDATED,
            source="system:sync",
            task_id=task_id,
            data={"state": state, **extra},
        )
        subscriber_ids = self._task_subscribers.get(task_id, set())
        return len(subscriber_ids)

    # ── Stats ──

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def active_tasks(self) -> list[str]:
        return [
            task_id
            for task_id, subs in self._task_subscribers.items()
            if len(subs) > 0
        ]


# ── Singleton ──

_sync: Optional[StateSync] = None


def get_state_sync(event_bus: EventBus = None) -> StateSync:
    global _sync
    if _sync is None:
        _sync = StateSync(event_bus=event_bus)
    return _sync
