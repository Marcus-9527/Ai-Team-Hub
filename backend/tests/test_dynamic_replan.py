"""
test_dynamic_replan.py — Phase 27 TechLead replan coverage.

Covers:
  1. Step fails after retries → TechLead replan → retry → success
  2. task.replan_decisions populated
  3. Completed step untouched after replan
"""
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel, TaskStepModel, TaskStatus, TaskStepStatus,
)
from backend.services.task.task_executor import TaskExecutor
from backend.services.task.task_result import TaskResultHandler
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_policy import TaskPolicyService, PolicyResult
from backend.services.task.task_events import TaskEventLogger
from backend.services.runtime.retry_policy import (
    RetryPolicy, BackoffStrategy, RetryAction,
)
from backend.services.runtime.trace import TraceLogger
from backend.services.runtime.executor import ExecStatus as RuntimeExecStatus

pytestmark = pytest.mark.asyncio


class FakeRuntimeTask:
    def __init__(self, task_id="exec-0001", status="COMPLETED",
                 result="", error=""):
        self.id = task_id
        self.status = status
        self.result = result
        self.error = error


class FakeRuntime:
    def __init__(self, fail_steps: int = 3):
        self._call_count = 0
        self._fail_steps = fail_steps

    async def submit(self, **kwargs) -> str:
        self._call_count += 1
        return f"exec-{self._call_count:04d}"

    async def wait(self, task_id: str, timeout=300.0):
        if self._call_count <= self._fail_steps:
            return FakeRuntimeTask(task_id, status="FAILED", error="Simulated failure")
        return FakeRuntimeTask(task_id, status="COMPLETED",
                               result="Result after replan")


def make_task(**kw) -> TaskModel:
    d = dict(id="task-rp-001", title="Replan Test Task",
             status=TaskStatus.RUNNING, priority=2,
             intent="test", created_by="test",
             replan_count=0, replan_decisions=[])
    d.update(kw)
    t = TaskModel(**d)
    t.steps = []
    return t


def make_step(task_id="task-rp-001", order=1, **kw) -> TaskStepModel:
    d = dict(id=f"step-rp-{order:03d}", task_id=task_id,
             order=order, objective=f"Step {order}",
             status=TaskStepStatus.PENDING)
    d.update(kw)
    return TaskStepModel(**d)


@pytest.fixture
def db_session():
    s = AsyncMock(spec=AsyncSession)
    s.commit = AsyncMock()
    s.rollback = AsyncMock()
    s.refresh = AsyncMock()
    s.flush = AsyncMock()
    return s


@pytest.fixture
def executor():
    return TaskExecutor(
        retry_policy=RetryPolicy(max_retries=1, base_delay_ms=1)
    )


async def test_replan_retry_on_failure(db_session, executor):
    """Step fails → TechLead replan → retry → completes."""
    task = make_task()
    step = make_step(objective="Write failing code")

    fake_rt = FakeRuntime(fail_steps=1)  # fail original, succeed replan
    executor._runtime = fake_rt

    # Mock TechLead replan to return retry decision
    async def fake_replan(*a, **kw):
        return {"action": "retry", "new_objective": "Write working code",
                "reassign": "tl-bot", "reasoning": "Wrong approach, try different pattern"}
    executor._trigger_replan = fake_replan

    # Mock state manager (transition_step_status auto-succeeds)
    async def fake_transition(db, step, status):
        step.status = status
        return step
    executor.state.transition_step_status = fake_transition

    async def fake_update_step(db, step, **kw):
        for k, v in kw.items():
            setattr(step, k, v)
        return step
    executor.state.update_step = fake_update_step

    async def fake_list_steps(*a, **kw):
        return [step]

    async def fake_create_step(*a, **kw):
        return step

    executor.state.list_steps = fake_list_steps

    # Mock context builder
    async def fake_build_context(*a, **kw):
        return "Context for step"
    executor.context_builder.build_maeos_description = fake_build_context

    # Mock policy — always allow
    async def fake_eval_step(*a, **kw):
        return PolicyResult(allowed=True, requires_approval=False)
    executor.policy.evaluate_step = fake_eval_step

    # Mock approval — never required
    async def fake_create_approval(*a, **kw):
        pass
    executor.approval.create_approval = fake_create_approval

    # Execute
    result = await executor.execute_task(db_session, task)

    # Step should be COMPLETED (TechLead replan rescued it)
    assert step.status == TaskStepStatus.COMPLETED, f"Expected COMPLETED, got {step.status}"
    assert step.objective == "Write working code", "Step objective should be updated by replan"
    assert task.replan_count == 1, f"Expected 1 replan, got {task.replan_count}"
    assert len(task.replan_decisions) == 1
    assert task.replan_decisions[0]["reasoning"] == "Wrong approach, try different pattern"


async def test_skip_step_via_replan(db_session, executor):
    """TechLead says skip → step marked SKIPPED, execution continues."""
    task = make_task()
    step = make_step(objective="Unnecessary step")

    fake_rt = FakeRuntime(fail_steps=99)
    executor._runtime = fake_rt

    async def fake_replan(*a, **kw):
        return {"action": "skip", "reasoning": "This step is unnecessary"}
    executor._trigger_replan = fake_replan

    async def fake_transition(db, step, status):
        step.status = status
        return step
    executor.state.transition_step_status = fake_transition

    async def fake_update_step(db, step, **kw):
        for k, v in kw.items():
            setattr(step, k, v)
        return step
    executor.state.update_step = fake_update_step

    async def fake_list_steps(*a, **kw):
        return [step]
    executor.state.list_steps = fake_list_steps

    async def fake_build_context(*a, **kw):
        return "ctx"
    executor.context_builder.build_maeos_description = fake_build_context

    async def fake_eval_step(*a, **kw):
        return PolicyResult(allowed=True, requires_approval=False)
    executor.policy.evaluate_step = fake_eval_step

    result = await executor.execute_task(db_session, task)

    assert step.status == TaskStepStatus.SKIPPED, f"Expected SKIPPED, got {step.status}"
    assert task.replan_count == 1
    assert task.replan_decisions[0]["decision"]["action"] == "skip"


async def test_reassign_step_via_replan(db_session, executor):
    """TechLead says reassign → teammate_id changes, step resolved."""
    task = make_task()
    step = make_step(objective="Needs different teammate", teammate_id="old-bot")

    fake_rt = FakeRuntime(fail_steps=99)
    executor._runtime = fake_rt

    async def fake_replan(*a, **kw):
        return {"action": "reassign", "reassign": "new-bot", "reasoning": "Better fit"}
    executor._trigger_replan = fake_replan

    async def fake_transition(db, step, status):
        step.status = status
        return step
    executor.state.transition_step_status = fake_transition

    async def fake_update_step(db, step, **kw):
        for k, v in kw.items():
            setattr(step, k, v)
        return step
    executor.state.update_step = fake_update_step

    async def fake_list_steps(*a, **kw):
        return [step]
    executor.state.list_steps = fake_list_steps

    async def fake_build_context(*a, **kw):
        return "ctx"
    executor.context_builder.build_maeos_description = fake_build_context

    async def fake_eval_step(*a, **kw):
        return PolicyResult(allowed=True, requires_approval=False)
    executor.policy.evaluate_step = fake_eval_step

    result = await executor.execute_task(db_session, task)

    assert step.teammate_id == "new-bot", f"Expected new-bot, got {step.teammate_id}"
    assert task.replan_count == 1
    assert task.replan_decisions[0]["decision"]["action"] == "reassign"


async def test_replan_abort_without_techlead(db_session, executor):
    """No TechLead teammate → step fails normally."""
    task = make_task()
    step = make_step()

    fake_rt = FakeRuntime(fail_steps=99)  # always fail
    executor._runtime = fake_rt

    # No TechLead — _trigger_replan returns None
    async def no_replan(*a, **kw):
        return None
    executor._trigger_replan = no_replan

    async def fake_transition(db, step, status):
        step.status = status
        return step
    executor.state.transition_step_status = fake_transition

    async def fake_update_step(db, step, **kw):
        for k, v in kw.items():
            setattr(step, k, v)
        return step
    executor.state.update_step = fake_update_step

    async def fake_list_steps(*a, **kw):
        return [step]
    executor.state.list_steps = fake_list_steps

    async def fake_build_context(*a, **kw):
        return "ctx"
    executor.context_builder.build_maeos_description = fake_build_context

    async def fake_eval_step(*a, **kw):
        return PolicyResult(allowed=True, requires_approval=False)
    executor.policy.evaluate_step = fake_eval_step

    result = await executor.execute_task(db_session, task)

    assert result.status == TaskStatus.FAILED, f"Expected FAILED, got {result.status}"
    assert step.status == TaskStepStatus.FAILED
    assert task.replan_count == 0
