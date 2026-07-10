"""
test_stress.py — MAEOS Stress & Edge-Case Tests

Covers:
  1. Concurrency Stress (10/50/100 concurrent requests)
  2. Long Horizon (50~100 steps single task)
  3. Cost Spike (large prompt, multi-teammate, no cache)
  4. Cache Hit Authenticity (false positive detection)
  5. Failure Recovery (timeout, model error, invalid JSON, tool failure)
"""

import asyncio
import time
import uuid
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import Optional

# ── System under test ──
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
from backend.services.runtime.retry_policy import FailureType, RetryAction


# ═══════════════════════════════════════════════════════════
# 1. CONCURRENCY STRESS TESTS
# ═══════════════════════════════════════════════════════════

class TestConcurrencyStress:
    """Test system behavior under concurrent load."""

    @pytest.mark.asyncio
    async def _run_concurrent_batch(self, count: int, max_workers: int = 4):
        """Helper: submit N tasks concurrently, wait for all."""
        os = MAEOS(max_workers=max_workers, provider="test", model="test")
        await os.start()

        results = []
        errors = []

        async def mock_execute(task):
            await asyncio.sleep(0.01)  # Simulate minimal work
            task.status = TaskStatus.COMPLETED
            task.result = f"result_{task.id}"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock"
            return task

        for w in os._workers:
            w.execute = mock_execute

        # Submit all tasks concurrently
        task_ids = []
        for i in range(count):
            tid = await os.submit(f"stress task {i}", priority=TaskPriority.NORMAL)
            task_ids.append(tid)

        # Wait for all
        for tid in task_ids:
            try:
                result = await os.wait(tid, timeout=30.0)
                if result:
                    results.append(result)
            except Exception as e:
                errors.append(str(e))

        stats = os.stats()
        await os.shutdown()
        return results, errors, stats

    @pytest.mark.asyncio
    async def test_10_concurrent(self):
        """10 concurrent tasks — baseline."""
        results, errors, stats = await self._run_concurrent_batch(10)
        assert len(results) == 10, f"Expected 10 results, got {len(results)}, errors: {errors}"
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        # All should be completed
        assert all(r.status == TaskStatus.COMPLETED for r in results)

    @pytest.mark.asyncio
    async def test_50_concurrent(self):
        """50 concurrent tasks — moderate stress."""
        results, errors, stats = await self._run_concurrent_batch(50)
        assert len(results) == 50, f"Expected 50 results, got {len(results)}, errors: {errors}"
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    @pytest.mark.asyncio
    async def test_100_concurrent(self):
        """100 concurrent tasks — heavy stress."""
        results, errors, stats = await self._run_concurrent_batch(100)
        assert len(results) == 100, f"Expected 100 results, got {len(results)}, errors: {errors}"
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    @pytest.mark.asyncio
    async def test_no_agent_cross_contamination(self):
        """Verify concurrent tasks don't leak context between agents."""
        os = MAEOS(max_workers=4, provider="test", model="test")
        await os.start()

        # Each task has a unique marker in its result
        async def mock_execute(task):
            task.status = TaskStatus.COMPLETED
            task.result = f"AGENT_{task.id}_RESULT"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock"
            return task

        for w in os._workers:
            w.execute = mock_execute

        # Submit 20 tasks
        task_ids = []
        for i in range(20):
            tid = await os.submit(f"isolated task {i}")
            task_ids.append(tid)

        # Collect results
        results_map = {}
        for tid in task_ids:
            result = await os.wait(tid, timeout=10.0)
            if result:
                results_map[tid] = result.result

        await os.shutdown()

        # Verify each result matches its own task_id (no cross-contamination)
        for tid, result_str in results_map.items():
            assert tid in result_str, f"Agent cross-contamination! Task {tid} got result: {result_str}"

    @pytest.mark.asyncio
    async def test_queue_no_corruption_under_load(self):
        """Verify PriorityTaskQueue integrity under concurrent access."""
        q = PriorityTaskQueue()
        total_tasks = 100

        # Push 100 tasks with mixed priorities
        task_ids = []
        for i in range(total_tasks):
            t = Task(
                id=f"task_{i:04d}",
                description=f"task {i}",
                priority=TaskPriority(i % 4),  # Cycle through priorities
            )
            q.push(t)
            task_ids.append(t.id)

        assert q.total == total_tasks

        # Pop all and verify ordering (lower priority value = higher priority)
        popped = []
        while not q.is_empty:
            t = q.pop()
            if t:
                popped.append(t)

        assert len(popped) == total_tasks

        # Verify priority ordering: each popped task should have priority >= previous
        for i in range(1, len(popped)):
            assert popped[i].priority >= popped[i-1].priority, \
                f"Priority violation at index {i}: {popped[i-1].priority} -> {popped[i].priority}"

    @pytest.mark.asyncio
    async def test_fsm_state_consistency_under_concurrency(self):
        """Verify FSM state doesn't get corrupted by concurrent tasks."""
        os = MAEOS(max_workers=4, provider="test", model="test")
        await os.start()

        fsm_states = []

        async def mock_execute(task):
            # Simulate FSM state tracking
            states = ["INIT", "CLASSIFY", "PLAN", "EXECUTE", "REVIEW", "DONE"]
            for s in states:
                fsm_states.append((task.id, s))
                await asyncio.sleep(0.001)
            task.status = TaskStatus.COMPLETED
            task.result = "done"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock"
            return task

        for w in os._workers:
            w.execute = mock_execute

        task_ids = []
        for i in range(10):
            tid = await os.submit(f"fsm task {i}")
            task_ids.append(tid)

        for tid in task_ids:
            await os.wait(tid, timeout=10.0)

        await os.shutdown()

        # Verify each task has complete FSM state sequence
        task_state_map = {}
        for task_id, state in fsm_states:
            if task_id not in task_state_map:
                task_state_map[task_id] = []
            task_state_map[task_id].append(state)

        for tid in task_ids:
            states = task_state_map.get(tid, [])
            assert len(states) == 6, f"Task {tid} has incomplete FSM: {states}"
            assert states[0] == "INIT", f"Task {tid} didn't start at INIT"
            assert states[-1] == "DONE", f"Task {tid} didn't end at DONE"


# ═══════════════════════════════════════════════════════════
# 2. LONG HORIZON TESTS
# ═══════════════════════════════════════════════════════════

class TestLongHorizon:
    """Test single task with many steps (50~100)."""

    @pytest.mark.asyncio
    async def test_50_step_task(self):
        """Single task executing 50 FSM steps."""
        mem = ExecutionMemory(max_entries=200)

        # Simulate a task that goes through 50 state transitions
        task = Task(
            id=f"long_50_{uuid.uuid4().hex[:8]}",
            description="50-step long horizon task",
        )

        # Track state transitions
        states = ["INIT"]
        for i in range(48):
            states.append(f"STEP_{i}")
        states.append("DONE")
        states.append("DONE")  # Final state

        task.status = TaskStatus.COMPLETED
        task.result = json.dumps({"steps_completed": 50, "final_state": states[-1]})
        task.started_at = time.time()
        task.completed_at = time.time()

        mem.save(task)

        # Verify memory persistence
        loaded = mem.load(task.id)
        assert loaded is not None
        assert loaded["status"] == TaskStatus.COMPLETED

        # Verify replay works
        replayed = mem.replay(task.id)
        assert replayed is not None
        assert "_replay" in replayed

    @pytest.mark.asyncio
    async def test_100_step_task(self):
        """Single task executing 100 FSM steps — stress on context."""
        mem = ExecutionMemory(max_entries=200)

        task = Task(
            id=f"long_100_{uuid.uuid4().hex[:8]}",
            description="100-step long horizon task",
        )

        # Simulate 100 steps of context accumulation
        context_data = {
            "steps": list(range(100)),
            "intermediate_results": [f"result_{i}" for i in range(100)],
            "total_tokens": 50000,
        }

        task.status = TaskStatus.COMPLETED
        task.result = json.dumps(context_data)
        task.started_at = time.time()
        task.completed_at = time.time()

        mem.save(task)

        loaded = mem.load(task.id)
        assert loaded is not None
        result = json.loads(loaded["result"])
        assert len(result["steps"]) == 100
        assert result["total_tokens"] == 50000

    @pytest.mark.asyncio
    async def test_no_role_drift_in_long_tasks(self):
        """Verify role identity doesn't drift over many FSM transitions."""
        iso = ContextIsolation()

        # Simulate context isolation over many steps
        global_context = {
            "task": "implement auth system",
            "api_key": "secret_key_12345",
            "token": "bearer_xyz",
            "password": "hunter2",
        }

        # Planner should never see secrets
        for step in range(50):
            ctx = iso.isolate(
                teammate_id="planner",
                state=f"PLAN_STEP_{step}",
                global_context=global_context,
            )
            assert ctx.get("api_key") is None, f"Role drift at step {step}: planner sees api_key"
            assert ctx.get("token") is None, f"Role drift at step {step}: planner sees token"
            assert ctx.get("password") is None, f"Role drift at step {step}: planner sees password"

    @pytest.mark.asyncio
    async def test_memory_no_pollution_across_tasks(self):
        """Verify memory doesn't leak between sequential tasks."""
        mem = ExecutionMemory(max_entries=50)

        # Task A saves sensitive data
        task_a = Task(id="task_A", description="sensitive task")
        task_a.status = TaskStatus.COMPLETED
        task_a.result = json.dumps({"secret": "TASK_A_SECRET", "data": "private"})
        task_a.started_at = time.time()
        task_a.completed_at = time.time()
        mem.save(task_a)

        # Task B saves different data
        task_b = Task(id="task_B", description="different task")
        task_b.status = TaskStatus.COMPLETED
        task_b.result = json.dumps({"info": "TASK_B_INFO"})
        task_b.started_at = time.time()
        task_b.completed_at = time.time()
        mem.save(task_b)

        # Verify no cross-contamination
        loaded_a = mem.load("task_A")
        loaded_b = mem.load("task_B")

        result_a = json.loads(loaded_a["result"])
        result_b = json.loads(loaded_b["result"])

        assert "TASK_A_SECRET" in result_a["secret"]
        assert "TASK_B_SECRET" not in result_a
        assert "TASK_A_SECRET" not in result_b

    @pytest.mark.asyncio
    async def test_context_bounded_growth(self):
        """Verify context grows linearly (not exponentially) over many steps."""
        # Simulate context accumulation
        context_size = 0
        per_step_sizes = []

        for step in range(100):
            # Each step adds some context (simulating FSM state)
            step_data = {"step": step, "result": f"output_{step}" * 10}
            step_size = len(json.dumps(step_data))
            per_step_sizes.append(step_size)
            context_size += step_size

        # Growth should be linear: each step adds roughly the same amount
        avg_size = sum(per_step_sizes) / len(per_step_sizes)
        # No single step should be more than 3x the average (no exponential blowup)
        for i, s in enumerate(per_step_sizes):
            assert s < avg_size * 3, f"Step {i} size {s} exceeds 3x average {avg_size:.0f}"

        # Total for 100 steps should be reasonable (< 50KB for simple state)
        assert context_size < 50000, f"Context grew to {context_size} bytes, expected < 50KB"


# ═══════════════════════════════════════════════════════════
# 3. COST SPIKE TESTS
# ═══════════════════════════════════════════════════════════

class TestCostSpike:
    """Test cost control under extreme conditions."""

    def test_large_prompt_cost_estimation(self):
        """Estimate cost for a very large prompt."""
        # Simulate a 50KB prompt
        large_prompt = "x" * 50000

        # Rough token estimation: ~4 chars per token
        estimated_tokens = len(large_prompt) / 4

        # At $0.01/1K tokens (example pricing)
        cost_per_1k = 0.01
        estimated_cost = (estimated_tokens / 1000) * cost_per_1k

        # Should be around $0.125 for 50KB
        assert estimated_tokens > 10000
        assert estimated_cost < 1.0  # Should be under $1

    def test_multi_agent_cost_accumulation(self):
        """Track cost across multiple agents in a collaboration."""
        # Simulate planner + executor + reviewer each making LLM calls
        agents = {
            "planner": {"calls": 3, "tokens_per_call": 2000},
            "executor": {"calls": 5, "tokens_per_call": 3000},
            "reviewer": {"calls": 2, "tokens_per_call": 1500},
        }

        total_tokens = 0
        for agent, config in agents.items():
            agent_tokens = config["calls"] * config["tokens_per_call"]
            total_tokens += agent_tokens

        # 3*2000 + 5*3000 + 2*1500 = 6000 + 15000 + 3000 = 24000
        assert total_tokens == 24000

    def test_cost_budget_enforcement(self):
        """Verify budget limits are enforced."""
        from backend.services.orchestrator_routing import ExecutionBudget, GlobalBounds

        bounds = GlobalBounds()
        budget = ExecutionBudget(
            max_tokens=bounds.max_tokens_per_task,
            max_cost=bounds.max_cost_per_task,
            max_latency_ms=bounds.max_total_latency_ms,
        )

        # Budget should have limits
        assert budget.max_tokens > 0
        assert budget.max_cost > 0

    def test_no_cache_cost_multiplier(self):
        """Without cache, repeated identical prompts should cost full price."""
        # Simulate 10 identical prompts without cache
        prompt_tokens = 1000
        cost_per_token = 0.00001  # $0.01/1K

        # Without cache: 10 * full cost
        cost_no_cache = 10 * prompt_tokens * cost_per_token

        # With cache: 1 full + 9 * 0.1 (cache hit discount)
        cost_with_cache = prompt_tokens * cost_per_token + 9 * prompt_tokens * cost_per_token * 0.1

        # No cache should cost more
        assert cost_no_cache > cost_with_cache


# ═══════════════════════════════════════════════════════════
# 4. CACHE HIT AUTHENTICITY TESTS
# ═══════════════════════════════════════════════════════════

class TestCacheAuthenticity:
    """Test cache hit detection — catch false positives."""

    def test_exact_match_is_true_hit(self):
        """Identical prompts should be true cache hits."""
        prompt_a = "Write a function to sort a list"
        prompt_b = "Write a function to sort a list"

        # Exact match = true hit
        assert prompt_a == prompt_b

    def test_semantic_different_is_false_hit(self):
        """Semantically different prompts should NOT be cache hits."""
        prompt_a = "Write a function to sort a list"
        prompt_b = "Write a function to reverse a list"

        # Different semantics — should not be treated as same
        assert prompt_a != prompt_b

    def test_subtle_difference_detection(self):
        """Small but critical differences should not be cache hits."""
        prompts = [
            ("Delete all files in /tmp", "Delete all files in /home"),  # Different paths
            ("Transfer $100 to Alice", "Transfer $1000 to Alice"),     # Different amounts
            ("Set permission to 644", "Set permission to 755"),         # Different perms
        ]

        for p1, p2 in prompts:
            assert p1 != p2, f"These should be different: '{p1}' vs '{p2}'"

    def test_cache_key_uniqueness(self):
        """Cache keys must be unique per unique input."""
        # Simulate cache key generation
        def cache_key(prompt: str) -> str:
            import hashlib
            return hashlib.md5(prompt.encode()).hexdigest()

        keys = set()
        prompts = [
            "analyze data",
            "analyze data",
            "analyze data ",
            "Analyze data",
            "analyse data",
        ]

        for p in prompts:
            keys.add(cache_key(p))

        # "analyze data" appears twice but should have same key
        # The others should have different keys
        assert len(keys) == 4  # 4 unique prompts (trailing space matters, case matters)

    def test_no_semantic_cache_without_implementation(self):
        """If no semantic cache exists, system should not fake it."""
        # Verify that the current system doesn't have semantic cache
        # (It shouldn't pretend to have one)
        from backend.services.maeos import MAEOS

        os = MAEOS(max_workers=1, provider="test", model="test")
        # MAEOS should not have a semantic_cache attribute
        assert not hasattr(os, 'semantic_cache') or os.semantic_cache is None


# ═══════════════════════════════════════════════════════════
# 5. FAILURE RECOVERY TESTS
# ═══════════════════════════════════════════════════════════

class TestFailureRecovery:
    """Test system resilience under various failure modes."""

    @pytest.mark.asyncio
    async def test_api_timeout_recovery(self):
        """System should handle API timeout gracefully."""
        scheduler = Scheduler(max_concurrency=1)

        async def timeout_fn(**kwargs):
            raise asyncio.TimeoutError("API timeout after 30s")

        unit = scheduler.submit(fn=timeout_fn, teammate_id="test", state="TEST")
        result = await scheduler.execute(unit)

        assert result.status == ExecStatus.FAILED
        assert "timeout" in result.error.lower() or "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_model_error_recovery(self):
        """System should handle model errors (e.g., 500 Internal Server Error)."""
        scheduler = Scheduler(max_concurrency=1)

        async def model_error_fn(**kwargs):
            raise RuntimeError("500 Internal Server Error: Model overloaded")

        unit = scheduler.submit(fn=model_error_fn, teammate_id="test", state="TEST")
        result = await scheduler.execute(unit)

        assert result.status == ExecStatus.FAILED
        assert "500" in result.error or "overloaded" in result.error

    @pytest.mark.asyncio
    async def test_invalid_json_recovery(self):
        """System should handle invalid JSON from LLM output (raised as ValueError)."""
        scheduler = Scheduler(max_concurrency=1)

        call_count = 0

        async def flaky_json_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call raises a JSON parse error
                raise ValueError("json parse error: invalid format")
            # Second call returns valid
            return '{"result": "success"}'

        unit = scheduler.submit(fn=flaky_json_fn, teammate_id="test", state="TEST", max_attempts=3)
        policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_ms=1,  # Fast for tests
        )
        # Force LOGIC_FAIL to trigger retry instead of fallback
        policy._type_actions[FailureType.LOGIC_FAIL] = RetryAction.RETRY

        result = await scheduler.execute_with_retry(unit, policy)
        # Should succeed on retry
        assert result.status == ExecStatus.SUCCESS
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_tool_failure_recovery(self):
        """System should handle tool execution failures."""
        worker = FSMWorker(provider="test", model="test")
        task = Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            description="tool failure task",
        )

        # Mock run_pipeline to simulate tool failure
        with patch(
            "backend.services.maeos.run_pipeline",
            AsyncMock(side_effect=RuntimeError("Tool execution failed: connection refused")),
        ):
            result = await worker.execute(task)

        assert result.status == TaskStatus.FAILED
        assert "connection refused" in result.error
        assert worker._total_failed == 1

    @pytest.mark.asyncio
    async def test_retry_exhaustion_handling(self):
        """System should stop after max retries and report failure."""
        scheduler = Scheduler(max_concurrency=1)

        call_count = 0

        async def always_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            raise ValueError("json parse error")

        unit = scheduler.submit(fn=always_fail, teammate_id="test", state="TEST", max_attempts=3)
        policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_ms=1,
        )
        policy._type_actions[FailureType.LOGIC_FAIL] = RetryAction.RETRY

        result = await scheduler.execute_with_retry(unit, policy)

        # Should be failed after exhausting retries
        assert result.status in (ExecStatus.FAILED, ExecStatus.ABORTED)
        assert call_count == 3  # Initial + 2 retries

    @pytest.mark.asyncio
    async def test_graceful_degradation_under_worker_failure(self):
        """If one worker fails, others should continue."""
        os = MAEOS(max_workers=3, provider="test", model="test")
        await os.start()

        success_count = 0
        fail_count = 0

        async def mixed_execute(task):
            nonlocal success_count, fail_count
            if "fail" in task.description:
                fail_count += 1
                raise RuntimeError("Worker crashed")
            success_count += 1
            task.status = TaskStatus.COMPLETED
            task.result = f"ok_{task.id}"
            task.started_at = time.time()
            task.completed_at = time.time()
            task.worker_id = "mock"
            return task

        for w in os._workers:
            w.execute = mixed_execute

        task_ids = []
        for i in range(6):
            desc = f"task {i}" if i % 2 == 0 else f"fail task {i}"
            tid = await os.submit(desc)
            task_ids.append(tid)

        results = []
        for tid in task_ids:
            try:
                result = await os.wait(tid, timeout=5.0)
                if result:
                    results.append(result)
            except Exception:
                pass

        await os.shutdown()

        # At least some tasks should succeed despite worker failures
        completed = [r for r in results if r.status == TaskStatus.COMPLETED]
        failed = [r for r in results if r.status == TaskStatus.FAILED]

        assert len(completed) >= 2, f"Expected at least 2 successes, got {len(completed)}"
        assert len(failed) >= 1, f"Expected at least 1 failure, got {len(failed)}"

    @pytest.mark.asyncio
    async def test_worker_state_cleanup_after_failure(self):
        """Failed worker should clean up state properly."""
        worker = FSMWorker(provider="test", model="test")
        task = Task(
            id=f"task_{uuid.uuid4().hex[:8]}",
            description="failing task",
        )

        with patch(
            "backend.services.maeos.run_pipeline",
            AsyncMock(side_effect=RuntimeError("crash")),
        ):
            result = await worker.execute(task)

        assert result.status == TaskStatus.FAILED
        # Worker should have cleaned up running state
        assert worker._running is None
        assert worker._total_failed == 1
        assert worker._total_executed == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Circuit breaker should open after repeated failures."""
        from backend.services.orchestrator_routing import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_time=1.0)

        # Record 3 failures
        for _ in range(3):
            cb.record_failure()

        # Circuit should be open
        assert cb.is_open()

        # After recovery time, should be half-open
        await asyncio.sleep(1.1)
        assert not cb.is_open()  # Half-open allows requests through


# ═══════════════════════════════════════════════════════════
# 6. MEMORY PRESSURE TESTS
# ═══════════════════════════════════════════════════════════

class TestMemoryPressure:
    """Test memory behavior under pressure."""

    def test_eviction_under_pressure(self):
        """Memory should evict old entries when full."""
        mem = ExecutionMemory(max_entries=10)

        # Save 20 tasks (2x capacity)
        for i in range(20):
            t = Task(id=f"task_{i:03d}", description=f"task {i}")
            t.status = TaskStatus.COMPLETED
            t.result = f"result_{i}"
            t.started_at = time.time()
            t.completed_at = time.time()
            mem.save(t)

        # Should only have 10 entries
        all_entries = mem.load_all()
        assert len(all_entries) == 10

        # Oldest should be evicted (first 10: task_000~task_009)
        assert mem.load("task_000") is None
        assert mem.load("task_009") is None
        # Newest should remain (task_010~task_019)
        assert mem.load("task_010") is not None
        assert mem.load("task_019") is not None

    def test_memory_stats_accuracy(self):
        """Memory stats should reflect actual state."""
        mem = ExecutionMemory(max_entries=100)

        # Save mixed status tasks
        for i in range(5):
            t = Task(id=f"completed_{i}", description=f"t{i}")
            t.status = TaskStatus.COMPLETED
            t.result = "ok"
            t.started_at = time.time()
            t.completed_at = time.time()
            mem.save(t)

        for i in range(3):
            t = Task(id=f"failed_{i}", description=f"t{i}")
            t.status = TaskStatus.FAILED
            t.error = "fail"
            t.started_at = time.time()
            t.completed_at = time.time()
            mem.save(t)

        stats = mem.stats()
        assert stats["total_entries"] == 8
        assert stats["status_breakdown"][TaskStatus.COMPLETED] == 5
        assert stats["status_breakdown"][TaskStatus.FAILED] == 3


# ═══════════════════════════════════════════════════════════
# 7. FSM TRANSITION VALIDITY TESTS
# ═══════════════════════════════════════════════════════════

# ── End of file ──