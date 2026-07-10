"""test_task_policy.py — Phase C2 Task Policy Layer Tests

Coverage:
  - Default policy created with task
  - Policy CRUD: get, upsert
  - evaluate_step: LOW/auto-proceed, MEDIUM/approval, HIGH/blocked
  - Evaluate with retry limit, teammate permission, cost limit
  - Executor integration: PolicyBlockedError triggered for HIGH risk
"""

import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStatus,
    TaskStepModel,
    TaskStepStatus,
    TaskPolicyModel,
    RiskLevel,
)
from backend.services.task.task_policy import TaskPolicyService, PolicyResult
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_executor import (
    TaskExecutor,
    ApprovalRequiredError,
    PolicyBlockedError,
)
from backend.services.task.task_events import TaskEventLogger
from backend.services.task.task_approval_service import TaskApprovalService


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


async def _create_test_task(db: AsyncSession) -> TaskModel:
    state = TaskStateManager()
    task = await state.create_task(
        db,
        title="Test Policy Task",
        description="Test",
        created_by="tester",
        channel_id=None,
    )
    task = await state.transition_task_status(db, task, TaskStatus.PLANNING)
    task = await state.transition_task_status(db, task, TaskStatus.EXECUTING)
    await db.flush()
    return task


async def _create_test_step(
    db: AsyncSession, task: TaskModel
) -> TaskStepModel:
    state = TaskStateManager()
    step = await state.create_step(
        db,
        task_id=task.id,
        order=1,
        objective="Test step",
    )
    await db.flush()
    return step


# ═══════════════════════════════════════════════════════════════
# Policy Service Tests
# ═══════════════════════════════════════════════════════════════


class TestTaskPolicyService:

    @pytest.mark.asyncio
    async def test_default_policy_created_with_task(self, db_session: AsyncSession):
        """A default LOW-risk policy should exist after task creation."""
        task = await _create_test_task(db_session)

        svc = TaskPolicyService()
        policy = await svc.get_policy(db_session, task.id)

        assert policy is not None
        assert policy.task_id == task.id
        assert policy.risk_level == RiskLevel.LOW
        assert policy.approval_required == "0"
        assert policy.max_retry == 2
        assert policy.max_cost == 0
        assert policy.get_allowed_teammates() == []

    @pytest.mark.asyncio
    async def test_get_policy_auto_creates_default(self, db_session: AsyncSession):
        """Getting policy for a task without one should auto-create default."""
        # Manually create task without creating it via state manager
        task = TaskModel(
            title="Orphan task",
            description="",
            created_by="tester",
            status=TaskStatus.CREATED,
        )
        db_session.add(task)
        await db_session.flush()

        svc = TaskPolicyService()
        policy = await svc.get_policy(db_session, task.id)
        assert policy is not None
        assert policy.risk_level == RiskLevel.LOW

    @pytest.mark.asyncio
    async def test_upsert_policy(self, db_session: AsyncSession):
        """Updating policy should change fields."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()

        policy = await svc.upsert_policy(
            db_session, task.id,
            risk_level=RiskLevel.HIGH,
            max_retry=5,
            max_cost=1000,
            approval_required="1",
            allowed_teammates='["alice"]',
        )

        assert policy.risk_level == RiskLevel.HIGH
        assert policy.max_retry == 5
        assert policy.max_cost == 1000
        assert policy.approval_required == "1"
        assert policy.get_allowed_teammates() == ["alice"]

    @pytest.mark.asyncio
    async def test_partial_upsert(self, db_session: AsyncSession):
        """Partial update should only change specified fields."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()

        # Update only risk_level
        policy = await svc.upsert_policy(
            db_session, task.id, risk_level=RiskLevel.HIGH
        )
        assert policy.risk_level == RiskLevel.HIGH
        # Other fields should be at default
        assert policy.max_retry == 2

    # ── evaluate_step ──

    @pytest.mark.asyncio
    async def test_evaluate_step_low_auto_proceed(self, db_session: AsyncSession):
        """LOW risk with approval_required=0 should allow execution."""
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task)
        svc = TaskPolicyService()

        # Default policy is LOW, approval_required=0
        result = await svc.evaluate_step(db_session, task, step)

        assert result.allowed is True
        assert result.requires_approval is False
        assert result.blocked_reason == ""

    @pytest.mark.asyncio
    async def test_evaluate_step_medium_requires_approval(self, db_session: AsyncSession):
        """MEDIUM risk with approval_required=1 should require approval."""
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task)
        svc = TaskPolicyService()

        await svc.upsert_policy(
            db_session, task.id,
            risk_level=RiskLevel.MEDIUM,
            approval_required="1",
        )

        result = await svc.evaluate_step(db_session, task, step)

        assert result.allowed is True
        assert result.requires_approval is True

    @pytest.mark.asyncio
    async def test_evaluate_step_high_blocked(self, db_session: AsyncSession):
        """HIGH risk should block execution."""
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task)
        svc = TaskPolicyService()

        await svc.upsert_policy(db_session, task.id, risk_level=RiskLevel.HIGH)

        result = await svc.evaluate_step(db_session, task, step)

        assert result.allowed is False
        assert "risk_level=HIGH" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_evaluate_step_retry_limit_blocked(self, db_session: AsyncSession):
        """Step exceeding max_retry should be blocked."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()
        state = TaskStateManager()

        step = await state.create_step(
            db_session, task_id=task.id, order=1, objective="Retry test"
        )
        step.retry_count = 2  # equal to default max_retry=2
        await db_session.flush()

        result = await svc.evaluate_step(db_session, task, step)

        assert result.allowed is False
        assert "retry_count" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_evaluate_step_teammate_blocked(self, db_session: AsyncSession):
        """Step with disallowed teammate should be blocked."""
        task = await _create_test_task(db_session)
        state = TaskStateManager()
        svc = TaskPolicyService()

        step = await state.create_step(
            db_session, task_id=task.id, order=1, objective="Teammate test",
            teammate_id="bob",
        )

        # Only allow alice
        await svc.upsert_policy(
            db_session, task.id,
            allowed_teammates='["alice"]',
        )

        result = await svc.evaluate_step(db_session, task, step)

        assert result.allowed is False
        assert "bob" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_evaluate_step_allowed_teammate(self, db_session: AsyncSession):
        """Step with allowed teammate should proceed."""
        task = await _create_test_task(db_session)
        state = TaskStateManager()
        svc = TaskPolicyService()

        step = await state.create_step(
            db_session, task_id=task.id, order=1, objective="Teammate test",
            teammate_id="alice",
        )

        await svc.upsert_policy(
            db_session, task.id,
            allowed_teammates='["alice"]',
        )

        result = await svc.evaluate_step(db_session, task, step)

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_evaluate_step_empty_teammates_all_allowed(self, db_session: AsyncSession):
        """Empty allowed_teammates should allow any teammate."""
        task = await _create_test_task(db_session)
        state = TaskStateManager()
        svc = TaskPolicyService()

        step = await state.create_step(
            db_session, task_id=task.id, order=1, objective="Team test",
            teammate_id="anyone",
        )

        # Default policy has empty allowed_teammates
        result = await svc.evaluate_step(db_session, task, step)

        assert result.allowed is True

    # ── evaluate_cost ──

    @pytest.mark.asyncio
    async def test_evaluate_cost_within_limit(self, db_session: AsyncSession):
        """Cost within max_cost should be allowed."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()

        await svc.upsert_policy(db_session, task.id, max_cost=1000)

        result = await svc.evaluate_cost(db_session, task.id, 500)

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_evaluate_cost_exceeds_limit(self, db_session: AsyncSession):
        """Cost exceeding max_cost should be blocked."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()

        await svc.upsert_policy(db_session, task.id, max_cost=1000)

        result = await svc.evaluate_cost(db_session, task.id, 1500)

        assert result.allowed is False
        assert "Cost limit reached" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_evaluate_cost_unlimited(self, db_session: AsyncSession):
        """max_cost=0 means unlimited."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()

        result = await svc.evaluate_cost(db_session, task.id, 999999)

        assert result.allowed is True  # default max_cost=0 (unlimited)

    # ── check_permission ──

    @pytest.mark.asyncio
    async def test_check_permission_allowed(self, db_session: AsyncSession):
        """check_permission should return True for allowed teammate."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()

        await svc.upsert_policy(
            db_session, task.id, allowed_teammates='["alice"]',
        )

        assert await svc.check_permission(db_session, task.id, "alice") is True
        assert await svc.check_permission(db_session, task.id, "bob") is False

    @pytest.mark.asyncio
    async def test_check_permission_no_restriction(self, db_session: AsyncSession):
        """Empty allowed_teammates means anyone can execute."""
        task = await _create_test_task(db_session)
        svc = TaskPolicyService()

        assert await svc.check_permission(db_session, task.id, "anyone") is True


# ═══════════════════════════════════════════════════════════════
# Executor Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestExecutorPolicyIntegration:

    @pytest.mark.asyncio
    async def test_executor_raises_approval_via_policy(self, db_session: AsyncSession):
        """Executor should raise ApprovalRequiredError when MEDIUM risk + approval_required."""
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task)
        events = TaskEventLogger(task.id)

        # Set policy to MEDIUM with approval required
        svc = TaskPolicyService()
        await svc.upsert_policy(
            db_session, task.id,
            risk_level=RiskLevel.MEDIUM,
            approval_required="1",
        )

        executor = TaskExecutor()
        with pytest.raises(ApprovalRequiredError):
            await executor._execute_single_step(
                db_session, task, step,
                trace=None,
                events=events,
            )

        # Approval should have been created
        approval = await TaskApprovalService().get_pending_approval_for_step(
            db_session, step.id
        )
        assert approval is not None
        assert approval.status == "PENDING"

    @pytest.mark.asyncio
    async def test_executor_raises_policy_blocked(self, db_session: AsyncSession):
        """Executor should raise PolicyBlockedError for HIGH risk."""
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task)
        events = TaskEventLogger(task.id)

        # Set policy to HIGH
        svc = TaskPolicyService()
        await svc.upsert_policy(db_session, task.id, risk_level=RiskLevel.HIGH)

        executor = TaskExecutor()
        with pytest.raises(PolicyBlockedError):
            await executor._execute_single_step(
                db_session, task, step,
                trace=None,
                events=events,
            )

    @pytest.mark.asyncio
    async def test_executor_passes_low_risk(self, db_session: AsyncSession):
        """Executor should NOT raise for LOW risk policy (default)."""
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task)
        events = TaskEventLogger(task.id)

        # Default policy is LOW
        executor = TaskExecutor()

        # This test just verifies it doesn't raise approval/policy errors.
        # We can't fully execute MAEOS, but it should pass the policy check.
        step_requires = getattr(step, "requires_approval", "0") == "1"
        assert not step_requires  # Step field is irrelevant now

        # We can only verify the check passes by calling evaluate directly
        policy_result = await executor.policy.evaluate_step(
            db_session, task, step
        )
        assert policy_result.allowed is True
        assert policy_result.requires_approval is False
