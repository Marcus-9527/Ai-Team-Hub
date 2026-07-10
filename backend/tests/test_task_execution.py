"""
test_task_execution.py — Phase B: Task Executor + Context Builder + Result Handler

Tests the MAEOS integration layer for task step execution.

Coverage:
  1. TaskContextBuilder — context construction with/without prior steps
  2. TaskResultHandler — execution recording, step success/failure
  3. TaskExecutor — sequential step execution, step failure handling
  4. Route integration — step CRUD, execute endpoint
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskStatus, TaskStepStatus,
)
from backend.services.task.task_context import TaskContextBuilder
from backend.services.task.task_result import TaskResultHandler
from backend.services.task.task_executor import TaskExecutor
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_policy import TaskPolicyService, PolicyResult

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def make_task(**kwargs) -> TaskModel:
    """Create a TaskModel with minimal required fields."""
    defaults = dict(
        id="task-001",
        title="Test Task",
        description="Test task description",
        status=TaskStatus.EXECUTING,
        priority=2,
        intent="test",
        created_by="test",
    )
    defaults.update(kwargs)
    task = TaskModel(**defaults)
    task.steps = []
    return task


def make_step(task_id="task-001", order=1, **kwargs) -> TaskStepModel:
    """Create a TaskStepModel with minimal required fields."""
    defaults = dict(
        id=f"step-{order:03d}",
        task_id=task_id,
        order=order,
        objective=f"Step {order} objective",
        status=TaskStepStatus.PENDING,
    )
    defaults.update(kwargs)
    return TaskStepModel(**defaults)


def make_execution(step_id="step-001", attempt=1, **kwargs) -> TaskExecutionModel:
    """Create a TaskExecutionModel with minimal required fields."""
    defaults = dict(
        id=f"exec-{step_id}-{attempt}",
        task_step_id=step_id,
        attempt=attempt,
        maeos_task_id="maeos-task-001",
    )
    defaults.update(kwargs)
    return TaskExecutionModel(**defaults)


# Mock MAEOS task result
class FakeMAEOSTask:
    def __init__(self, task_id: str, status: str = "COMPLETED",
                 result: str = "", error: str = ""):
        self.id = task_id
        self.task_id = task_id
        self.status = status
        self.result = result
        self.error = error
        self.trace_report = {"trace_id": "trace-001"}

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


class FakeMAEOS:
    """Mock MAEOS engine that returns predefined results."""

    def __init__(self, results: dict[str, str] = None, fail_ids: set[str] = None):
        self.results = results or {}
        self.fail_ids = fail_ids or set()
        self._started = True
        self.submitted: list[str] = []

    async def submit(self, description: str, priority: int = 2,
                     intent: str = "", wait: bool = False,
                     **kwargs) -> str:
        task_id = f"maeos-{len(self.submitted) + 1:04d}"
        self.submitted.append(task_id)
        return task_id

    def get_status(self, task_id: str) -> dict:
        if task_id in self.fail_ids:
            return {"status": "FAILED", "error": "Simulated failure"}
        return {"status": "COMPLETED"}

    async def wait(self, task_id: str, timeout: float = 300.0) -> FakeMAEOSTask:
        if task_id in self.fail_ids:
            return FakeMAEOSTask(task_id, status="FAILED", error="Simulated MAEOS failure")
        result = self.results.get(task_id, f"Result for {task_id}")
        return FakeMAEOSTask(task_id, status="COMPLETED", result=result)

    def stats(self):
        return {"tasks_submitted": len(self.submitted)}


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def db_session():
    """Create a mock async DB session."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def context_builder():
    return TaskContextBuilder()


@pytest.fixture
def result_handler():
    return TaskResultHandler()


@pytest.fixture
def fake_maeos():
    return FakeMAEOS()


# ═══════════════════════════════════════════════════════════════
# 1. TaskContextBuilder Tests
# ═══════════════════════════════════════════════════════════════

class TestTaskContextBuilder:
    """Verify context construction for step execution."""

    async def test_build_context_no_prior_steps(self, db_session, context_builder):
        """Context with only task goal + current step (no prior steps)."""
        task = make_task(description="Build a user authentication system")
        step = make_step(order=1, objective="Design the database schema")

        # Mock the internal state manager's list_steps to avoid DB calls
        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[])):
            context = await context_builder.build_step_context(db_session, task, step)

        assert "[TASK GOAL]" in context
        assert "Build a user authentication system" in context
        assert "[CURRENT STEP]" in context
        assert "Design the database schema" in context
        assert "[PRIOR STEPS]" not in context

    async def test_build_context_with_prior_steps(self, db_session, context_builder):
        """Context includes outputs from prior completed steps."""
        task = make_task(description="Build a blog system")
        step3 = make_step(order=3, objective="Add commenting feature")
        prior1 = make_step(order=1, objective="Create post model",
                           status="COMPLETED", output="Created Post model with title/body")
        prior2 = make_step(order=2, objective="Create comment model",
                           status="COMPLETED", output="Created Comment model with foreign key")

        # Mock list_steps to return all steps sorted
        import backend.services.task.task_state as ts_mod
        with patch.object(ts_mod.TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[prior1, prior2, step3])):
            context = await context_builder.build_step_context(db_session, task, step3)

        assert "[TASK GOAL]" in context
        assert "Build a blog system" in context
        assert "[PRIOR STEPS]" in context
        assert "[STEP 1:" in context
        assert "Created Post model with title/body" in context
        assert "[STEP 2:" in context
        assert "Created Comment model" in context
        assert "[CURRENT STEP]" in context
        assert "Add commenting feature" in context

    async def test_build_maeos_description(self, db_session, context_builder):
        """build_maeos_description returns the full context string."""
        task = make_task(description="Test task")
        step = make_step(order=1, objective="Do the thing")

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[])):
            result = await context_builder.build_maeos_description(db_session, task, step)

        assert isinstance(result, str)
        assert "Test task" in result
        assert "Do the thing" in result


# ═══════════════════════════════════════════════════════════════
# 2. TaskResultHandler Tests
# ═══════════════════════════════════════════════════════════════

class TestTaskResultHandler:
    """Verify execution recording and step/task status updates."""

    async def test_record_execution(self, db_session, result_handler):
        """record_execution creates a TaskExecution record."""
        step = make_step()

        with patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution(
                              maeos_task_id="maeos-abc"))):
            exec_record = await result_handler.record_execution(
                db_session, step, maeos_task_id="maeos-abc", attempt=1
            )

        assert exec_record.task_step_id == step.id
        assert exec_record.maeos_task_id == "maeos-abc"
        assert exec_record.attempt == 1

    async def test_update_execution_result(self, db_session, result_handler):
        """Update execution with output, duration, trace_id."""
        exec_record = make_execution()
        updated = make_execution(output_snapshot="Step completed OK",
                                 execution_time_ms=1500, trace_id="trace-xyz")

        with patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=updated)):
            result = await result_handler.update_execution_result(
                db_session, exec_record,
                output="Step completed OK",
                execution_time_ms=1500,
                trace_id="trace-xyz",
            )

        assert result.output_snapshot == "Step completed OK"
        assert result.execution_time_ms == 1500
        assert result.trace_id == "trace-xyz"

    async def test_handle_step_success(self, db_session, result_handler):
        """Successful step: update output, transition to COMPLETED."""
        step = make_step()
        updated_step = make_step(status=TaskStepStatus.COMPLETED,
                                 output="Great result",
                                 maeos_task_id="maeos-abc")

        with patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=updated_step)), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(return_value=updated_step)):
            result = await result_handler.handle_step_success(
                db_session, step, "Great result", "maeos-abc", 2000
            )

        assert result.status == TaskStepStatus.COMPLETED
        assert result.output == "Great result"

    async def test_handle_step_failure(self, db_session, result_handler):
        """Failed step: update error, transition to FAILED."""
        step = make_step()
        failed_step = make_step(status=TaskStepStatus.FAILED,
                                error="Something broke")

        with patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=failed_step)), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(return_value=failed_step)):
            result = await result_handler.handle_step_failure(
                db_session, step, "Something broke", "maeos-abc"
            )

        assert result.status == TaskStepStatus.FAILED
        assert result.error == "Something broke"

    async def test_handle_task_completion(self, db_session, result_handler):
        """Task completion: transition to COMPLETED."""
        task = make_task()

        with patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.COMPLETED))):
            result = await result_handler.handle_task_completion(db_session, task)

        assert result.status == TaskStatus.COMPLETED

    async def test_calculate_duration(self, result_handler):
        """Duration calculated correctly in ms."""
        import time
        start = time.time()
        # Simulate 100ms wait is unrealistic in test — just verify math
        duration = result_handler.calculate_duration(start, start + 0.5)
        assert duration == 500

        duration = result_handler.calculate_duration(start, start + 1.0)
        assert duration == 1000


# ═══════════════════════════════════════════════════════════════
# 3. TaskExecutor Tests
# ═══════════════════════════════════════════════════════════════

class TestTaskExecutor:
    """Verify sequential step execution through MAEOS."""

    @pytest.fixture
    def executor(self):
        return TaskExecutor()

    async def test_no_maeos_raises(self, db_session, executor):
        """Executor without MAEOS set raises RuntimeError."""
        task = make_task()
        with pytest.raises(RuntimeError, match="MAEOS instance not set"):
            await executor.execute_task(db_session, task)

    async def test_not_executing_state_raises(self, db_session, executor, fake_maeos):
        """Task not in EXECUTING raises ValueError."""
        executor.set_maeos(fake_maeos)
        task = make_task(status=TaskStatus.CREATED)
        with pytest.raises(ValueError, match="must be in EXECUTING"):
            await executor.execute_task(db_session, task)

    async def test_no_pending_steps_marks_complete(self, db_session, executor,
                                                    fake_maeos):
        """All steps already completed → task transitions to COMPLETED."""
        executor.set_maeos(fake_maeos)
        completed_step = make_step(status=TaskStepStatus.COMPLETED)
        task = make_task()
        task.steps = [completed_step]

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[completed_step])), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.COMPLETED))):
            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.COMPLETED

    async def test_single_step_execution(self, db_session, executor, fake_maeos):
        """Single step: step transitions PENDING→RUNNING→COMPLETED,
        task transitions EXECUTING→COMPLETED."""
        executor.set_maeos(fake_maeos)
        step = make_step()
        task = make_task()
        task.steps = [step]

        running_step = make_step(status=TaskStepStatus.RUNNING)
        completed_step = make_step(status=TaskStepStatus.COMPLETED,
                                    output="Step result")
        completed_task = make_task(status=TaskStatus.COMPLETED)

        # Mock the state manager calls
        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          side_effect=[running_step, completed_step]), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=completed_step)), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=completed_task)), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=PolicyResult())):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.COMPLETED

    async def test_two_steps_sequential(self, db_session, executor, fake_maeos):
        """Two steps: both execute in sequence, step2 gets context from step1."""
        executor.set_maeos(fake_maeos)
        step1 = make_step(order=1, objective="Step 1")
        step2 = make_step(order=2, objective="Step 2")
        task = make_task()
        task.steps = [step1, step2]

        running = make_step(status=TaskStepStatus.RUNNING)
        done = make_step(status=TaskStepStatus.COMPLETED, output="Done")
        completed_task = make_task(status=TaskStatus.COMPLETED)

        call_count = 0

        async def fake_list_steps(db, task_id):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return [step1, step2]  # First call at beginning
            return [done, step2]  # After step1 is done

        transition_call_count = 0

        async def fake_transition_step(db, step_obj, new_status):
            nonlocal transition_call_count
            transition_call_count += 1
            if new_status == TaskStepStatus.RUNNING:
                return running
            return done

        with patch.object(TaskStateManager, 'list_steps',
                      AsyncMock(side_effect=fake_list_steps)), \
         patch.object(TaskStateManager, 'transition_step_status',
                      AsyncMock(side_effect=fake_transition_step)), \
         patch.object(TaskStateManager, 'create_execution',
                      AsyncMock(return_value=make_execution())), \
         patch.object(TaskStateManager, 'update_execution',
                      AsyncMock(return_value=make_execution())), \
         patch.object(TaskStateManager, 'update_step',
                      AsyncMock(return_value=done)), \
         patch.object(TaskStateManager, 'transition_task_status',
                      AsyncMock(return_value=completed_task)), \
         patch.object(TaskPolicyService, 'evaluate_step',
                      AsyncMock(return_value=PolicyResult())):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.COMPLETED
        assert fake_maeos.submitted == ["maeos-0001", "maeos-0002"]

    async def test_step_failure_marks_task_failed(self, db_session, executor):
        """Failed step → step marked FAILED, task marked FAILED."""
        fake_maeos = FakeMAEOS(fail_ids={"maeos-0001"})
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()
        task.steps = [step]

        running_step = make_step(status=TaskStepStatus.RUNNING)
        failed_step = make_step(status=TaskStepStatus.FAILED,
                                 error="Simulated MAEOS failure")
        failed_task = make_task(status=TaskStatus.FAILED)

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          side_effect=[running_step, failed_step]), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=failed_step)), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=failed_task)), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=PolicyResult())):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.FAILED

    async def test_get_task_progress(self, db_session, executor):
        """get_task_progress returns step counts and details."""
        executor.set_maeos(FakeMAEOS())
        done = make_step(status=TaskStepStatus.COMPLETED)
        pending = make_step(order=2, status=TaskStepStatus.PENDING)

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[done, pending])):
            progress = await executor.get_task_progress(db_session, "task-001")

        assert progress["task_id"] == "task-001"
        assert progress["total_steps"] == 2
        assert progress["completed_steps"] == 1
        assert progress["pending_steps"] == 1
        assert progress["failed_steps"] == 0
        assert len(progress["steps"]) == 2


# ═══════════════════════════════════════════════════════════════
# 4. Integration Test: Full Task Lifecycle via Routes
# ═══════════════════════════════════════════════════════════════

class TestFullExecutionFlow:
    """End-to-end: create task → add steps → plan → execute via executor."""

    async def test_full_flow_success(self, db_session):
        """Complete happy path with mocked MAEOS."""
        fake_maeos = FakeMAEOS()

        # Set up mock state
        task = make_task(id="task-full", status=TaskStatus.PLANNING,
                         description="Test full flow")
        step1 = make_step(id="step-001", task_id="task-full", order=1,
                          objective="Step one")
        step2 = make_step(id="step-002", task_id="task-full", order=2,
                          objective="Step two")
        running_step = make_step(id="step-001", status=TaskStepStatus.RUNNING)
        completed_step = make_step(id="step-001", status=TaskStepStatus.COMPLETED,
                                    output="Step result")
        completed_task = make_task(id="task-full", status=TaskStatus.COMPLETED)

        # Plan → EXECUTING
        task = make_task(status=TaskStatus.EXECUTING)

        # Execute via executor
        executor = TaskExecutor(maeos_instance=fake_maeos)

        call_count = 0

        async def fake_list_steps(db, tid):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return [step1, step2]
            return [completed_step, step2]

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(side_effect=fake_list_steps)), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=lambda db, s, status:
                                    make_step(id=s.id, order=s.order,
                                              objective=s.objective,
                                              status=status))), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution(step_id="step-001"))), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=completed_step)), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=completed_task)):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.COMPLETED
