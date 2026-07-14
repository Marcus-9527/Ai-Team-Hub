"""
test_execution_persistence.py - v3.2 Execution Persistence Tests

Tests:
  - restart: data survives engine close/reopen
  - events:  event timeline restored from DB
  - stats:   aggregate statistics correct
"""
import asyncio
import os
import tempfile
import time

import pytest

from backend.services.runtime.execution_store import (
    DBExecutionStore,
    MemoryExecutionStore,
    reset_execution_store,
)


def _tmp_db_url():
    """Return a temp-file SQLite URL (thread-safe, unlike :memory:)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".test-exec.db", delete=False)
    path = tmp.name
    tmp.close()
    return f"sqlite:///{path}", path


# ── Test 1: Data survives restart ──


@pytest.mark.asyncio
async def test_data_survives_restart():
    """Create execution, close engine, reopen, verify record persists."""
    url, path = _tmp_db_url()
    try:
        store = DBExecutionStore(db_url=url)

        rec = store.create(task_id="task-1", model="test/model")
        rec.set_running()
        time.sleep(0.01)
        rec.set_completed(prompt_tokens=100, completion_tokens=50)

        # Verify via the same store
        fetched = await store.aget(rec.execution_id)
        assert fetched is not None, "Should find execution after create+sync"
        assert fetched.task_id == "task-1"
        assert fetched.status == "COMPLETED"
        assert fetched.total_tokens == 150
        assert fetched.cost_micro_usd > 0
        assert len(fetched.events) >= 2  # runtime_start + runtime_complete

        engine1 = store._engine

        # Simulate restart: new store with new engine on the same file
        store_a = DBExecutionStore(db_url=url)
        rec_a = store_a.create(task_id="restart-test", model="m")
        rec_a.set_running()
        rec_a.set_completed(prompt_tokens=50, completion_tokens=25)

        store_a._engine.dispose()
        engine1.dispose()

        store_b = DBExecutionStore(db_url=url)
        fetched_b = await store_b.aget(rec_a.execution_id)
        assert fetched_b is not None, "Data should survive restart"
        assert fetched_b.execution_id == rec_a.execution_id
        assert fetched_b.status == "COMPLETED"
        assert fetched_b.total_tokens == 75
        assert len(fetched_b.events) == len(rec_a.events)

        event_types = [e["type"] for e in fetched_b.events]
        assert "runtime_start" in event_types
        assert "runtime_complete" in event_types

        store_b._engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ── Test 2: Event timeline ──


@pytest.mark.asyncio
async def test_event_timeline():
    """Events stored and retrieved in order."""
    store = DBExecutionStore(db_url="sqlite:///:memory:")

    rec = store.create(task_id="task-evt", model="test/model")
    rec.set_running()
    rec.set_teammate_start("alice")
    rec.add_tool_call("search", "query: hello")
    rec.set_completed(prompt_tokens=10, completion_tokens=20)

    fetched = await store.aget(rec.execution_id)
    assert fetched is not None

    types = [e["type"] for e in fetched.events]
    expected = ["runtime_start", "teammate_start", "tool_call", "runtime_complete"]
    assert types == expected, f"Event order mismatch: {types}"

    # Verify tool call payload
    tool_evt = [e for e in fetched.events if e["type"] == "tool_call"]
    assert len(tool_evt) == 1
    assert tool_evt[0]["data"]["tool"] == "search"

    # Verify runtime_complete
    complete_evt = [e for e in fetched.events if e["type"] == "runtime_complete"]
    assert len(complete_evt) == 1
    assert complete_evt[0]["data"]["status"] == "COMPLETED"


# ── Test 3: Stats ──


@pytest.mark.asyncio
async def test_stats():
    """Aggregate statistics are correct after multiple executions."""
    store = DBExecutionStore(db_url="sqlite:///:memory:")

    # Two completed, one failed
    r1 = store.create(task_id="t1", model="m1")
    r1.set_running()
    r1.set_completed(prompt_tokens=100, completion_tokens=50)

    r2 = store.create(task_id="t2", model="m1")
    r2.set_running()
    r2.set_completed(prompt_tokens=200, completion_tokens=100)

    r3 = store.create(task_id="t3", model="m2")
    r3.set_running()
    r3.set_failed("timeout error")

    stats = await store.astats()
    assert stats["total_executions"] == 3
    assert stats["completed"] == 2
    assert stats["failed"] == 1
    assert stats["running"] == 0
    assert stats["total_tokens"] == 100 + 50 + 200 + 100 + 0  # 450
    assert stats["total_cost_micro_usd"] > 0

    # Filter by status via alist
    completed = await store.alist(status="COMPLETED")
    assert len(completed) == 2
    for r in completed:
        assert r.status == "COMPLETED"

    failed = await store.alist(status="FAILED")
    assert len(failed) == 1
    assert failed[0].status == "FAILED"
    assert "timeout" in failed[0].error


# ── Test 4: Memory store still works (regression) ──


@pytest.mark.asyncio
async def test_memory_store_backward_compat():
    """Memory store still functions correctly."""
    store = MemoryExecutionStore(max_size=100)

    rec = store.create(task_id="mem-test", model="m")
    rec.set_running()
    rec.set_completed(prompt_tokens=10, completion_tokens=5)

    fetched = store.get(rec.execution_id)
    assert fetched is not None
    assert fetched.status == "COMPLETED"

    records = store.list()
    assert len(records) == 1

    stats = store.stats()
    assert stats["total_executions"] == 1
    assert stats["completed"] == 1
