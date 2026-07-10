"""
tests/test_collaboration.py — Collaboration Layer Tests

Tests for:
  1. EventBus: emit, subscribe, history
  2. SharedContext: write, read, replay, timeline
  3. StateSync: connections, subscriptions, broadcasting
  4. Integration: full event flow
"""

import asyncio
import time
import pytest
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.collaboration import (
    EventBus,
    EventType,
    Event,
    SharedContext,
    ContextStore,
    StateSync,
    InMemoryConnection,
    get_event_bus,
    get_context_store,
    get_state_sync,
)


# ── Event Bus Tests ──

class TestEventBus:
    def setup_method(self):
        self.bus = EventBus()
        self.received: list[Event] = []

    @pytest.mark.asyncio
    async def test_emit_and_receive(self):
        async def handler(event: Event):
            self.received.append(event)

        self.bus.subscribe(EventType.TASK_CREATED, handler)
        await self.bus.emit(
            EventType.TASK_CREATED,
            source="user:123",
            task_id="task_001",
            data={"message": "hello"}
        )

        assert len(self.received) == 1
        assert self.received[0].event_type == "task_created"
        assert self.received[0].task_id == "task_001"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        received_2: list[Event] = []

        async def handler1(event: Event):
            self.received.append(event)

        async def handler2(event: Event):
            received_2.append(event)

        self.bus.subscribe(EventType.TEAMMATE_COMPLETED, handler1)
        self.bus.subscribe(EventType.TEAMMATE_COMPLETED, handler2)
        await self.bus.emit(EventType.TEAMMATE_COMPLETED, source="agent:executor")

        assert len(self.received) == 1
        assert len(received_2) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        async def handler(event: Event):
            self.received.append(event)

        self.bus.subscribe(EventType.TASK_UPDATED, handler)
        await self.bus.emit(EventType.TASK_UPDATED, source="test")
        self.bus.unsubscribe(EventType.TASK_UPDATED, handler)
        await self.bus.emit(EventType.TASK_UPDATED, source="test")

        assert len(self.received) == 1

    @pytest.mark.asyncio
    async def test_history_filtering(self):
        for i in range(5):
            await self.bus.emit(
                EventType.TASK_UPDATED,
                source="test",
                task_id=f"task_{i}",
            )

        all_events = self.bus.get_history(limit=10)
        assert len(all_events) == 5

        filtered = self.bus.get_history(task_id="task_2", limit=10)
        assert len(filtered) == 1
        assert filtered[0].task_id == "task_2"

    @pytest.mark.asyncio
    async def test_no_subscribers_no_error(self):
        # Should not throw when no subscribers
        await self.bus.emit(EventType.ERROR, source="test", data={"error": "test"})
        assert self.bus.event_count == 1

    @pytest.mark.asyncio
    async def test_history_max_cap(self):
        bus = EventBus(max_history=3)
        for i in range(5):
            await bus.emit(EventType.TASK_UPDATED, source="test", task_id=f"t{i}")

        assert len(bus.get_all_events()) == 3
        # Should keep the latest 3
        assert bus.get_all_events()[0].task_id == "t2"

    @pytest.mark.asyncio
    async def test_event_serialization(self):
        event = Event(
            event_type="test",
            source="test",
            task_id="t1",
            data={"key": "value"},
        )
        d = event.to_dict()
        assert d["event_type"] == "test"
        assert d["task_id"] == "t1"
        assert "event_id" in d
        assert "timestamp" in d


# ── Shared Context Tests ──

class TestSharedContext:
    def setup_method(self):
        self.bus = EventBus()
        self.ctx = SharedContext("task_001", event_bus=self.bus)
        self.context_events: list = []

        async def track(event: Event):
            self.context_events.append(event)

        self.bus.subscribe(EventType.CONTEXT_UPDATED, track)

    @pytest.mark.asyncio
    async def test_write_and_read(self):
        await self.ctx.write("plan", {"steps": ["a", "b"]}, teammate_id="planner")
        result = self.ctx.read("plan")
        assert result == {"steps": ["a", "b"]}

    @pytest.mark.asyncio
    async def test_read_nonexistent(self):
        result = self.ctx.read("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_event_emitted_on_write(self):
        await self.ctx.write("key1", "value1", teammate_id="test")
        await asyncio.sleep(0.01)  # Let async emit complete
        assert len(self.context_events) == 1
        assert self.context_events[0].data["key"] == "key1"

    @pytest.mark.asyncio
    async def test_timeline_replay(self):
        await self.ctx.write("status", "pending", teammate_id="system")
        await asyncio.sleep(0.01)
        await self.ctx.write("status", "running", teammate_id="executor")
        await asyncio.sleep(0.01)
        await self.ctx.write("status", "completed", teammate_id="executor")

        history = self.ctx.read_history("status")
        assert len(history) == 3
        assert history[0].value == "pending"
        assert history[2].value == "completed"

    @pytest.mark.asyncio
    async def test_replay_to_timestamp(self):
        t0 = time.time()
        await self.ctx.write("x", 1, teammate_id="test")
        await asyncio.sleep(0.05)
        t1 = time.time()
        await self.ctx.write("x", 2, teammate_id="test")
        await asyncio.sleep(0.05)
        t2 = time.time()
        await self.ctx.write("x", 3, teammate_id="test")

        state_at_t1 = self.ctx.replay_to(t1)
        assert state_at_t1["x"] == 1  # Only first write before t1

        state_at_t2 = self.ctx.replay_to(t2)
        assert state_at_t2["x"] == 2  # First two writes before t2

    @pytest.mark.asyncio
    async def test_read_all(self):
        await self.ctx.write("a", 1, teammate_id="test")
        await self.ctx.write("b", 2, teammate_id="test")
        await self.ctx.write("a", 3, teammate_id="test")  # Overwrite a

        all_state = self.ctx.read_all()
        assert all_state["a"] == 3
        assert all_state["b"] == 2

    @pytest.mark.asyncio
    async def test_audit_trail(self):
        await self.ctx.write("config", {"mode": "simple"}, teammate_id="planner")
        await asyncio.sleep(0.01)
        await self.ctx.write("config", {"mode": "complex"}, teammate_id="reviewer")

        history = self.ctx.read_history("config")
        assert len(history) == 2
        assert history[1].previous_value == {"mode": "simple"}


# ── Context Store Tests ──

class TestContextStore:
    def setup_method(self):
        self.bus = EventBus()
        self.store = ContextStore(event_bus=self.bus)

    @pytest.mark.asyncio
    async def test_get_or_create(self):
        ctx1 = self.store.get_or_create("task_1")
        ctx2 = self.store.get_or_create("task_1")
        assert ctx1 is ctx2

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        result = self.store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_remove(self):
        self.store.get_or_create("task_1")
        assert self.store.remove("task_1") is True
        assert self.store.get("task_1") is None

    @pytest.mark.asyncio
    async def test_list_active(self):
        self.store.get_or_create("task_1")
        self.store.get_or_create("task_2")
        active = self.store.list_active()
        assert "task_1" in active
        assert "task_2" in active
        assert self.store.active_count == 2


# ── State Sync Tests ──

class TestStateSync:
    def setup_method(self):
        self.bus = EventBus()
        self.sync = StateSync(event_bus=self.bus)
        self.conn1 = InMemoryConnection("conn_1")
        self.conn2 = InMemoryConnection("conn_2")

    @pytest.mark.asyncio
    async def test_register_and_subscribe(self):
        self.sync.register_connection(self.conn1)
        self.sync.register_connection(self.conn2)
        assert self.sync.connection_count == 2

        self.sync.subscribe_connection("conn_1", "task_1")
        self.sync.subscribe_connection("conn_2", "task_1")
        assert "task_1" in self.conn1.subscribed_tasks

    @pytest.mark.asyncio
    async def test_broadcast_on_event(self):
        self.sync.register_connection(self.conn1)
        self.sync.subscribe_connection("conn_1", "task_1")

        await self.bus.emit(
            EventType.TASK_UPDATED,
            source="system",
            task_id="task_1",
            data={"state": "running"}
        )
        await asyncio.sleep(0.01)  # Let async dispatch complete

        assert len(self.conn1.messages) == 1
        assert self.conn1.messages[0].sync_type == "task_state"

    @pytest.mark.asyncio
    async def test_no_broadcast_to_unsubscribed(self):
        self.sync.register_connection(self.conn1)
        self.sync.register_connection(self.conn2)
        self.sync.subscribe_connection("conn_1", "task_1")

        await self.bus.emit(
            EventType.TEAMMATE_COMPLETED,
            source="agent:executor",
            task_id="task_1",
        )
        await asyncio.sleep(0.01)

        assert len(self.conn1.messages) == 1
        assert len(self.conn2.messages) == 0

    @pytest.mark.asyncio
    async def test_unregister_cleans_subscriptions(self):
        self.sync.register_connection(self.conn1)
        self.sync.subscribe_connection("conn_1", "task_1")
        self.sync.unregister_connection("conn_1")

        assert self.sync.connection_count == 0

    @pytest.mark.asyncio
    async def test_push_stream_chunk(self):
        self.sync.register_connection(self.conn1)
        self.sync.subscribe_connection("conn_1", "task_stream")

        await self.sync.push_stream_chunk("task_stream", "Hello ", "agent:executor")
        await self.sync.push_stream_chunk("task_stream", "World!", "agent:executor")
        await asyncio.sleep(0.01)

        assert len(self.conn1.messages) == 2
        assert self.conn1.messages[0].data["chunk"] == "Hello "
        assert self.conn1.messages[1].data["chunk"] == "World!"


# ── Integration Test ──

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_event_flow(self):
        """Simulate a complete task lifecycle with collaboration layer."""
        bus = EventBus()
        store = ContextStore(event_bus=bus)
        sync = StateSync(event_bus=bus)

        # Setup connection
        conn = InMemoryConnection("client_1")
        sync.register_connection(conn)
        sync.subscribe_connection("client_1", "task_full")

        # 1. Task created
        await bus.emit(EventType.TASK_CREATED, source="user:1", task_id="task_full")

        # 2. Get shared context
        ctx = store.get_or_create("task_full")

        # 3. Planner writes plan
        await ctx.write(
            "plan",
            {"steps": ["analyze", "implement", "review"]},
            teammate_id="planner",
        )

        # 4. Executor updates state
        await ctx.write("status", "executing", teammate_id="executor")
        await bus.emit(
            EventType.TEAMMATE_COMPLETED,
            source="agent:executor",
            task_id="task_full",
            data={"step": "implement", "status": "success"},
        )

        # 5. Verify client received updates
        await asyncio.sleep(0.05)
        assert len(conn.messages) >= 2  # Task created + agent completed + more

        # 6. Verify shared context state
        assert ctx.read("status") == "executing"
        assert ctx.read("plan") == {"steps": ["analyze", "implement", "review"]}

        # 7. Verify event history
        all_events = bus.get_history(task_id="task_full")
        assert len(all_events) >= 3

    @pytest.mark.asyncio
    async def test_collaboration_does_not_break_isolation(self):
        """Execution isolation remains — agents see only their inputs."""
        bus = EventBus()
        store = ContextStore(event_bus=bus)

        ctx_task1 = store.get_or_create("task_a")
        ctx_task2 = store.get_or_create("task_b")

        await ctx_task1.write("secret", "task_a_secret", teammate_id="executor")
        await ctx_task2.write("secret", "task_b_secret", teammate_id="executor")

        # Each task sees only its own context
        assert ctx_task1.read("secret") == "task_a_secret"
        assert ctx_task2.read("secret") == "task_b_secret"
