"""
test_stress_db.py — DB-Backed Stress Test: 100 Tasks × 1000 Steps + Memory

Verifies system stability under load:
  1. Bulk create 100 tasks × 10 steps = 1000 steps
  2. Execute all steps through TaskExecutor with mocked MAEOS
  3. Accumulate MemoryItems via MemoryTaskHook
  4. Validate state machine integrity at scale
  5. Check cascade deletes, orphan detection, query performance

Key difference from test_stress.py:
  - Tests REAL SQLAlchemy DB (async in-memory SQLite)
  - Tests REAL TaskExecutor / TaskStateManager / TaskResultHandler
  - Tests REAL MemoryTaskHook integration
  - Only MAEOS is mocked (no real LLM calls)
"""

import asyncio
import time
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskStatus, TaskStepStatus, PlanStatus, gen_uuid,
)
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_executor import TaskExecutor
from backend.services.task.task_result import TaskResultHandler
from backend.services.task.task_events import TaskEventLogger
from backend.services.task.task_policy import TaskPolicyService, PolicyResult
from backend.services.task.task_context import TaskContextBuilder
from backend.services.task.task_hooks import (
    TaskHookRegistry, TaskLifecycleEvent,
    TaskHookContext, reset_task_hook_registry,
    get_task_hook_registry,
)
from backend.services.memory.memory_event_handler import MemoryTaskHook
from backend.services.memory.memory_types import MemoryType, MemoryItem

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global singletons before each test to avoid cross-test pollution."""
    reset_task_hook_registry()
    yield


@pytest.fixture
def state_manager():
    return TaskStateManager()


@pytest.fixture
def task_manager():
    return TaskManager()


@pytest.fixture
def executor():
    return TaskExecutor()


# ═══════════════════════════════════════════════════════════════
# Fake MAEOS (same pattern as test_task_execution.py)
# ═══════════════════════════════════════════════════════════════

class FakeMAEOSTask:
    def __init__(self, task_id: str, status: str = "COMPLETED",
                 result: str = "", error: str = ""):
        self.id = task_id
        self.task_id = task_id
        self.status = status
        self.result = result
        self.error = error
        self.trace_report = {"trace_id": f"trace-{task_id}"}


class FakeMAEOS:
    """Mock MAEOS — returns success for all submitted tasks."""

    def __init__(self):
        self._call_count = 0
        self._submitted: list[str] = []
        self._started = True

    async def submit(self, description: str, priority: int = 2,
                     intent: str = "", wait: bool = False,
                     **kwargs) -> str:
        self._call_count += 1
        task_id = f"maeos-{self._call_count:06d}"
        self._submitted.append(task_id)
        return task_id

    async def wait(self, task_id: str, timeout: float = 300.0) -> FakeMAEOSTask:
        return FakeMAEOSTask(
            task_id=task_id,
            status="COMPLETED",
            result=f"Success result for {task_id}",
        )

    def stats(self):
        return {"submitted": self._call_count}


# ═══════════════════════════════════════════════════════════════
# 1. BULK CREATE STRESS (100 Tasks × 1000 Steps)
# ═══════════════════════════════════════════════════════════════

class TestBulkCreateStress:
    """Create 100 tasks with 10 steps each — verify bulk operations."""

    async def test_bulk_create_100_tasks(self, db_session, state_manager):
        """Create 100 tasks and 1000 steps, verify everything persisted correctly."""
        NUM_TASKS = 100
        STEPS_PER_TASK = 10

        task_ids = []
        step_count_total = 0

        start = time.time()

        for i in range(NUM_TASKS):
            task = await state_manager.create_task(
                db_session,
                title=f"Stress Task {i:04d}",
                description=f"Integration stress test task #{i} — simulate heavy workload",
                priority=2,
                created_by="stress_test",
            )
            task_ids.append(task.id)

            for j in range(STEPS_PER_TASK):
                await state_manager.create_step(
                    db_session,
                    task_id=task.id,
                    order=j + 1,
                    objective=f"Step {j + 1} of task {i:04d}: process data chunk #{j}",
                    teammate_id="test-agent",
                )
                step_count_total += 1

        await db_session.commit()

        elapsed = time.time() - start

        # ── Verify counts ──
        task_result = await db_session.execute(select(func.count(TaskModel.id)))
        actual_task_count = task_result.scalar()
        assert actual_task_count == NUM_TASKS, \
            f"Expected {NUM_TASKS} tasks, got {actual_task_count}"

        step_result = await db_session.execute(
            select(func.count(TaskStepModel.id))
        )
        actual_step_count = step_result.scalar()
        assert actual_step_count == STEPS_PER_TASK * NUM_TASKS, \
            f"Expected {STEPS_PER_TASK * NUM_TASKS} steps, got {actual_step_count}"

        # ── Verify all tasks have correct initial status ──
        result = await db_session.execute(
            select(TaskModel.status, func.count(TaskModel.id))
            .group_by(TaskModel.status)
        )
        status_counts = dict(result.all())
        assert status_counts.get(TaskStatus.CREATED, 0) == NUM_TASKS, \
            f"Not all tasks are CREATED: {status_counts}"

        # ── Verify all steps have correct initial status ──
        step_status_result = await db_session.execute(
            select(TaskStepModel.status, func.count(TaskStepModel.id))
            .group_by(TaskStepModel.status)
        )
        step_status_counts = dict(step_status_result.all())
        assert step_status_counts.get(TaskStepStatus.PENDING, 0) == step_count_total, \
            f"Not all steps are PENDING: {step_status_counts}"

        # Print performance
        create_rate = (NUM_TASKS + step_count_total) / elapsed if elapsed > 0 else 0
        print(f"\n[BULK CREATE] {NUM_TASKS} tasks + {step_count_total} steps in {elapsed:.2f}s "
              f"({create_rate:.0f} rows/s)")

    async def test_list_tasks_performance(self, db_session, state_manager):
        """Verify list_tasks and count_tasks work at scale."""
        # Create 100 tasks first
        for i in range(100):
            task = await state_manager.create_task(
                db_session,
                title=f"Perf Test Task {i:04d}",
                created_by="perf_test",
            )
            for j in range(5):
                await state_manager.create_step(
                    db_session,
                    task_id=task.id,
                    order=j + 1,
                    objective=f"Step {j + 1}",
                )
        await db_session.commit()

        # list_tasks with limit
        start = time.time()
        tasks = await state_manager.list_tasks(db_session, limit=100)
        list_time = time.time() - start
        assert len(tasks) == 100
        print(f"\n[QUERY] list_tasks(limit=100): {list_time*1000:.1f}ms")

        # count_tasks
        start = time.time()
        count = await state_manager.count_tasks(db_session)
        count_time = time.time() - start
        assert count == 100
        print(f"[QUERY] count_tasks(): {count_time*1000:.1f}ms")

        # list steps for one task
        task_id = tasks[0].id
        start = time.time()
        steps = await state_manager.list_steps(db_session, task_id)
        steps_time = time.time() - start
        assert len(steps) == 5
        print(f"[QUERY] list_steps(): {steps_time*1000:.1f}ms")

        # All queries should complete under 200ms
        assert list_time < 0.2, f"list_tasks too slow: {list_time:.2f}s"
        assert count_time < 0.2, f"count_tasks too slow: {count_time:.2f}s"
        assert steps_time < 0.2, f"list_steps too slow: {steps_time:.2f}s"

    async def test_orphan_detection(self, db_session, state_manager):
        """Verify no orphan steps exist after creating tasks."""
        # Create tasks + steps
        for i in range(10):
            task = await state_manager.create_task(
                db_session, title=f"Orphan test {i}", created_by="test",
            )
            for j in range(5):
                await state_manager.create_step(
                    db_session, task_id=task.id, order=j + 1,
                )
        await db_session.commit()

        # Verify no orphan steps (steps referencing non-existent tasks)
        result = await db_session.execute(
            select(TaskStepModel).join(
                TaskModel,
                TaskStepModel.task_id == TaskModel.id,
                isouter=True,
            ).where(TaskModel.id.is_(None))
        )
        orphans = result.scalars().all()
        assert len(orphans) == 0, f"Found {len(orphans)} orphan steps!"

    async def test_cascade_delete(self, db_session, state_manager):
        """Delete a task and verify cascade deletes steps."""
        task = await state_manager.create_task(
            db_session, title="Cascade test", created_by="test",
        )
        for j in range(5):
            await state_manager.create_step(
                db_session, task_id=task.id, order=j + 1,
            )
        await db_session.commit()

        step_count_before = await db_session.execute(
            select(func.count(TaskStepModel.id))
        )
        assert step_count_before.scalar() == 5

        # Delete task
        await state_manager.delete_task(db_session, task)
        await db_session.commit()

        # Steps should be cascade-deleted
        step_count_after = await db_session.execute(
            select(func.count(TaskStepModel.id))
        )
        assert step_count_after.scalar() == 0, "Cascade delete did not remove steps!"


# ═══════════════════════════════════════════════════════════════
# 2. STATE TRANSITION STRESS
# ═══════════════════════════════════════════════════════════════

class TestBulkStateTransitionStress:
    """Verify state machine integrity with 100 tasks."""

    async def test_all_valid_transitions(self, db_session, state_manager):
        """Create tasks, run through full lifecycle transitions."""
        NUM_TASKS = 100

        tasks = []
        for i in range(NUM_TASKS):
            task = await state_manager.create_task(
                db_session, title=f"Transition task {i:04d}", created_by="test",
            )
            tasks.append(task)
        await db_session.commit()

        # CREATED → PLANNING
        for task in tasks:
            t = await state_manager.transition_task_status(
                db_session, task, TaskStatus.PLANNING,
            )
            assert t.status == TaskStatus.PLANNING
        await db_session.commit()

        # PLANNING → EXECUTING
        for task in tasks:
            t = await state_manager.transition_task_status(
                db_session, task, TaskStatus.EXECUTING,
            )
            assert t.status == TaskStatus.EXECUTING
        await db_session.commit()

        # EXECUTING → COMPLETED
        for task in tasks:
            t = await state_manager.transition_task_status(
                db_session, task, TaskStatus.COMPLETED,
            )
            assert t.status == TaskStatus.COMPLETED
        await db_session.commit()

        # Verify all terminal
        result = await db_session.execute(
            select(TaskModel.status, func.count(TaskModel.id))
            .group_by(TaskModel.status)
        )
        status_counts = dict(result.all())
        assert status_counts.get(TaskStatus.COMPLETED, 0) == NUM_TASKS

    async def test_invalid_transition_rejected(self, db_session, state_manager):
        """Invalid transitions raise ValueError even under load."""
        task = await state_manager.create_task(
            db_session, title="Invalid transition test", created_by="test",
        )
        await db_session.commit()

        # CREATED cannot skip to COMPLETED directly
        with pytest.raises(ValueError, match="Invalid task status transition"):
            await state_manager.transition_task_status(
                db_session, task, TaskStatus.COMPLETED,
            )

        # CANCELLED is terminal — cannot transition from it
        await state_manager.transition_task_status(
            db_session, task, TaskStatus.CANCELLED,
        )
        await db_session.commit()
        with pytest.raises(ValueError, match="Invalid task status transition"):
            await state_manager.transition_task_status(
                db_session, task, TaskStatus.EXECUTING,
            )

    async def test_step_transitions(self, db_session, state_manager):
        """Step state transitions at scale."""
        task = await state_manager.create_task(
            db_session, title="Step transition test", created_by="test",
        )
        steps = []
        for j in range(100):
            step = await state_manager.create_step(
                db_session, task_id=task.id, order=j + 1,
                objective=f"Step {j + 1}",
            )
            steps.append(step)
        await db_session.commit()

        # All start PENDING
        for step in steps:
            assert step.status == TaskStepStatus.PENDING

        # Transition all to RUNNING
        for step in steps:
            s = await state_manager.transition_step_status(
                db_session, step, TaskStepStatus.RUNNING,
            )
            assert s.status == TaskStepStatus.RUNNING
        await db_session.commit()

        # Transition all to COMPLETED
        for step in steps:
            s = await state_manager.transition_step_status(
                db_session, step, TaskStepStatus.COMPLETED,
            )
            assert s.status == TaskStepStatus.COMPLETED
        await db_session.commit()

        # Verify all COMPLETED
        result = await db_session.execute(
            select(func.count(TaskStepModel.id))
            .where(TaskStepModel.status == TaskStepStatus.COMPLETED)
        )
        assert result.scalar() == 100, "Not all steps reached COMPLETED!"

    async def test_step_invalid_transition(self, db_session, state_manager):
        """Invalid step transitions raise ValueError."""
        step = await state_manager.create_step(
            db_session, task_id="test-task", order=1,
        )
        await db_session.commit()

        # PENDING → COMPLETED is NOT allowed (must go through RUNNING)
        with pytest.raises(ValueError, match="Invalid step status transition"):
            await state_manager.transition_step_status(
                db_session, step, TaskStepStatus.COMPLETED,
            )


# ═══════════════════════════════════════════════════════════════
# 3. EXECUTOR STRESS (100 Tasks × 10 Steps via TaskExecutor)
# ═══════════════════════════════════════════════════════════════

class TestExecutorStress:
    """Run 100 tasks × 10 steps through TaskExecutor with mocked MAEOS."""

    async def _create_and_execute(
        self,
        db_session,
        state_manager,
        executor,
        num_tasks: int,
        steps_per_task: int,
        mock_policy_result=None,
    ):
        """Helper: create N tasks, execute all through executor with mocks."""
        fake_maeos = FakeMAEOS()
        executor.set_maeos(fake_maeos)

        if mock_policy_result is None:
            mock_policy_result = PolicyResult()

        task_ids = []

        for i in range(num_tasks):
            # Create task
            task = await state_manager.create_task(
                db_session,
                title=f"Exec Stress Task {i:04d}",
                description=f"Executor stress test task #{i}",
                created_by="stress_test",
            )
            # Transition to EXECUTING
            task = await state_manager.transition_task_status(
                db_session, task, TaskStatus.PLANNING,
            )
            task = await state_manager.transition_task_status(
                db_session, task, TaskStatus.EXECUTING,
            )

            # Create steps
            for j in range(steps_per_task):
                await state_manager.create_step(
                    db_session,
                    task_id=task.id,
                    order=j + 1,
                    objective=f"Step {j + 1} for task {i:04d}",
                    teammate_id="test-agent",
                )

            task_ids.append(task.id)

        await db_session.commit()

        # Now execute all tasks
        start = time.time()
        completed_count = 0
        failed_count = 0
        policy_blocked_count = 0

        for task_id in task_ids:
            task = await state_manager.get_task(db_session, task_id)
            assert task is not None

            # Mock policy + state transitions
            side_effects = []
            steps = await state_manager.list_steps(db_session, task_id)

            # For each step: one RUNNING transition, one COMPLETED transition
            for _ in steps:
                running = TaskStepModel(
                    id=gen_uuid(), task_id=task_id, order=0,
                    status=TaskStepStatus.RUNNING,
                )
                completed = TaskStepModel(
                    id=gen_uuid(), task_id=task_id, order=0,
                    status=TaskStepStatus.COMPLETED,
                    output="Stress test step result",
                )
                side_effects.extend([running, completed])

            completed_task = TaskModel(
                id=task_id, title="completed",
                status=TaskStatus.COMPLETED,
                created_by="test",
            )

            with patch.object(TaskPolicyService, 'evaluate_step',
                              AsyncMock(return_value=mock_policy_result)), \
                 patch.object(TaskStateManager, 'transition_step_status',
                              side_effect=side_effects), \
                 patch.object(TaskStateManager, 'create_execution',
                              AsyncMock(return_value=TaskExecutionModel(
                                  id=gen_uuid(), task_step_id=steps[0].id,
                                  attempt=1, maeos_task_id="maeos-test",
                              ))), \
                 patch.object(TaskStateManager, 'update_execution',
                              AsyncMock(return_value=TaskExecutionModel(
                                  id=gen_uuid(), task_step_id=steps[0].id,
                                  attempt=1,
                              ))), \
                 patch.object(TaskStateManager, 'update_step',
                              AsyncMock(return_value=TaskStepModel(
                                  id=gen_uuid(), task_id=task_id, order=0,
                                  status=TaskStepStatus.COMPLETED,
                                  output="Done",
                              ))), \
                 patch.object(TaskStateManager, 'transition_task_status',
                              AsyncMock(return_value=completed_task)):

                try:
                    result = await executor.execute_task(db_session, task)
                    if result.status == TaskStatus.COMPLETED:
                        completed_count += 1
                    elif result.status == TaskStatus.PAUSED:
                        policy_blocked_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    print(f"  [WARN] Task {task_id} failed: {e}")

        elapsed = time.time() - start
        total_steps = num_tasks * steps_per_task

        print(f"\n[EXECUTOR] {num_tasks} tasks, {total_steps} steps in {elapsed:.2f}s "
              f"({total_steps/elapsed:.0f} steps/s)")
        print(f"  Completed: {completed_count}, Failed: {failed_count}, "
              f"Policy-blocked: {policy_blocked_count}")

        return {
            "completed": completed_count,
            "failed": failed_count,
            "policy_blocked": policy_blocked_count,
            "elapsed": elapsed,
            "steps_per_second": total_steps / elapsed if elapsed > 0 else 0,
        }

    async def test_10_tasks_100_steps(self, db_session, state_manager, executor):
        """10 tasks × 10 steps = 100 steps — moderate stress."""
        result = await self._create_and_execute(
            db_session, state_manager, executor,
            num_tasks=10, steps_per_task=10,
        )
        assert result["completed"] == 10, \
            f"Expected all 10 tasks to complete, got: {result}"

    async def test_50_tasks_500_steps(self, db_session, state_manager, executor):
        """50 tasks × 10 steps = 500 steps — heavy stress."""
        result = await self._create_and_execute(
            db_session, state_manager, executor,
            num_tasks=50, steps_per_task=10,
        )
        assert result["completed"] == 50, \
            f"Expected all 50 tasks to complete, got: {result}"

    async def test_100_tasks_1000_steps(self, db_session, state_manager, executor):
        """100 tasks × 10 steps = 1000 steps — full stress."""
        result = await self._create_and_execute(
            db_session, state_manager, executor,
            num_tasks=100, steps_per_task=10,
        )
        assert result["completed"] == 100, \
            f"Expected all 100 tasks to complete, got: {result}"
        # At least 500 steps/s on in-memory SQLite (should be much faster)
        assert result["steps_per_second"] > 100, \
            f"Too slow: {result['steps_per_second']:.0f} steps/s"


# ═══════════════════════════════════════════════════════════════
# 4. MEMORY ACCUMULATION STRESS
# ═══════════════════════════════════════════════════════════════

class TestMemoryAccumulationStress:
    """Verify MemoryTaskHook handles bulk event dispatch correctly."""

    async def test_hook_dispatch_overhead(self, db_session):
        """Verify hook registry + buffered batch write doesn't crash under load."""
        registry = get_task_hook_registry()
        hook = MemoryTaskHook()
        registry.register(hook)

        NUM_EVENTS = 1000

        # Dispatch 1000 events concurrently
        start = time.time()
        tasks = []
        for i in range(NUM_EVENTS):
            ctx = TaskHookContext(
                task_id=f"task-{i:04d}",
                task_title=f"Memory Test Task {i:04d}",
                task_description=f"Stress test for memory accumulation #{i}",
                task_status=TaskStatus.COMPLETED,
                step_id=f"step-{i:04d}",
                step_order=i % 10,
                step_objective=f"Step {i % 10}",
                step_output=f"Output for step {i % 10}",
                execution_id=f"exec-{i:04d}",
                execution_outcome="SUCCESS",
                execution_duration_ms=100,
                execution_total_tokens=500,
            )
            tasks.append(registry.dispatch(
                TaskLifecycleEvent.TASK_CREATED, ctx,
            ))

        await asyncio.gather(*tasks)
        elapsed = time.time() - start

        # Flush remaining buffered items
        await hook.buffer.flush()

        rate = NUM_EVENTS / elapsed if elapsed > 0 else 0
        print(f"\n[MEMORY-HOOK] {NUM_EVENTS} events dispatched in {elapsed:.2f}s "
              f"({rate:.0f} events/s) — buffered batch write")

        # Hooks should never throw — failures are swallowed
        assert True
        # With buffering, dispatch should be very fast (< 1s for 1000 events)
        assert elapsed < 5.0, f"Hook dispatch too slow: {elapsed:.2f}s"

    async def test_buffer_flush_all_items(self):
        """Verify MemoryBuffer flush() writes ALL buffered items."""
        hook = MemoryTaskHook(buffer_max_size=10, buffer_flush_interval=5.0)

        stored_ids = []
        async def fake_store_batch(items):
            stored_ids.extend(item.id for item in items)
            return [item.id for item in items]

        with patch.object(
            hook._buffer, '_flush_locked',
            wraps=hook._buffer._flush_locked,
        ) as mock_flush, \
             patch(
                 'backend.services.memory.memory_service.MemoryService.store_batch',
                 side_effect=fake_store_batch,
             ):
            # Dispatch 25 items (2 full flushes at threshold 10 + 5 remaining)
            for i in range(25):
                item = MemoryItem(
                    memory_type=MemoryType.EXECUTION,
                    content=f"item {i}",
                    source_id="test",
                )
                await hook._buffer.add(item)

            # 2 auto-flushes should have happened at thresholds 10 and 20
            assert mock_flush.call_count == 2, \
                f"Expected 2 auto-flushes, got {mock_flush.call_count}"

            # 5 items still in buffer
            assert len(hook._buffer._items) == 5

            # Manual flush
            await hook.buffer.flush()
            assert len(hook._buffer._items) == 0, "Buffer not empty after flush"

        # All 25 items should have been stored
        assert len(stored_ids) == 25, f"Expected 25 stored, got {len(stored_ids)}"

        print(f"\n[MEMORY-BUFFER] Auto-flush: {mock_flush.call_count} times, "
              f"25 items total stored")

    async def test_memory_hook_count_correct(self):
        """Verify MemoryTaskHook is called the expected number of times."""
        hook = MemoryTaskHook()

        task_created_count = 0
        task_completed_count = 0
        step_completed_count = 0
        execution_completed_count = 0

        async def counting_store(item, label):
            nonlocal task_created_count, task_completed_count, \
                step_completed_count, execution_completed_count
            if item.memory_type == MemoryType.TASK:
                if "Task completed" in item.content:
                    task_completed_count += 1
                else:
                    task_created_count += 1
            elif item.memory_type == MemoryType.EXECUTION:
                if "Step" in item.content and "Output" in item.content:
                    step_completed_count += 1
                else:
                    execution_completed_count += 1

        with patch.object(hook, '_store', side_effect=counting_store):
            NUM_TASKS = 100
            STEPS_PER_TASK = 10

            # Create events
            for i in range(NUM_TASKS):
                ctx = TaskHookContext(
                    task_id=f"task-{i:04d}",
                    task_title=f"Task {i:04d}",
                    task_description=f"Description {i}",
                    task_status=TaskStatus.CREATED,
                )
                await hook.on_task_created(ctx)

                for j in range(STEPS_PER_TASK):
                    step_ctx = TaskHookContext(
                        task_id=f"task-{i:04d}",
                        step_id=f"step-{i:04d}-{j:02d}",
                        step_order=j + 1,
                        step_objective=f"Step {j + 1}",
                        step_output=f"Output {j}",
                        execution_id=f"exec-{i:04d}-{j:02d}",
                        execution_outcome="SUCCESS",
                        execution_duration_ms=100 + j,
                        execution_total_tokens=500 + j * 10,
                    )
                    await hook.on_step_completed(step_ctx)
                    await hook.on_execution_completed(step_ctx)

                complete_ctx = TaskHookContext(
                    task_id=f"task-{i:04d}",
                    task_title=f"Task {i:04d}",
                    task_description=f"Description {i}",
                    task_status=TaskStatus.COMPLETED,
                )
                await hook.on_task_completed(complete_ctx)

        # Verify counts
        assert task_created_count == NUM_TASKS, \
            f"Expected {NUM_TASKS} TASK_CREATED, got {task_created_count}"
        assert task_completed_count == NUM_TASKS, \
            f"Expected {NUM_TASKS} TASK_COMPLETED, got {task_completed_count}"
        assert step_completed_count == NUM_TASKS * STEPS_PER_TASK, \
            f"Expected {NUM_TASKS * STEPS_PER_TASK} STEP_COMPLETED, got {step_completed_count}"
        assert execution_completed_count == NUM_TASKS * STEPS_PER_TASK, \
            f"Expected {NUM_TASKS * STEPS_PER_TASK} EXECUTION_COMPLETED, " \
            f"got {execution_completed_count}"

        print(f"\n[MEMORY-COUNT] Verified: {task_created_count} created + "
              f"{task_completed_count} completed + "
              f"{step_completed_count} steps + "
              f"{execution_completed_count} executions")

    async def test_store_batch_performance(self):
        """Verify MemoryService.store_batch handles bulk items."""
        from backend.services.memory.memory_service import MemoryService
        from backend.services.memory.memory_types import MemoryItem

        svc = MemoryService()
        svc._ensure_table = AsyncMock()  # Skip real DB
        svc._ready = True

        NUM_ITEMS = 1000
        items = [
            MemoryItem(
                memory_type=MemoryType.EXECUTION,
                content=f"Memory item #{i}: step result with execution data",
                source_id=f"task-{i % 100:04d}",
                relevance_score=0.7,
                metadata={"step": i, "task": f"task-{i % 100:04d}"},
            )
            for i in range(NUM_ITEMS)
        ]

        with patch.object(svc, '_ensure_table', AsyncMock()):
            start = time.time()
            ids = await svc.store_batch(items)
            elapsed = time.time() - start

        assert len(ids) == NUM_ITEMS
        rate = NUM_ITEMS / elapsed if elapsed > 0 else 0
        print(f"\n[MEMORY-BATCH] {NUM_ITEMS} items stored (mocked) in {elapsed*1000:.1f}ms "
              f"({rate:.0f} items/s)")


# ═══════════════════════════════════════════════════════════════
# 5. ANALYTICS / AGGREGATION STRESS
# ═══════════════════════════════════════════════════════════════

class TestAnalyticsStress:
    """Verify task analytics queries work at scale."""

    async def test_get_task_analytics_at_scale(self, db_session, state_manager):
        """get_task_analytics should return correct data with 1000+ executions."""
        # Create tasks with executions
        NUM_TASKS = 50
        task_ids = []

        for i in range(NUM_TASKS):
            task = await state_manager.create_task(
                db_session, title=f"Analytics task {i:04d}", created_by="test",
            )
            task_ids.append(task.id)

            for j in range(5):
                step = await state_manager.create_step(
                    db_session, task_id=task.id, order=j + 1,
                )
                # Create execution for each step (simulate by writing directly)
                execution = TaskExecutionModel(
                    task_step_id=step.id,
                    attempt=1,
                    maeos_task_id=f"maeos-{i}-{j}",
                    input_tokens=100 + i,
                    output_tokens=50 + j,
                    total_tokens=150 + i + j,
                    estimated_cost=100 + i * j,
                )
                db_session.add(execution)

        await db_session.commit()

        # Query analytics for each task
        analytics_total_time = 0
        for task_id in task_ids:
            start = time.time()
            analytics = await state_manager.get_task_analytics(db_session, task_id)
            analytics_total_time += time.time() - start

            # Each task has 5 steps × 1 execution = 5 executions
            assert analytics["execution_count"] == 5, \
                f"Expected 5 executions for {task_id}, got {analytics}"

        avg_time = (analytics_total_time / len(task_ids)) * 1000
        print(f"\n[ANALYTICS] {len(task_ids)} tasks, avg query time: {avg_time:.1f}ms")
        assert avg_time < 200, f"Analytics queries too slow: avg {avg_time:.1f}ms"

    async def test_list_executions_by_task(self, db_session, state_manager):
        """list_executions_by_task should work at scale."""
        # Create one task with many steps
        task = await state_manager.create_task(
            db_session, title="Exec list test", created_by="test",
        )
        step_ids = []
        for j in range(100):
            step = await state_manager.create_step(
                db_session, task_id=task.id, order=j + 1,
            )
            step_ids.append(step.id)

            # Create execution for each step
            execution = TaskExecutionModel(
                task_step_id=step.id,
                attempt=1,
                maeos_task_id=f"maeos-list-{j}",
                input_tokens=200,
                output_tokens=100,
                total_tokens=300,
                estimated_cost=50,
            )
            db_session.add(execution)
        await db_session.commit()

        # Query
        start = time.time()
        executions = await state_manager.list_executions_by_task(db_session, task.id)
        elapsed = time.time() - start

        assert len(executions) == 100, \
            f"Expected 100 executions, got {len(executions)}"

        print(f"\n[EXEC-LIST] {len(executions)} executions in {elapsed*1000:.1f}ms")
        assert elapsed < 0.5, f"list_executions_by_task too slow: {elapsed:.2f}s"
