"""
test_tasks.py — Task Core (Phase A) Tests

Covers:
  1. Task CRUD: create, read, update, delete
  2. Task status transitions (state machine validation)
  3. Task lifecycle: plan → execute → pause → resume → complete
  4. Task listing with filters
  5. Step CRUD (basic)
  6. Execution CRUD (basic)
  7. Transition validation (invalid transitions rejected)
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskExecutionModel,
    TaskStatus,
    TaskStepStatus,
)
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_manager import TaskManager


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def state_mgr():
    return TaskStateManager()


@pytest.fixture
def task_mgr():
    return TaskManager()


@pytest.fixture
def _unique_title():
    """Generate a unique task title per test."""
    return f"test-task-{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════
# 1. TaskStatus State Machine
# ═══════════════════════════════════════════════════════════════


class TestTaskStatus:
    def test_valid_transitions(self):
        """Verify all allowed transitions."""
        assert TaskStatus.can_transition(TaskStatus.CREATED, TaskStatus.PLANNING)
        assert TaskStatus.can_transition(TaskStatus.CREATED, TaskStatus.CANCELLED)
        assert TaskStatus.can_transition(TaskStatus.PLANNING, TaskStatus.EXECUTING)
        assert TaskStatus.can_transition(TaskStatus.PLANNING, TaskStatus.FAILED)
        assert TaskStatus.can_transition(TaskStatus.PLANNING, TaskStatus.CANCELLED)
        assert TaskStatus.can_transition(TaskStatus.EXECUTING, TaskStatus.COMPLETED)
        assert TaskStatus.can_transition(TaskStatus.EXECUTING, TaskStatus.FAILED)
        assert TaskStatus.can_transition(TaskStatus.EXECUTING, TaskStatus.PAUSED)
        assert TaskStatus.can_transition(TaskStatus.EXECUTING, TaskStatus.CANCELLED)
        assert TaskStatus.can_transition(TaskStatus.PAUSED, TaskStatus.EXECUTING)
        assert TaskStatus.can_transition(TaskStatus.PAUSED, TaskStatus.CANCELLED)
        assert TaskStatus.can_transition(TaskStatus.FAILED, TaskStatus.PLANNING)

    def test_invalid_transitions(self):
        """Verify invalid transitions are rejected."""
        # Terminal states
        assert not TaskStatus.can_transition(TaskStatus.COMPLETED, TaskStatus.PLANNING)
        assert not TaskStatus.can_transition(TaskStatus.CANCELLED, TaskStatus.PLANNING)

        # Wrong direction
        assert not TaskStatus.can_transition(TaskStatus.PLANNING, TaskStatus.CREATED)
        assert not TaskStatus.can_transition(TaskStatus.EXECUTING, TaskStatus.PLANNING)

        # Skip states (now allowed: CREATED→EXECUTING for v1 direct execution)
        assert TaskStatus.can_transition(TaskStatus.CREATED, TaskStatus.EXECUTING)
        assert not TaskStatus.can_transition(TaskStatus.CREATED, TaskStatus.COMPLETED)
        assert not TaskStatus.can_transition(TaskStatus.PLANNING, TaskStatus.COMPLETED)


class TestTaskStepStatus:
    def test_valid_transitions(self):
        assert TaskStepStatus.can_transition(TaskStepStatus.PENDING, TaskStepStatus.SCHEDULED)
        assert TaskStepStatus.can_transition(TaskStepStatus.PENDING, TaskStepStatus.SKIPPED)
        assert TaskStepStatus.can_transition(TaskStepStatus.SCHEDULED, TaskStepStatus.RUNNING)
        assert TaskStepStatus.can_transition(TaskStepStatus.RUNNING, TaskStepStatus.COMPLETED)
        assert TaskStepStatus.can_transition(TaskStepStatus.RUNNING, TaskStepStatus.FAILED)
        assert TaskStepStatus.can_transition(TaskStepStatus.FAILED, TaskStepStatus.PENDING)

    def test_invalid_transitions(self):
        assert not TaskStepStatus.can_transition(TaskStepStatus.COMPLETED, TaskStepStatus.RUNNING)
        assert not TaskStepStatus.can_transition(TaskStepStatus.SKIPPED, TaskStepStatus.PENDING)
        # PENDING→RUNNING and PENDING→FAILED now allowed for v1 direct execution
        assert TaskStepStatus.can_transition(TaskStepStatus.PENDING, TaskStepStatus.RUNNING)
        assert TaskStepStatus.can_transition(TaskStepStatus.PENDING, TaskStepStatus.FAILED)


# ═══════════════════════════════════════════════════════════════
# 2. TaskStateManager — Task CRUD
# ═══════════════════════════════════════════════════════════════


class TestTaskStateManagerTaskCRUD:
    """Task CRUD operations (async — requires db_session)."""
    pytestmark = pytest.mark.asyncio
    async def test_create_task(self, db_session, state_mgr, _unique_title):
        """Create a task and verify defaults."""
        task = await state_mgr.create_task(
            db_session,
            title=_unique_title,
            description="integration test task",
            channel_id="ch_test",
            created_by="test",
        )
        assert task.id is not None
        assert task.title == _unique_title
        assert task.status == TaskStatus.CREATED
        assert task.channel_id == "ch_test"
        assert task.priority == 2

    async def test_get_task(self, db_session, state_mgr, _unique_title):
        """Create then retrieve a task by ID."""
        created = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        loaded = await state_mgr.get_task(db_session, created.id)
        assert loaded is not None
        assert loaded.id == created.id
        assert loaded.title == _unique_title

    async def test_get_task_not_found(self, db_session, state_mgr):
        """Getting a nonexistent task returns None."""
        result = await state_mgr.get_task(db_session, "nonexistent-id")
        assert result is None

    async def test_list_tasks(self, db_session, state_mgr):
        """List all tasks, ordered by created_at desc."""
        # Create two tasks
        await state_mgr.create_task(db_session, title="task-a", created_by="test")
        await state_mgr.create_task(db_session, title="task-b", created_by="test")
        tasks = await state_mgr.list_tasks(db_session)
        assert len(tasks) >= 2
        # Most recently created first
        assert tasks[0].title == "task-b"

    async def test_list_tasks_filter_by_status(self, db_session, state_mgr):
        """Filter tasks by status."""
        t1 = await state_mgr.create_task(db_session, title="filter-a", created_by="test")
        await state_mgr.create_task(db_session, title="filter-b", created_by="test")
        await state_mgr.transition_task_status(db_session, t1, TaskStatus.PLANNING)
        planning_tasks = await state_mgr.list_tasks(db_session, status=TaskStatus.PLANNING)
        assert len(planning_tasks) >= 1
        assert all(t.status == TaskStatus.PLANNING for t in planning_tasks)

    async def test_list_tasks_filter_by_channel(self, db_session, state_mgr):
        """Filter tasks by channel_id."""
        await state_mgr.create_task(db_session, title="ch-a", channel_id="ch1", created_by="test")
        await state_mgr.create_task(db_session, title="ch-b", channel_id="ch2", created_by="test")
        ch1_tasks = await state_mgr.list_tasks(db_session, channel_id="ch1")
        assert len(ch1_tasks) >= 1
        assert all(t.channel_id == "ch1" for t in ch1_tasks)

    async def test_count_tasks(self, db_session, state_mgr):
        """Count tasks with optional filters."""
        await state_mgr.create_task(db_session, title="count-a", channel_id="cnt", created_by="test")
        await state_mgr.create_task(db_session, title="count-b", channel_id="cnt", created_by="test")
        total = await state_mgr.count_tasks(db_session)
        cnt_total = await state_mgr.count_tasks(db_session, channel_id="cnt")
        assert cnt_total >= 2
        assert total >= cnt_total

    async def test_update_task(self, db_session, state_mgr, _unique_title):
        """Update task title and priority."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await state_mgr.update_task(db_session, task, title="updated-title", priority=1)
        loaded = await state_mgr.get_task(db_session, task.id)
        assert loaded.title == "updated-title"
        assert loaded.priority == 1

    async def test_delete_task(self, db_session, state_mgr, _unique_title):
        """Delete a task and verify it's gone."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        task_id = task.id
        await state_mgr.delete_task(db_session, task)
        loaded = await state_mgr.get_task(db_session, task_id)
        assert loaded is None


# ═══════════════════════════════════════════════════════════════
# 3. TaskStateManager — Status Transitions
# ═══════════════════════════════════════════════════════════════


class TestTaskStatusTransitions:
    """Task status transitions (async — requires db_session)."""
    pytestmark = pytest.mark.asyncio
    async def test_full_lifecycle(self, db_session, state_mgr, _unique_title):
        """Test the happy path: CREATED → PLANNING → EXECUTING → COMPLETED."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")

        await state_mgr.transition_task_status(db_session, task, TaskStatus.PLANNING)
        assert task.status == TaskStatus.PLANNING

        await state_mgr.transition_task_status(db_session, task, TaskStatus.EXECUTING)
        assert task.status == TaskStatus.EXECUTING

        await state_mgr.transition_task_status(db_session, task, TaskStatus.COMPLETED)
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None

    async def test_pause_resume(self, db_session, state_mgr, _unique_title):
        """Test pause/resume cycle."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await state_mgr.transition_task_status(db_session, task, TaskStatus.PLANNING)
        await state_mgr.transition_task_status(db_session, task, TaskStatus.EXECUTING)

        await state_mgr.transition_task_status(db_session, task, TaskStatus.PAUSED)
        assert task.status == TaskStatus.PAUSED

        await state_mgr.transition_task_status(db_session, task, TaskStatus.EXECUTING)
        assert task.status == TaskStatus.EXECUTING

    async def test_cancel_from_created(self, db_session, state_mgr, _unique_title):
        """Cancel a newly created task."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await state_mgr.transition_task_status(db_session, task, TaskStatus.CANCELLED)
        assert task.status == TaskStatus.CANCELLED

    async def test_cancel_from_executing(self, db_session, state_mgr, _unique_title):
        """Cancel a running task."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await state_mgr.transition_task_status(db_session, task, TaskStatus.PLANNING)
        await state_mgr.transition_task_status(db_session, task, TaskStatus.EXECUTING)
        await state_mgr.transition_task_status(db_session, task, TaskStatus.CANCELLED)
        assert task.status == TaskStatus.CANCELLED

    async def test_fail_then_replan(self, db_session, state_mgr, _unique_title):
        """Fail then re-plan (FAILED → PLANNING)."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await state_mgr.transition_task_status(db_session, task, TaskStatus.PLANNING)
        await state_mgr.transition_task_status(db_session, task, TaskStatus.EXECUTING)
        await state_mgr.transition_task_status(db_session, task, TaskStatus.FAILED)
        assert task.status == TaskStatus.FAILED

        # Re-plan from failure
        await state_mgr.transition_task_status(db_session, task, TaskStatus.PLANNING)
        assert task.status == TaskStatus.PLANNING

    async def test_invalid_transition_raises(self, db_session, state_mgr, _unique_title):
        """Invalid transition raises ValueError."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        with pytest.raises(ValueError, match="Invalid task status transition"):
            await state_mgr.transition_task_status(db_session, task, TaskStatus.COMPLETED)

    async def test_noop_transition(self, db_session, state_mgr, _unique_title):
        """Same-status transition is a no-op."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        result = await state_mgr.transition_task_status(db_session, task, TaskStatus.CREATED)
        assert result.status == TaskStatus.CREATED

    async def test_terminal_states_reject_all(self, db_session, state_mgr, _unique_title):
        """Terminal states (COMPLETED, CANCELLED) reject any transition."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await state_mgr.transition_task_status(db_session, task, TaskStatus.PLANNING)
        await state_mgr.transition_task_status(db_session, task, TaskStatus.EXECUTING)
        await state_mgr.transition_task_status(db_session, task, TaskStatus.COMPLETED)

        with pytest.raises(ValueError):
            await state_mgr.transition_task_status(db_session, task, TaskStatus.PLANNING)


# ═══════════════════════════════════════════════════════════════
# 4. TaskStateManager — Step CRUD
# ═══════════════════════════════════════════════════════════════


class TestTaskStepCRUD:
    """Step CRUD (async — requires db_session)."""
    pytestmark = pytest.mark.asyncio
    async def test_create_step(self, db_session, state_mgr, _unique_title):
        """Create a step under a task."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(
            db_session,
            task_id=task.id,
            order=1,
            objective="analyze requirements",
            teammate_id="teammate_a",
        )
        assert step.id is not None
        assert step.task_id == task.id
        assert step.order == 1
        assert step.objective == "analyze requirements"
        assert step.teammate_id == "teammate_a"
        assert step.status == TaskStepStatus.PENDING

    async def test_list_steps(self, db_session, state_mgr, _unique_title):
        """List steps for a task in order."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step-1")
        await state_mgr.create_step(db_session, task_id=task.id, order=2, objective="step-2")
        steps = await state_mgr.list_steps(db_session, task.id)
        assert len(steps) == 2
        assert steps[0].order == 1
        assert steps[1].order == 2

    async def test_step_status_transition(self, db_session, state_mgr, _unique_title):
        """Step status transitions: PENDING → SCHEDULED → RUNNING → COMPLETED."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")

        await state_mgr.transition_step_status(db_session, step, TaskStepStatus.SCHEDULED)
        assert step.status == TaskStepStatus.SCHEDULED

        await state_mgr.transition_step_status(db_session, step, TaskStepStatus.RUNNING)
        assert step.status == TaskStepStatus.RUNNING
        assert step.started_at is not None

        await state_mgr.transition_step_status(db_session, step, TaskStepStatus.COMPLETED)
        assert step.status == TaskStepStatus.COMPLETED
        assert step.completed_at is not None

    async def test_step_retry_cycle(self, db_session, state_mgr, _unique_title):
        """Step failure → retry: RUNNING → FAILED → PENDING."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")

        await state_mgr.transition_step_status(db_session, step, TaskStepStatus.SCHEDULED)
        await state_mgr.transition_step_status(db_session, step, TaskStepStatus.RUNNING)
        await state_mgr.transition_step_status(db_session, step, TaskStepStatus.FAILED)
        assert step.status == TaskStepStatus.FAILED

        # Retry: FAILED → PENDING
        await state_mgr.transition_step_status(db_session, step, TaskStepStatus.PENDING)
        assert step.status == TaskStepStatus.PENDING

    async def test_invalid_step_transition_raises(self, db_session, state_mgr, _unique_title):
        """Invalid step transition raises ValueError."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")

        with pytest.raises(ValueError, match="Invalid step status transition"):
            await state_mgr.transition_step_status(db_session, step, TaskStepStatus.COMPLETED)

    async def test_step_cascade_on_task_delete(self, db_session, state_mgr, _unique_title):
        """Deleting a task cascades to its steps."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")
        step_id = step.id

        await state_mgr.delete_task(db_session, task)
        loaded = await state_mgr.get_step(db_session, step_id)
        assert loaded is None


# ═══════════════════════════════════════════════════════════════
# 5. TaskStateManager — Execution CRUD
# ═══════════════════════════════════════════════════════════════


class TestTaskExecutionCRUD:
    """Execution CRUD (async — requires db_session)."""
    pytestmark = pytest.mark.asyncio
    async def test_create_execution(self, db_session, state_mgr, _unique_title):
        """Create an execution record for a step."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")

        execution = await state_mgr.create_execution(
            db_session,
            task_step_id=step.id,
            attempt=1,
            maeos_task_id="maeos_abc123",
            trace_id="trace_xyz456",
        )
        assert execution.id is not None
        assert execution.task_step_id == step.id
        assert execution.attempt == 1
        assert execution.maeos_task_id == "maeos_abc123"
        assert execution.trace_id == "trace_xyz456"

    async def test_list_executions(self, db_session, state_mgr, _unique_title):
        """List executions for a step in attempt order."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")

        await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)
        await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=2)
        executions = await state_mgr.list_executions(db_session, step.id)
        assert len(executions) == 2
        assert executions[0].attempt == 1
        assert executions[1].attempt == 2

    async def test_update_execution(self, db_session, state_mgr, _unique_title):
        """Update execution metrics."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")
        execution = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)

        await state_mgr.update_execution(
            db_session, execution,
            execution_time_ms=1500,
            token_usage=500,
            cost=10,
            output_snapshot="result data",
        )
        assert execution.execution_time_ms == 1500
        assert execution.token_usage == 500
        assert execution.cost == 10

    async def test_execution_cascade_on_step_delete(self, db_session, state_mgr, _unique_title):
        """Deleting a step (via task cascade) removes executions too."""
        task = await state_mgr.create_task(db_session, title=_unique_title, created_by="test")
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step")
        execution = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)
        exec_id = execution.id

        await state_mgr.delete_task(db_session, task)
        loaded = await state_mgr.get_step(db_session, step.id)
        assert loaded is None
        # Verify we can't load the execution (step is gone, cascade removed it)


# ═══════════════════════════════════════════════════════════════
# 6. TaskManager — High-Level Lifecycle
# ═══════════════════════════════════════════════════════════════


class TestTaskManagerLifecycle:
    """TaskManager lifecycle (async — requires db_session)."""
    pytestmark = pytest.mark.asyncio
    async def test_create_and_get(self, db_session, task_mgr, _unique_title):
        """TaskManager.create_task returns a valid task."""
        task = await task_mgr.create_task(
            db_session,
            title=_unique_title,
            created_by="test",
        )
        assert task.id is not None
        assert task.status == TaskStatus.CREATED

        loaded = await task_mgr.get_task(db_session, task.id)
        assert loaded is not None

    async def test_create_and_delete(self, db_session, task_mgr, _unique_title):
        """TaskManager.create + delete."""
        task = await task_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await task_mgr.delete_task(db_session, task.id)
        loaded = await task_mgr.get_task(db_session, task.id)
        assert loaded is None

    async def test_update_task_metadata(self, db_session, task_mgr, _unique_title):
        """TaskManager.update_task changes metadata."""
        task = await task_mgr.create_task(db_session, title=_unique_title, created_by="test")
        await task_mgr.update_task(db_session, task.id, title="new-title", priority=0)
        loaded = await task_mgr.get_task(db_session, task.id)
        assert loaded.title == "new-title"
        assert loaded.priority == 0

    async def test_update_task_rejects_status(self, db_session, task_mgr, _unique_title):
        """TaskManager.update_task rejects 'status' kwarg."""
        task = await task_mgr.create_task(db_session, title=_unique_title, created_by="test")
        with pytest.raises(ValueError, match="Use transition_task_status"):
            await task_mgr.update_task(db_session, task.id, status="COMPLETED")

    async def test_delete_nonexistent_raises(self, db_session, task_mgr):
        """Deleting a nonexistent task raises ValueError."""
        with pytest.raises(ValueError, match="Task not found"):
            await task_mgr.delete_task(db_session, "nonexistent")

    async def test_full_lifecycle_via_task_manager(self, db_session, task_mgr, _unique_title):
        """End-to-end lifecycle via TaskManager convenience methods."""
        task = await task_mgr.create_task(db_session, title=_unique_title, created_by="test")
        assert task.status == TaskStatus.CREATED

        task = await task_mgr.start_planning(db_session, task.id)
        assert task.status == TaskStatus.PLANNING

        task = await task_mgr.start_execution(db_session, task.id)
        assert task.status == TaskStatus.EXECUTING

        task = await task_mgr.pause(db_session, task.id)
        assert task.status == TaskStatus.PAUSED

        task = await task_mgr.resume(db_session, task.id)
        assert task.status == TaskStatus.EXECUTING

        task = await task_mgr.complete(db_session, task.id)
        assert task.status == TaskStatus.COMPLETED

    async def test_cancel_via_task_manager(self, db_session, task_mgr, _unique_title):
        """TaskManager.cancel works from CREATED."""
        task = await task_mgr.create_task(db_session, title=_unique_title, created_by="test")
        task = await task_mgr.cancel(db_session, task.id)
        assert task.status == TaskStatus.CANCELLED

    async def test_fail_via_task_manager(self, db_session, task_mgr, _unique_title):
        """TaskManager.fail sets FAILED."""
        task = await task_mgr.create_task(db_session, title=_unique_title, created_by="test")
        task = await task_mgr.start_planning(db_session, task.id)
        task = await task_mgr.start_execution(db_session, task.id)
        task = await task_mgr.fail(db_session, task.id)
        assert task.status == TaskStatus.FAILED

    async def test_list_with_pagination(self, db_session, task_mgr):
        """TaskManager.list_tasks with limit/offset."""
        for i in range(5):
            await task_mgr.create_task(db_session, title=f"page-{i}", created_by="test")

        page1 = await task_mgr.list_tasks(db_session, limit=2, offset=0)
        assert len(page1) <= 2

        page2 = await task_mgr.list_tasks(db_session, limit=2, offset=2)
        assert len(page2) <= 2
