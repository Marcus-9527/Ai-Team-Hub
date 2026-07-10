"""
test_task_trace.py — Execution Trace Integration Tests

Tests:
  1. TaskExecutionModel stores trace_id, start_time, end_time, teammate_id, model_name
  2. TraceLogger integration in TaskExecutor
  3. TaskEventLogger lifecycle events
  4. Trace fields persisted to DB
  5. Execution timestamps recorded correctly
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from backend.models import (
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskStatus, TaskStepStatus,
)
from backend.services.task.task_executor import TaskExecutor
from backend.services.task.task_events import TaskEventLogger, TaskEvent
from backend.services.task.task_result import TaskResultHandler
from backend.services.task.task_state import TaskStateManager

pytestmark = pytest.mark.asyncio


# ── Helpers ──

def make_task(**kwargs) -> TaskModel:
    defaults = dict(
        id="task-trace-001", title="Trace Test", description="Test",
        status=TaskStatus.EXECUTING, priority=2, intent="test",
        created_by="test",
    )
    defaults.update(kwargs)
    return TaskModel(**defaults)


def make_step(task_id="task-trace-001", order=1, **kwargs) -> TaskStepModel:
    defaults = dict(
        id=f"step-{order:03d}", task_id=task_id, order=order,
        objective=f"Step {order}", status=TaskStepStatus.PENDING,
        teammate_id="teammate-001",
    )
    defaults.update(kwargs)
    return TaskStepModel(**defaults)


def make_execution(**kwargs) -> TaskExecutionModel:
    defaults = dict(
        id="exec-trace-001", task_step_id="step-001",
        attempt=1, maeos_task_id="maeos-trace-001",
        trace_id="trace-abc-123",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        teammate_id="teammate-001",
        model_name="openrouter/auto",
    )
    defaults.update(kwargs)
    return TaskExecutionModel(**defaults)


class FakeMAEOS:
    def __init__(self):
        self._started = True

    async def submit(self, **kwargs) -> str:
        return "maeos-trace-001"

    async def wait(self, task_id: str, timeout: float = 300.0):
        return FakeMAEOSTask(task_id, status="COMPLETED", result="Trace result")


class FakeMAEOSTask:
    def __init__(self, task_id, status="COMPLETED", result="", error=""):
        self.id = task_id
        self.status = status
        self.result = result
        self.error = error
        self.trace_report = {"trace_id": "maeos-trace-report-001"}


# ── TaskEventLogger Unit Tests ──

class TestTaskEventLogger:

    def test_event_creation(self):
        """TaskEvent created with correct fields."""
        event = TaskEvent(event_type="CREATED", task_id="task-001")
        assert event.event_type == "CREATED"
        assert event.task_id == "task-001"
        assert event.timestamp > 0

    def test_logger_creates_events(self):
        """TaskEventLogger emits and stores events."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_created()
        logger.log_started()
        logger.log_step_started(step_id="s1", step_order=1, attempt=1)
        logger.log_step_completed(step_id="s1", step_order=1, attempt=1, duration_ms=500)
        logger.log_completed(total_steps=1)

        events = logger.get_events()
        assert len(events) == 5
        assert events[0]["event_type"] == "CREATED"
        assert events[1]["event_type"] == "STARTED"
        assert events[2]["event_type"] == "STEP_STARTED"
        assert events[3]["event_type"] == "STEP_COMPLETED"
        assert events[4]["event_type"] == "COMPLETED"

    def test_logger_step_failed_and_retry_flag(self):
        """STEP_FAILED event includes will_retry flag."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_step_failed(
            step_id="s1", step_order=1, attempt=1,
            error="Something broke", will_retry=True,
        )

        events = logger.get_events()
        assert events[0]["event_type"] == "STEP_FAILED"
        assert events[0]["data"]["will_retry"] is True
        assert events[0]["data"]["error"] == "Something broke"

    def test_logger_failed_event(self):
        """FAILED event with reason."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_failed(reason="Step failed after retries")
        events = logger.get_events()
        assert events[0]["event_type"] == "FAILED"
        assert "retries" in events[0]["data"]["reason"]

    # ── V3.0 Phase B: SSE Event Tests ──

    def test_log_execution_started(self):
        """EXECUTION_STARTED event with execution_id."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_execution_started(
            step_id="s1", step_order=1, execution_id="exec-001",
            attempt=1, teammate_id="engineer",
        )
        events = logger.get_events()
        assert events[0]["event_type"] == "EXECUTION_STARTED"
        assert events[0]["data"]["execution_id"] == "exec-001"
        assert events[0]["data"]["teammate_id"] == "engineer"

    def test_log_execution_completed(self):
        """EXECUTION_COMPLETED event with outcome and tokens."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_execution_completed(
            step_id="s1", step_order=1, execution_id="exec-001",
            outcome="SUCCESS", duration_ms=1200, total_tokens=500,
        )
        events = logger.get_events()
        assert events[0]["event_type"] == "EXECUTION_COMPLETED"
        assert events[0]["data"]["outcome"] == "SUCCESS"
        assert events[0]["data"]["duration_ms"] == 1200
        assert events[0]["data"]["total_tokens"] == 500

    def test_log_execution_failed(self):
        """EXECUTION_FAILED event with error message."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_execution_failed(
            step_id="s1", step_order=1, execution_id="exec-001",
            error="Timeout after 30s",
        )
        events = logger.get_events()
        assert events[0]["event_type"] == "EXECUTION_FAILED"
        assert "Timeout" in events[0]["data"]["error"]

    def test_log_plan_created(self):
        """PLAN_CREATED event with summary."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_plan_created(
            step_id="s1", step_order=1,
            plan_summary="3-step execution plan", steps_count=3,
        )
        events = logger.get_events()
        assert events[0]["event_type"] == "PLAN_CREATED"
        assert events[0]["data"]["plan_summary"] == "3-step execution plan"
        assert events[0]["data"]["steps_count"] == 3

    def test_log_approval_completed(self):
        """APPROVAL_COMPLETED event with result."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_approval_completed(
            step_id="s1", step_order=1,
            approval_id="aprv-001", result="APPROVED", reviewer="manager",
        )
        events = logger.get_events()
        assert events[0]["event_type"] == "APPROVAL_COMPLETED"
        assert events[0]["data"]["result"] == "APPROVED"
        assert events[0]["data"]["reviewer"] == "manager"

    def test_log_execution_quality_updated(self):
        """EXECUTION_QUALITY_UPDATED event with quality score."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_execution_quality_updated(
            step_id="s1", step_order=1,
            execution_id="exec-001", overall_quality=0.85,
        )
        events = logger.get_events()
        assert events[0]["event_type"] == "EXECUTION_QUALITY_UPDATED"
        assert events[0]["data"]["overall_quality"] == 0.85

    def test_all_phase_b_event_types_roundtrip(self):
        """All 6 Phase B event types can be emitted in sequence."""
        logger = TaskEventLogger(task_id="task-001")
        logger.log_plan_created(step_id="s1", step_order=1, plan_summary="Plan", steps_count=2)
        logger.log_execution_started(step_id="s1", step_order=1, execution_id="e1", attempt=1)
        logger.log_execution_completed(step_id="s1", step_order=1, execution_id="e1", outcome="SUCCESS")
        logger.log_execution_quality_updated(step_id="s1", step_order=1, execution_id="e1", overall_quality=0.9)
        logger.log_approval_completed(step_id="s1", step_order=1, result="APPROVED")
        logger.log_execution_failed(step_id="s2", step_order=2, execution_id="e2", error="fail")

        events = logger.get_events()
        assert len(events) == 6
        types = [e["event_type"] for e in events]
        assert types == [
            "PLAN_CREATED", "EXECUTION_STARTED", "EXECUTION_COMPLETED",
            "EXECUTION_QUALITY_UPDATED", "APPROVAL_COMPLETED", "EXECUTION_FAILED",
        ]


# ── Execution Trace Fields Tests ──

class TestExecutionTraceFields:

    async def test_creation_with_trace_fields(self, db_session):
        """TaskExecutionModel stores trace_id, start_time, teammate_id, model."""
        state = TaskStateManager()
        now = datetime.now(timezone.utc)

        execution = await state.create_execution(
            db_session,
            task_step_id="step-trace-001",
            attempt=1,
            maeos_task_id="maeos-001",
            trace_id="trace-xyz",
            start_time=now,
            teammate_id="tm-001",
            model_name="openrouter/auto",
        )

        assert execution.trace_id == "trace-xyz"
        assert execution.start_time == now
        assert execution.teammate_id == "tm-001"
        assert execution.model_name == "openrouter/auto"

    async def test_to_dict_includes_trace_fields(self):
        """to_dict() returns all new trace fields."""
        now = datetime.now(timezone.utc)
        execution = make_execution(
            trace_id="trace-abc",
            start_time=now,
            end_time=now,
            teammate_id="tm-001",
            model_name="gpt-4o",
        )
        d = execution.to_dict()
        assert d["trace_id"] == "trace-abc"
        assert d["start_time"] == now.isoformat()
        assert d["end_time"] == now.isoformat()
        assert d["teammate_id"] == "tm-001"
        assert d["model_name"] == "gpt-4o"

    async def test_update_execution_preserves_trace_fields(self, db_session):
        """update_execution can set trace fields via kwargs."""
        state = TaskStateManager()
        execution = make_execution()
        now = datetime.now(timezone.utc)

        updated = await state.update_execution(
            db_session, execution,
            trace_id="new-trace-id",
            end_time=now,
            teammate_id="tm-002",
            model_name="deepseek-chat",
        )

        assert updated.trace_id == "new-trace-id"
        assert updated.end_time == now
        assert updated.teammate_id == "tm-002"


# ── Task Result Handler Trace Integration ──

class TestResultHandlerTrace:

    async def test_record_execution_with_trace(self, db_session):
        """record_execution passes trace/teammate/model to state."""
        handler = TaskResultHandler()
        step = make_step()

        with patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution(
                              trace_id="trace-handler",
                              teammate_id="tm-001",
                              model_name="claude-sonnet-4",
                          ))):
            exec_record = await handler.record_execution(
                db_session, step,
                maeos_task_id="maeos-001",
                attempt=1,
                trace_id="trace-handler",
                teammate_id="tm-001",
                model_name="claude-sonnet-4",
            )

        assert exec_record.trace_id == "trace-handler"
        assert exec_record.teammate_id == "tm-001"
        assert exec_record.model_name == "claude-sonnet-4"


# ── TaskExecutor Trace Integration Tests ──

class TestExecutorTraceIntegration:

    @pytest.fixture
    def db_session(self):
        session = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.refresh = AsyncMock()
        return session

    async def test_execute_generates_trace_id(self, db_session):
        """Executor generates a trace_id and passes it to execution records."""
        maeos = FakeMAEOS()
        executor = TaskExecutor(maeos_instance=maeos)
        step = make_step()
        task = make_task()
        task.steps = [step]
        completed_step = make_step(status=TaskStepStatus.COMPLETED, output="Done")

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=lambda db, s, status:
                                    make_step(id=s.id, status=status))), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution(
                              trace_id="any-non-empty",
                              teammate_id="teammate-001",
                          ))), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution(
                              trace_id="any-non-empty",
                          ))), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=completed_step)), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.COMPLETED))):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.COMPLETED
