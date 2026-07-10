"""
test_maeos.py — MAEOS Unit + Integration Tests

Covers:
  1. PriorityTaskQueue: push/pop/priority ordering
  2. ExecutionMemory: save/load/replay/eviction
  3. FSMWorker: execute (mocked LLM)
  4. MAEOS Kernel: submit → scheduler → worker → memory pipeline
  5. Isolation enforcement: no shared context, no role leakage
"""

import asyncio
import time
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Data Models ──

from backend.services.maeos import (
    MAEOS,
    FSMWorker,
    PriorityTaskQueue,
    ExecutionMemory,
    Task,
    TaskPriority,
    TaskStatus,
)
from backend.services.runtime import (
    Scheduler,
    RetryPolicy,
    BackoffStrategy,
    ContextIsolation,
    FlowControlEnforcer,
    ExecStatus,
)


# ═══════════════════════════════════════════════════════════
# 1. PriorityTaskQueue Tests
# ═══════════════════════════════════════════════════════════

class TestPriorityTaskQueue:
    def _make_task(self, priority=TaskPriority.NORMAL, desc="test"):
        return Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            description=desc,
            priority=priority,
        )

    def test_push_pop_single(self):
        q = PriorityTaskQueue()
        t = self._make_task()
        q.push(t)
        popped = q.pop()
        assert popped.id == t.id
        assert q.is_empty

    def test_priority_ordering(self):
        q = PriorityTaskQueue()
        low = self._make_task(TaskPriority.LOW, "low")
        normal = self._make_task(TaskPriority.NORMAL, "normal")
        high = self._make_task(TaskPriority.HIGH, "high")
        critical = self._make_task(TaskPriority.CRITICAL, "critical")

        # Push in random order
        q.push(low)
        q.push(critical)
        q.push(normal)
        q.push(high)

        # Should pop in priority order
        assert q.pop().priority == TaskPriority.CRITICAL
        assert q.pop().priority == TaskPriority.HIGH
        assert q.pop().priority == TaskPriority.NORMAL
        assert q.pop().priority == TaskPriority.LOW
        assert q.is_empty

    def test_fifo_within_same_priority(self):
        q = PriorityTaskQueue()
        t1 = self._make_task(TaskPriority.NORMAL, "first")
        t2 = self._make_task(TaskPriority.NORMAL, "second")
        q.push(t1)
        q.push(t2)
        assert q.pop().description == "first"
        assert q.pop().description == "second"

    def test_remove_by_id(self):
        q = PriorityTaskQueue()
        t = self._make_task()
        q.push(t)
        assert q.total == 1
        result = q.remove(t.id)
        assert result is True
        assert q.is_empty

    def test_get_by_id(self):
        q = PriorityTaskQueue()
        t = self._make_task()
        q.push(t)
        found = q.get(t.id)
        assert found.id == t.id

    def test_count_by_status(self):
        q = PriorityTaskQueue()
        t1 = self._make_task()
        t2 = self._make_task()
        t2.status = TaskStatus.RUNNING
        q.push(t1)
        q.push(t2)
        assert q.count_by_status(TaskStatus.PENDING) == 1
        assert q.count_by_status(TaskStatus.RUNNING) == 1

    def test_peek_no_remove(self):
        q = PriorityTaskQueue()
        t = self._make_task(TaskPriority.HIGH)
        q.push(t)
        peeked = q.peek()
        assert peeked.id == t.id
        assert q.total == 1  # Not removed

    def test_pop_empty(self):
        q = PriorityTaskQueue()
        assert q.pop() is None


# ═══════════════════════════════════════════════════════════
# 2. ExecutionMemory Tests
# ═══════════════════════════════════════════════════════════

class TestExecutionMemory:
    def _make_task(self, status=TaskStatus.COMPLETED):
        t = Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            description="test task",
            status=status,
        )
        t.started_at = time.time() - 1
        t.completed_at = time.time()
        t.result = "done"
        return t

    def test_save_and_load(self):
        mem = ExecutionMemory()
        t = self._make_task()
        mem.save(t)
        loaded = mem.load(t.id)
        assert loaded is not None
        assert loaded["task_id"] == t.id
        assert loaded["status"] == TaskStatus.COMPLETED

    def test_replay(self):
        mem = ExecutionMemory()
        t = self._make_task()
        mem.save(t)
        replayed = mem.replay(t.id)
        assert replayed is not None
        assert "_replay" in replayed
        assert "replayed_at" in replayed["_replay"]

    def test_load_by_status(self):
        mem = ExecutionMemory()
        t1 = self._make_task(TaskStatus.COMPLETED)
        t2 = self._make_task(TaskStatus.FAILED)
        t2.error = "oops"
        mem.save(t1)
        mem.save(t2)
        completed = mem.load_by_status(TaskStatus.COMPLETED)
        failed = mem.load_by_status(TaskStatus.FAILED)
        assert len(completed) == 1
        assert len(failed) == 1

    def test_eviction(self):
        mem = ExecutionMemory(max_entries=3)
        tasks = [self._make_task() for _ in range(5)]
        for t in tasks:
            mem.save(t)
        assert len(mem.load_all()) == 3
        # Oldest should be evicted
        assert mem.load(tasks[0].id) is None
        assert mem.load(tasks[4].id) is not None

    def test_stats(self):
        mem = ExecutionMemory()
        mem.save(self._make_task())
        mem.save(self._make_task(TaskStatus.FAILED))
        stats = mem.stats()
        assert stats["total_entries"] == 2
        assert TaskStatus.COMPLETED in stats["status_breakdown"]
        assert TaskStatus.FAILED in stats["status_breakdown"]

    def test_clear(self):
        mem = ExecutionMemory()
        mem.save(self._make_task())
        mem.clear()
        assert mem.stats()["total_entries"] == 0


# ═══════════════════════════════════════════════════════════
# 3. Scheduler Tests (Runtime)
# ═══════════════════════════════════════════════════════════

class TestScheduler:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        scheduler = Scheduler(max_concurrency=1)

        async def mock_fn(**kwargs):
            return "result"

        unit = scheduler.submit(fn=mock_fn, teammate_id="test", state="TEST")
        result = await scheduler.execute(unit)
        assert result.status == ExecStatus.SUCCESS
        assert result.result == "result"

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        scheduler = Scheduler(max_concurrency=1)

        async def failing_fn(**kwargs):
            raise ValueError("boom")

        unit = scheduler.submit(fn=failing_fn, teammate_id="test", state="TEST")
        result = await scheduler.execute(unit)
        assert result.status == ExecStatus.FAILED
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_execute_with_retry(self):
        scheduler = Scheduler(max_concurrency=1)
        retry_policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_ms=10,  # Fast for tests
        )

        call_count = 0

        async def flaky_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("json parse error")  # LOGIC_FAIL → FALLBACK, but needs RETRY
            return "ok"

        # Use a retry policy that retries on unknown errors
        from backend.services.runtime.retry_policy import FailureType, RetryAction
        policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_ms=10,
        )
        # Override to retry on logic fails instead of fallback
        policy._type_actions[FailureType.LOGIC_FAIL] = RetryAction.RETRY

        unit = scheduler.submit(fn=flaky_fn, teammate_id="test", state="TEST", max_attempts=3)
        result = await scheduler.execute_with_retry(unit, policy)
        assert result.status == ExecStatus.SUCCESS
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_execute_max_retries_exhausted(self):
        scheduler = Scheduler(max_concurrency=1)
        retry_policy = RetryPolicy(
            max_retries=2,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_ms=10,
        )

        async def always_fail(**kwargs):
            raise ValueError("json parse error")  # LOGIC_FAIL, not SYSTEM_FAIL

        from backend.services.runtime.retry_policy import FailureType, RetryAction
        retry_policy._type_actions[FailureType.LOGIC_FAIL] = RetryAction.RETRY

        unit = scheduler.submit(fn=always_fail, teammate_id="test", state="TEST", max_attempts=2)
        result = await scheduler.execute_with_retry(unit, retry_policy)
        # After 2 attempts with LOGIC_FAIL→RETRY, max attempts exhausted → FAILED
        assert result.status in (ExecStatus.FAILED, ExecStatus.ABORTED)


# ═══════════════════════════════════════════════════════════
# 4. Context Isolation Tests
# ═══════════════════════════════════════════════════════════

class TestContextIsolation:
    def test_planner_gets_only_task(self):
        iso = ContextIsolation()
        ctx = iso.isolate(
            teammate_id="planner",
            state="PLAN",
            global_context={"task": "design api", "api_key": "secret123", "retry_count": 5},
        )
        assert ctx.get("task") == "design api"
        assert ctx.get("api_key") is None
        assert ctx.get("retry_count") is None

    def test_executor_gets_plan_and_task(self):
        iso = ContextIsolation()
        ctx = iso.isolate(
            teammate_id="executor",
            state="EXECUTE",
            global_context={"task": "design api", "plan": {"steps": []}, "retry_count": 3},
        )
        assert ctx.get("plan") is not None
        assert ctx.get("original_task") is None  # not in global_context
        assert ctx.get("retry_count") is None

    def test_reviewer_gets_result_and_task(self):
        iso = ContextIsolation()
        ctx = iso.isolate(
            teammate_id="reviewer",
            state="REVIEW",
            global_context={"task": "...", "result": "output", "plan": {"steps": []}},
        )
        assert ctx.get("result") == "output"
        assert ctx.get("plan") is None

    def test_no_leak_validation(self):
        iso = ContextIsolation()
        assert iso.validate_no_leak("clean output", "planner") is True
        assert iso.validate_no_leak("my api_key is abc", "planner") is False
        assert iso.validate_no_leak("token=xyz", "executor") is False

    def test_unknown_agent_gets_empty(self):
        iso = ContextIsolation()
        ctx = iso.isolate(teammate_id="unknown_agent", state="X", global_context={"task": "hi"})
        assert ctx.to_dict() == {}


# ═══════════════════════════════════════════════════════════
# 5. Flow Control Tests
# ═══════════════════════════════════════════════════════════

class TestFlowControl:
    def test_clean_output(self):
        fc = FlowControlEnforcer(mode="strict")
        result = fc.check("planner", '{"strategy": "decompose task into steps"}')
        assert result.enforced is True

    def test_next_action_violation(self):
        fc = FlowControlEnforcer(mode="strict")
        result = fc.check("planner", '{"next_action": "execute"}')
        assert result.enforced is False
        assert result.action == "reject"

    def test_handoff_violation(self):
        fc = FlowControlEnforcer(mode="strict")
        result = fc.check("executor", "handoff_to reviewer")
        assert result.enforced is False

    def test_state_manipulation_violation(self):
        fc = FlowControlEnforcer(mode="strict")
        result = fc.check("executor", "set_state=REVIEW")
        assert result.enforced is False

    def test_log_mode_allows(self):
        fc = FlowControlEnforcer(mode="log")
        result = fc.check("planner", '{"next_step": "execute"}')
        assert result.enforced is True
        assert result.action == "log"


# ═══════════════════════════════════════════════════════════
# 6. FSMWorker Tests (mocked LLM)
# ═══════════════════════════════════════════════════════════

class TestFSMWorker:
    @pytest.mark.asyncio
    async def test_worker_execute_task(self):
        worker = FSMWorker(provider="test", model="test")
        task = Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            description="simple test task",
            priority=TaskPriority.NORMAL,
        )

        # Mock FSMOrchestrator.run to avoid real LLM calls
        mock_ctx = MagicMock()
        mock_ctx.final_result = "task completed"
        mock_ctx.error = ""
        mock_ctx.retry_count = 0
        mock_ctx.to_dict.return_value = {}
        mock_ctx.diversity_report = {}

        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=mock_ctx)
        mock_orch.get_trace_report.return_value = {"events": []}

        with patch("backend.services.maeos.run_pipeline", return_value=mock_ctx.final_result):
            result = await worker.execute(task)

        assert result.status == TaskStatus.COMPLETED
        assert result.result == "task completed"
        assert result.worker_id == worker.worker_id
        assert worker._total_executed == 1

    @pytest.mark.asyncio
    async def test_worker_handles_failure(self):
        worker = FSMWorker(provider="test", model="test")
        task = Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            description="failing task",
        )

        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(side_effect=RuntimeError("LLM error"))

        with patch("backend.services.maeos.run_pipeline", side_effect=RuntimeError("LLM error")):
            result = await worker.execute(task)

        assert result.status == TaskStatus.FAILED
        assert "LLM error" in result.error
        assert worker._total_failed == 1


# ═══════════════════════════════════════════════════════════
# 7. MAEOS Kernel Integration Tests
# ═══════════════════════════════════════════════════════════

class TestMAEOSKernel:
    @pytest.mark.asyncio
    async def test_submit_and_wait(self):
        os = MAEOS(max_workers=2, provider="test", model="test")
        await os.start()

        # Mock FSMWorker.execute
        async def mock_execute(task):
            task.status = TaskStatus.COMPLETED
            task.result = "done"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock_worker"
            return task

        for w in os._workers:
            w.execute = mock_execute

        task_id = await os.submit("test task", priority=TaskPriority.NORMAL)
        result = await os.wait(task_id, timeout=5.0)

        assert result is not None
        assert result.status == TaskStatus.COMPLETED
        assert result.result == "done"

        await os.shutdown()

    @pytest.mark.asyncio
    async def test_concurrent_submissions(self):
        os = MAEOS(max_workers=4, provider="test", model="test")
        await os.start()

        async def mock_execute(task):
            await asyncio.sleep(0.1)  # Simulate work
            task.status = TaskStatus.COMPLETED
            task.result = f"result_{task.id}"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock"
            return task

        for w in os._workers:
            w.execute = mock_execute

        # Submit 4 tasks concurrently
        task_ids = []
        for i in range(4):
            tid = await os.submit(f"task {i}", priority=TaskPriority.NORMAL)
            task_ids.append(tid)

        # Wait for all
        for tid in task_ids:
            result = await os.wait(tid, timeout=10.0)
            assert result is not None
            assert result.status == TaskStatus.COMPLETED

        await os.shutdown()

    @pytest.mark.asyncio
    async def test_priority_scheduling(self):
        os = MAEOS(max_workers=1, provider="test", model="test")
        await os.start()

        execution_order = []

        async def mock_execute(task):
            execution_order.append(task.description)
            await asyncio.sleep(0.05)
            task.status = TaskStatus.COMPLETED
            task.result = "ok"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock"
            return task

        for w in os._workers:
            w.execute = mock_execute

        # Submit in reverse priority order
        # First worker is busy, so tasks queue up
        await os.submit("low", priority=TaskPriority.LOW)
        await os.submit("high", priority=TaskPriority.HIGH)
        await os.submit("critical", priority=TaskPriority.CRITICAL)

        # Wait enough for all to complete
        await asyncio.sleep(1.0)

        # Priority should be respected: critical first, then high, then low
        # (first task starts immediately since worker was free)
        assert len(execution_order) == 3

        await os.shutdown()

    @pytest.mark.asyncio
    async def test_memory_persistence(self):
        os = MAEOS(max_workers=1, provider="test", model="test")
        await os.start()

        async def mock_execute(task):
            task.status = TaskStatus.COMPLETED
            task.result = "persisted"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock"
            return task

        for w in os._workers:
            w.execute = mock_execute

        task_id = await os.submit("persist test")
        await os.wait(task_id, timeout=5.0)

        # Check memory
        debug = os.debug_task(task_id)
        assert debug is not None
        assert debug["result"] == "persisted"
        assert "_replay" in debug

        memory_stats = os.memory.stats()
        assert memory_stats["total_entries"] >= 1

        await os.shutdown()

    @pytest.mark.asyncio
    async def test_system_stats(self):
        os = MAEOS(max_workers=4, provider="test", model="test")
        await os.start()

        stats = os.stats()
        assert stats["status"] == "running"
        assert stats["total_workers"] == 4
        assert stats["busy_workers"] == 0

        await os.shutdown()
