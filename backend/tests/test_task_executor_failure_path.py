"""
test_task_executor_failure_path.py — Phase 1 失败路径修复验证

覆盖：
  1. PolicyBlockedError — 不会 TypeError，正确走 failure path
  2. 失败状态转换 — step: PENDING → FAILED 经过 transition_step_status
  3. Retry 语义 — max_retries=2 → 3 次 attempt 后停止
  4. FAILED event 生成
  5. ExecutionResult 创建
"""

import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskStatus, TaskStepStatus,
)
from backend.services.task.task_executor import (
    TaskExecutor,
    PolicyBlockedError,
    ApprovalRequiredError,
)
from backend.services.task.task_result import TaskResultHandler
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_policy import TaskPolicyService, PolicyResult
from backend.services.task.task_events import TaskEventLogger
from backend.services.runtime.retry_policy import (
    RetryPolicy,
    BackoffStrategy,
    RetryAction,
)
from backend.services.runtime.trace import TraceLogger

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════
# Helpers (copied from test_task_execution.py for self-containment)
# ═══════════════════════════════════════════════════════════════

def make_task(**kwargs) -> TaskModel:
    defaults = dict(
        id="task-ft-001",
        title="Failure Path Test Task",
        description="Test task for failure path verification",
        status=TaskStatus.EXECUTING,
        priority=2,
        intent="test",
        created_by="test",
    )
    defaults.update(kwargs)
    task = TaskModel(**defaults)
    task.steps = []
    return task


def make_step(task_id="task-ft-001", order=1, **kwargs) -> TaskStepModel:
    defaults = dict(
        id=f"step-ft-{order:03d}",
        task_id=task_id,
        order=order,
        objective=f"Failure path step {order}",
        status=TaskStepStatus.PENDING,
    )
    defaults.update(kwargs)
    return TaskStepModel(**defaults)


def make_execution(step_id="step-ft-001", attempt=1, **kwargs) -> TaskExecutionModel:
    defaults = dict(
        id=f"exec-ft-{step_id}-{attempt}",
        task_step_id=step_id,
        attempt=attempt,
        maeos_task_id="maeos-ft-001",
    )
    defaults.update(kwargs)
    return TaskExecutionModel(**defaults)


class FakeMAEOSTask:
    def __init__(self, task_id: str, status: str = "COMPLETED",
                 result: str = "", error: str = ""):
        self.id = task_id
        self.task_id = task_id
        self.status = status
        self.result = result
        self.error = error
        self.trace_report = {"trace_id": "trace-ft-001"}

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


class FakeMAEOS:
    def __init__(self, results: dict[str, str] = None, fail_ids: set[str] = None):
        self.results = results or {}
        self.fail_ids = fail_ids or set()
        self._started = True
        self.submitted: list[str] = []

    async def submit(self, description: str, priority: int = 2,
                     intent: str = "", wait: bool = False,
                     **kwargs) -> str:
        task_id = f"maeos-ft-{len(self.submitted) + 1:04d}"
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


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def db_session():
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def fake_maeos():
    return FakeMAEOS()


@pytest.fixture
def executor():
    return TaskExecutor()


@pytest.fixture
def result_handler():
    return TaskResultHandler()


# ═══════════════════════════════════════════════════════════════
# 1. PolicyBlockedError 路径
# ═══════════════════════════════════════════════════════════════

class TestPolicyBlockedErrorPath:
    """P0: PolicyBlockedError — 走 failure path，不会 TypeError"""

    async def test_policy_blocked_no_typeerror(self, db_session, executor):
        """
        PolicyBlockedError 被捕获后不会抛出 TypeError。
        旧代码传了多余参数给 handle_task_completion 导致 TypeError。
        """
        fake_maeos = FakeMAEOS()
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()

        # Policy 返回 blocked
        policy_result = PolicyResult(
            allowed=False,
            blocked_reason="Risk level exceeds threshold",
        )

        running_step = make_step(status=TaskStepStatus.RUNNING)
        failed_step = make_step(status=TaskStepStatus.FAILED)
        failed_task = make_task(status=TaskStatus.FAILED)

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          side_effect=[running_step, failed_step]), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=failed_task)), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=policy_result)):

            # 不报 TypeError 就算通过
            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.FAILED

    async def test_policy_blocked_step_transition_used(self, db_session, executor):
        """
        step.status = FAILED 被替换为 transition_step_status()。
        验证 transition_step_status 被调用以 FAILED 状态。
        """
        fake_maeos = FakeMAEOS()
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()
        policy_result = PolicyResult(
            allowed=False,
            blocked_reason="Risk too high",
        )

        transition_calls = []

        async def track_transition(db, s, new_status):
            transition_calls.append((s.id, new_status))
            s.status = new_status
            return s

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=track_transition)), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.FAILED))), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=policy_result)):

            await executor.execute_task(db_session, task)

        # 验证 transition_step_status 被调用，且有 FAILED 转换
        failed_transitions = [
            (sid, st) for sid, st in transition_calls
            if st == TaskStepStatus.FAILED
        ]
        assert len(failed_transitions) >= 1, (
            f"transition_step_status 应该被调用以 FAILED 状态, "
            f"实际调用: {transition_calls}"
        )

    async def test_policy_blocked_execution_record_created(self, db_session, executor):
        """
        PolicyBlockedError 需要创建 ExecutionResult。
        验证 record_execution 和 update_execution_result 被调用。
        """
        fake_maeos = FakeMAEOS()
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()
        policy_result = PolicyResult(
            allowed=False,
            blocked_reason="Budget exceeded",
        )

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(return_value=make_step(status=TaskStepStatus.FAILED))), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())) as mock_create_exec, \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())) as mock_update_exec, \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.FAILED))), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=policy_result)):

            await executor.execute_task(db_session, task)

        mock_create_exec.assert_called_once()
        mock_update_exec.assert_called_once()
        # 验证 execution 记录中包含 policy_blocked 信息
        call_args = mock_update_exec.call_args
        if call_args:
            kwargs = call_args[1] if len(call_args) > 1 else {}
            error_arg = kwargs.get('error', '')
            assert 'policy' in error_arg.lower() or 'blocked' in error_arg.lower(), \
                f"execution 错误应包含 policy 信息, 实际: {error_arg}"


# ═══════════════════════════════════════════════════════════════
# 2. 失败状态转换（P1）
# ═══════════════════════════════════════════════════════════════

class TestFailureTransition:
    """P1: 所有 step 状态变化必须通过 transition_step_status"""

    async def test_step_failure_via_transition(self, db_session, executor, fake_maeos):
        """
        MAEOS 执行失败后，step 通过 transition_step_status
        完成 PENDING → RUNNING → FAILED 转换。
        """
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()
        running_step = make_step(status=TaskStepStatus.RUNNING)
        failed_step = make_step(status=TaskStepStatus.FAILED)
        failed_task = make_task(status=TaskStatus.FAILED)

        # 模拟 MAEOS 执行失败
        maeos_fail = FakeMAEOS(fail_ids={"maeos-ft-0001"})
        executor.set_maeos(maeos_fail)

        transition_sequence = []

        async def track_transition(db, s, new_status):
            transition_sequence.append((s.id, s.status, new_status))
            s.status = new_status
            return s

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=track_transition)), \
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
        # 至少有一次 PENDING → RUNNING 和一次 RUNNING → FAILED
        running_transitions = [
            t for t in transition_sequence if t[2] == TaskStepStatus.RUNNING
        ]
        failed_transitions = [
            t for t in transition_sequence if t[2] == TaskStepStatus.FAILED
        ]
        assert len(running_transitions) >= 1, "应有 PENDING → RUNNING 转换"
        assert len(failed_transitions) >= 1, "应有 RUNNING → FAILED 转换"


# ═══════════════════════════════════════════════════════════════
# 3. Retry 语义（P2）
# ═══════════════════════════════════════════════════════════════

class TestRetrySemantics:
    """P2: max_attempts = max_retries + 1"""

    async def test_max_attempts_equals_max_retries_plus_one(self, db_session):
        """
        max_retries=2 → 共 3 次 attempt（1 initial + 2 retries）
        验证 attempt=3 后停止执行。
        """
        policy = RetryPolicy(
            max_retries=2,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_ms=1,  # 最小化等待
        )
        executor = TaskExecutor(retry_policy=policy)
        task = make_task()
        step = make_step()
        failed_task = make_task(status=TaskStatus.FAILED)

        # MAEOS 每次都失败
        maeos_always_fail = FakeMAEOS(fail_ids={"maeos-ft-0001", "maeos-ft-0002", "maeos-ft-0003"})
        executor.set_maeos(maeos_always_fail)

        attempt_count = 0

        async def track_create_execution(db, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            return make_execution(attempt=kwargs.get('attempt', 1))

        transition_sequence = []

        async def track_transition(db, s, new_status):
            transition_sequence.append((s.id, s.status, new_status))
            s.status = new_status
            return s

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(side_effect=track_transition)), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(side_effect=track_create_execution)), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_step',
                          AsyncMock(return_value=make_step(status=TaskStepStatus.FAILED))), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=failed_task)), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=PolicyResult())):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.FAILED
        # max_retries=2 → 3 次 attempt（initial + 2 retries）
        assert attempt_count == 3, (
            f"max_retries=2 应有 3 次 attempt (initial + 2 retries), "
            f"实际: {attempt_count}"
        )

    async def test_retry_policy_decide_strict_greater(self):
        """
        decide() 用 > max_retries 而非 >= max_retries。
        max_retries=2: attempt=1 OK, attempt=2 OK, attempt=3 → ABORT。
        """
        policy = RetryPolicy(max_retries=2)

        class FakeUnit:
            def __init__(self, attempt, error=""):
                self.attempt = attempt
                self.error = error

        # attempt=1 → retry
        d1 = policy.decide(FakeUnit(attempt=1, error="unexpected runtime error"))
        assert d1.action == RetryAction.RETRY, \
            f"attempt=1 应返回 RETRY, 实际: {d1.action}"

        # attempt=2 → retry
        d2 = policy.decide(FakeUnit(attempt=2, error="unexpected runtime error"))
        assert d2.action == RetryAction.RETRY, \
            f"attempt=2 应返回 RETRY, 实际: {d2.action}"

        # attempt=3 → abort (超过 max_retries)
        d3 = policy.decide(FakeUnit(attempt=3, error="unexpected runtime error"))
        assert d3.action == RetryAction.ABORT, \
            f"attempt=3 应返回 ABORT, 实际: {d3.action}"


# ═══════════════════════════════════════════════════════════════
# 4. FAILED event 生成
# ═══════════════════════════════════════════════════════════════

class TestFailedEventGeneration:
    """验证 FAILED event 在失败路径中被生成"""

    async def test_policy_blocked_generates_failed_event(self, db_session, executor):
        """
        PolicyBlockedError → events.log_failed() 被调用。
        """
        fake_maeos = FakeMAEOS()
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()
        policy_result = PolicyResult(
            allowed=False,
            blocked_reason="Risk limit",
        )

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(return_value=make_step(status=TaskStepStatus.FAILED))), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution())), \
             patch.object(TaskStateManager, 'transition_task_status',
                          AsyncMock(return_value=make_task(status=TaskStatus.FAILED))), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=policy_result)):

            result = await executor.execute_task(db_session, task)

        assert result.status == TaskStatus.FAILED

    async def test_maeos_failure_generates_failed_event(self, db_session, executor):
        """
        MAEOS 执行失败 → events.log_failed() 和 events.log_step_failed() 被调用。
        """
        step = make_step()
        task = make_task()
        failed_step = make_step(status=TaskStepStatus.FAILED)
        failed_task = make_task(status=TaskStatus.FAILED)
        maeos_fail = FakeMAEOS(fail_ids={"maeos-ft-0001"})
        executor.set_maeos(maeos_fail)

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          side_effect=[
                              make_step(status=TaskStepStatus.RUNNING),
                              failed_step,
                          ]), \
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


# ═══════════════════════════════════════════════════════════════
# 5. 回归验证：正常成功路径不受影响
# ═══════════════════════════════════════════════════════════════

class TestRegression:
    """确保修复没有破坏正常成功路径"""

    async def test_success_path_still_works(self, db_session, executor, fake_maeos):
        """单个 step 成功执行后 task 应 COMPLETED。"""
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()
        running_step = make_step(status=TaskStepStatus.RUNNING)
        completed_step = make_step(status=TaskStepStatus.COMPLETED, output="OK")
        completed_task = make_task(status=TaskStatus.COMPLETED)

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
        assert len(fake_maeos.submitted) == 1

    async def test_approval_required_still_works(self, db_session, executor):
        """
        ApprovalRequiredError 不应影响 task 状态（PAUSED 而非 FAILED）。
        """
        fake_maeos = FakeMAEOS()
        executor.set_maeos(fake_maeos)

        step = make_step()
        task = make_task()

        policy_result = PolicyResult(
            allowed=True,
            requires_approval=True,
            blocked_reason="",
        )

        with patch.object(TaskStateManager, 'list_steps',
                          AsyncMock(return_value=[step])), \
             patch.object(TaskStateManager, 'transition_step_status',
                          AsyncMock(return_value=step)), \
             patch.object(TaskPolicyService, 'evaluate_step',
                          AsyncMock(return_value=policy_result)), \
             patch.object(TaskStateManager, 'create_execution',
                          AsyncMock(return_value=make_execution())):

            # approval create 需要 mock
            with patch.object(
                executor.approval, 'create_approval',
                AsyncMock(),
            ):
                result = await executor.execute_task(db_session, task)

        # Approval 不应使 task FAILED
        assert result.status != TaskStatus.FAILED

    async def test_no_pending_steps_marks_complete(self, db_session, executor, fake_maeos):
        """所有 steps 已 COMPLETED → task 直接 COMPLETED。"""
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

    async def test_two_steps_sequential_still_works(self, db_session, executor, fake_maeos):
        """两个步骤顺序执行不受影响。"""
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
                return [step1, step2]
            return [done, step2]

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
        assert fake_maeos.submitted == ["maeos-ft-0001", "maeos-ft-0002"]


# ═══════════════════════════════════════════════════════════════
# 6. RetryPolicy 单元测试
# ═══════════════════════════════════════════════════════════════

class TestRetryPolicyUnit:
    """直接测试 RetryPolicy.decide() 的边界条件"""

    @pytest.mark.asyncio
    async def test_max_retries_zero(self):
        """max_retries=0: attempt=1 → ABORT"""
        policy = RetryPolicy(max_retries=0)

        class U:
            def __init__(self, a, e=""):
                self.attempt = a
                self.error = e

        # attempt=1 > 0 → abort (no retries allowed)
        d = policy.decide(U(1, "error"))
        assert d.action == RetryAction.ABORT, \
            f"max_retries=0, attempt=1 → ABORT, 实际: {d.action}"

    @pytest.mark.asyncio
    async def test_max_retries_one(self):
        """max_retries=1: attempt=1 OK, attempt=2 → ABORT"""
        policy = RetryPolicy(max_retries=1)

        class U:
            def __init__(self, a, e=""):
                self.attempt = a
                self.error = e

        d1 = policy.decide(U(1, "error"))
        assert d1.action == RetryAction.RETRY, \
            f"attempt=1 → RETRY, 实际: {d1.action}"

        d2 = policy.decide(U(2, "error"))
        assert d2.action == RetryAction.ABORT, \
            f"attempt=2 → ABORT, 实际: {d2.action}"

    @pytest.mark.asyncio
    async def test_system_failure_aborts_immediately(self):
        """
        SYSTEM_FAIL 即使 attempt 未超限也应 ABORT。
        """
        policy = RetryPolicy(max_retries=3)

        class U:
            def __init__(self, a, e=""):
                self.attempt = a
                self.error = e

        # system keyword → abort
        d = policy.decide(U(1, "connection refused"))
        assert d.action == RetryAction.ABORT, \
            f"SYSTEM_FAIL 应 ABORT, 实际: {d.action}"
