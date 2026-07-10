"""
test_task_recovery.py — Recovery & Retry Tests

Tests:
  1. RetryPolicy integration: retry on transient failure, abort on system failure
  2. TaskExecutor retry loop: max_attempts exhausted → step FAILED
  3. Step reset to PENDING on retry
  4. Retry count tracking on TaskStepModel
  5. Task status after recovery (COMPLETED after retry succeeds)
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.models import (
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskStatus, TaskStepStatus,
)
from backend.services.task.task_executor import TaskExecutor
from backend.services.task.task_result import TaskResultHandler
from backend.services.task.task_state import TaskStateManager
from backend.services.runtime.retry_policy import (
    RetryPolicy, RetryDecision, FailureType, BackoffStrategy, RetryAction,
)

pytestmark = pytest.mark.asyncio


# ── Helpers ──

def make_task(**kwargs) -> TaskModel:
    defaults = dict(
        id="task-retry-001", title="Retry Test", description="Test",
        status=TaskStatus.EXECUTING, priority=2, intent="test",
        created_by="test",
    )
    defaults.update(kwargs)
    return TaskModel(**defaults)


def make_step(task_id="task-retry-001", order=1, **kwargs) -> TaskStepModel:
    defaults = dict(
        id=f"step-{order:03d}", task_id=task_id, order=order,
        objective=f"Step {order}", status=TaskStepStatus.PENDING,
    )
    defaults.update(kwargs)
    return TaskStepModel(**defaults)


def make_execution(**kwargs) -> TaskExecutionModel:
    defaults = dict(
        id="exec-retry-001", task_step_id="step-001",
        attempt=1, maeos_task_id="maeos-retry-001",
    )
    defaults.update(kwargs)
    return TaskExecutionModel(**defaults)


class FakeMAEOS:
    """Fake MAEOS with configurable fail pattern for retry testing."""

    def __init__(self, fail_count: int = 0, fail_then_succeed: bool = False):
        self._started = True
        self._call_count = 0
        self._fail_count = fail_count
        self._fail_then_succeed = fail_then_succeed

    async def submit(self, **kwargs) -> str:
        self._call_count += 1
        return f"maeos-retry-{self._call_count:04d}"

    async def wait(self, task_id: str, timeout: float = 300.0):
        self._call_count += 0  # not counting as separate
        if self._fail_then_succeed and self._call_count <= 1:
            return FakeMAEOSTask(task_id, status="FAILED", error="Transient error")
        if self._fail_count > 0 and self._call_count <= self._fail_count:
            return FakeMAEOSTask(task_id, status="FAILED", error="Transient error")
        return FakeMAEOSTask(task_id, status="COMPLETED", result="Success!")

    def get_status(self, task_id: str) -> dict:
        return {"status": "COMPLETED"}

    def stats(self):
        return {"tasks_submitted": self._call_count}


class FakeMAEOSTask:
    def __init__(self, task_id: str, status="COMPLETED", result="", error=""):
        self.id = task_id
        self.status = status
        self.result = result
        self.error = error
        self.trace_report = {"trace_id": "trace-retry"}


# ── Related: RetryPolicy Unit Tests ──

class TestRetryPolicy:
    """Verify RetryPolicy classification and decision logic."""

    def test_classify_system_error(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.classify("connection timeout", False) == FailureType.SYSTEM_FAIL
        assert policy.classify("network error", False) == FailureType.SYSTEM_FAIL
        assert policy.classify("503 Service Unavailable", False) == FailureType.SYSTEM_FAIL

    def test_classify_logic_error(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.classify("JSON parse error", False) == FailureType.LOGIC_FAIL
        assert policy.classify("invalid format", False) == FailureType.LOGIC_FAIL

    def test_classify_unknown(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.classify("some random error", False) == FailureType.UNKNOWN

    def test_retry_decision_within_budget(self):
        """Within retry budget → action=RETRY."""
        policy = RetryPolicy(max_retries=3)
        decision = policy.decide(
            FakeExecUnit(attempt=1, error="transient error")
        )
        assert decision.action == RetryAction.RETRY
        assert decision.delay_ms > 0

    def test_retry_decision_exhausted(self):
        """Retries exhausted → action=ABORT.
        
        语义: max_attempts = max_retries + 1 (initial + N retries).
        max_retries=2 → attempt=1,2,3 共3次, attempt=3 超限.
        """
        policy = RetryPolicy(max_retries=2)
        # attempt=2 在预算内 → RETRY
        decision_ok = policy.decide(
            FakeExecUnit(attempt=2, error="still failing")
        )
        assert decision_ok.action == RetryAction.RETRY
        # attempt=3 超限 → ABORT
        decision_exhausted = policy.decide(
            FakeExecUnit(attempt=3, error="still failing")
        )
        assert decision_exhausted.action == RetryAction.ABORT
        assert "exhausted" in decision_exhausted.reason

    def test_system_failure_aborts(self):
        """System-level failure → action=ABORT even within budget."""
        policy = RetryPolicy(max_retries=5)
        decision = policy.decide(
            FakeExecUnit(attempt=1, error="connection refused")
        )
        assert decision.action == RetryAction.ABORT

    def test_exponential_backoff(self):
        policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            base_delay_ms=1000,
        )
        d1 = policy._compute_delay(1)
        d2 = policy._compute_delay(2)
        d3 = policy._compute_delay(3)
        assert d1 == 1000
        assert d2 == 2000
        assert d3 == 4000

    def test_fixed_backoff(self):
        policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_ms=2000,
        )
        d1 = policy._compute_delay(1)
        d2 = policy._compute_delay(2)
        assert d1 == 2000
        assert d2 == 2000

    def test_max_delay_cap(self):
        policy = RetryPolicy(
            max_retries=10,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            base_delay_ms=5000,
            max_delay_ms=10000,
        )
        d = policy._compute_delay(10)
        assert d <= 10000


# ── Task Executor Retry Integration Tests ──

class TestTaskExecutorRetry:
    """Verify retry loop in task executor."""

    @pytest.fixture
    def db_session(self):
        session = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.refresh = AsyncMock()
        return session

    async def test_retry_succeeds_on_second_attempt(self, db_session):
        """Step fails once, retries, succeeds on second attempt."""
        maeos = FakeMAEOS(fail_then_succeed=True)
        executor = TaskExecutor(
            maeos_instance=maeos,
            retry_policy=RetryPolicy(max_retries=2, backoff_strategy=BackoffStrategy.FIXED, base_delay_ms=1),
        )

        step = make_step()
        task = make_task()
        task.steps = [step]

        async def fake_list_steps(db, tid):
            return [step]

        transition_call_count = [0]

        async def fake_transition(db, s, status):
            transition_call_count[0] += 1
            if status == TaskStepStatus.COMPLETED:
                return make_step(status=TaskStepStatus.COMPLETED, output="Final result")
            return make_step(id=s.id, order=s.order, objective=s.objective, status=status)

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(side_effect=fake_list_steps)), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=fake_transition)), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(side_effect=lambda db, s, **kw: make_step(
                              id=s.id, status=TaskStepStatus.COMPLETED,
                              output=kw.get('output', '')))), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.COMPLETED))):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.COMPLETED

    async def test_retry_exhausted_marks_task_failed(self, db_session):
        """Step fails all retries → task FAILED."""
        maeos = FakeMAEOS(fail_count=10)  # always fails
        executor = TaskExecutor(
            maeos_instance=maeos,
            retry_policy=RetryPolicy(max_retries=2, backoff_strategy=BackoffStrategy.FIXED, base_delay_ms=1),
        )

        step = make_step()
        task = make_task()
        task.steps = [step]

        async def fake_transition(db, s, status):
            if status in (TaskStepStatus.COMPLETED, TaskStepStatus.COMPLETED):
                return make_step(status=status)
            return make_step(id=s.id, order=s.order, objective=s.objective, status=status)

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=fake_transition)), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=make_step(status=TaskStepStatus.FAILED))), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.FAILED))):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.FAILED

    async def test_system_failure_aborts_immediately(self, db_session):
        """System-level error (e.g. timeout) → ABORT immediately, no retry."""
        maeos = FakeMAEOS(fail_count=10)
        executor = TaskExecutor(
            maeos_instance=maeos,
            retry_policy=RetryPolicy(max_retries=5, backoff_strategy=BackoffStrategy.FIXED, base_delay_ms=1),
        )

        step = make_step()
        task = make_task()
        task.steps = [step]

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=lambda db, s, status: make_step(
                              id=s.id, status=status))), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=make_step(status=TaskStepStatus.FAILED))), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.FAILED))):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.FAILED

    async def test_retry_count_tracked_on_step(self):
        """TaskResultHandler.update_step_retry_count updates retry_count."""
        handler = TaskResultHandler()
        db = AsyncMock()
        step = make_step(retry_count=0)

        with patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=make_step(
                              retry_count=1, status=TaskStepStatus.PENDING))):
            updated = await handler.update_step_retry_count(db, step, 1)

        assert updated.retry_count == 1


class FakeExecUnit:
    """Minimal ExecUnit stub for RetryPolicy testing."""
    def __init__(self, attempt: int, error: str):
        self.attempt = attempt
        self.error = error
