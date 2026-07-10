"""test_task_approval.py — Phase C1 Human Approval Layer Tests

Coverage:
  - Create approval request (pause task, emit event)
  - Approve approval (resume task)
  - Reject approval (cancel task)
  - Expire approval
  - Error cases: non-PENDING approval, non-existent approval
  - Executor integration: step with requires_approval pauses task
"""

import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStatus,
    TaskStepModel,
    TaskStepStatus,
    TaskApprovalModel,
    ApprovalStatus,
)
from backend.services.task.task_approval_service import TaskApprovalService
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_executor import TaskExecutor, ApprovalRequiredError
from backend.services.task.task_events import TaskEventLogger
from backend.services.task.task_policy import TaskPolicyService, RiskLevel


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


async def _create_test_task(db: AsyncSession) -> TaskModel:
    """Create a basic task in EXECUTING state."""
    state = TaskStateManager()
    task = await state.create_task(
        db,
        title="Test Approval Task",
        description="Test",
        created_by="tester",
        channel_id=None,
    )
    task = await state.transition_task_status(db, task, TaskStatus.PLANNING)
    task = await state.transition_task_status(db, task, TaskStatus.EXECUTING)
    await db.flush()
    return task


async def _create_test_step(
    db: AsyncSession, task: TaskModel, requires_approval: str = "0"
) -> TaskStepModel:
    """Create a step under a task."""
    state = TaskStateManager()
    step = await state.create_step(
        db,
        task_id=task.id,
        order=1,
        objective="Test step",
        requires_approval=requires_approval,
    )
    await db.flush()
    return step


# ═══════════════════════════════════════════════════════════════
# Approval Service Tests
# ═══════════════════════════════════════════════════════════════


class TestTaskApprovalService:
    """Direct unit tests for TaskApprovalService."""

    @pytest.mark.asyncio
    async def test_create_approval_pauses_task(self, db_session: AsyncSession):
        """Creating an approval should pause the task."""
        svc = TaskApprovalService()
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")

        approval = await svc.create_approval(db_session, task, step)

        assert approval is not None
        assert approval.task_id == task.id
        assert approval.step_id == step.id
        assert approval.status == ApprovalStatus.PENDING

        # Task should be PAUSED
        task = await state.get_task(db_session, task.id)
        assert task.status == TaskStatus.PAUSED

    @pytest.mark.asyncio
    async def test_create_approval_with_events(self, db_session: AsyncSession):
        """Creating an approval should emit APPROVAL_REQUIRED event."""
        svc = TaskApprovalService()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        events = TaskEventLogger(task.id)

        approval = await svc.create_approval(
            db_session, task, step, reason="Need check", events=events
        )

        # Check event was recorded
        event_list = events.get_events()
        assert any(e["event_type"] == "APPROVAL_REQUIRED" for e in event_list)
        approval_event = [e for e in event_list if e["event_type"] == "APPROVAL_REQUIRED"][0]
        assert approval_event["data"]["approval_id"] == approval.id

    @pytest.mark.asyncio
    async def test_approve_resumes_task(self, db_session: AsyncSession):
        """Approving should resume the task (PAUSED → EXECUTING)."""
        svc = TaskApprovalService()
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        approval = await svc.create_approval(db_session, task, step)

        # Approve
        result = await svc.approve(db_session, approval.id, approved_by="admin")

        assert result.status == ApprovalStatus.APPROVED
        assert result.approved_by == "admin"

        # Task should be EXECUTING again
        task = await state.get_task(db_session, task.id)
        assert task.status == TaskStatus.EXECUTING

    @pytest.mark.asyncio
    async def test_approve_emits_approved_event(self, db_session: AsyncSession):
        """Approving should emit APPROVED event."""
        svc = TaskApprovalService()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        events = TaskEventLogger(task.id)
        approval = await svc.create_approval(db_session, task, step)

        await svc.approve(
            db_session, approval.id, approved_by="admin", events=events
        )

        event_list = events.get_events()
        assert any(e["event_type"] == "APPROVED" for e in event_list)

    @pytest.mark.asyncio
    async def test_reject_cancels_task(self, db_session: AsyncSession):
        """Rejecting should cancel the task (PAUSED → CANCELLED)."""
        svc = TaskApprovalService()
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        approval = await svc.create_approval(db_session, task, step)

        # Reject
        result = await svc.reject(db_session, approval.id, approved_by="admin", reason="Not needed")

        assert result.status == ApprovalStatus.REJECTED
        assert result.approved_by == "admin"

        # Task should be CANCELLED
        task = await state.get_task(db_session, task.id)
        assert task.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_reject_emits_rejected_event(self, db_session: AsyncSession):
        """Rejecting should emit REJECTED event."""
        svc = TaskApprovalService()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        events = TaskEventLogger(task.id)
        approval = await svc.create_approval(db_session, task, step)

        await svc.reject(
            db_session, approval.id, approved_by="admin", reason="Skip", events=events
        )

        event_list = events.get_events()
        assert any(e["event_type"] == "REJECTED" for e in event_list)

    @pytest.mark.asyncio
    async def test_expire_pending(self, db_session: AsyncSession):
        """Expiring a PENDING approval should set status to EXPIRED."""
        svc = TaskApprovalService()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        approval = await svc.create_approval(db_session, task, step)

        result = await svc.expire(db_session, approval.id)

        assert result.status == ApprovalStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_approve_non_pending_raises(self, db_session: AsyncSession):
        """Approving a non-PENDING approval should raise ValueError."""
        svc = TaskApprovalService()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        approval = await svc.create_approval(db_session, task, step)

        # First approve
        await svc.approve(db_session, approval.id)

        # Second approve should fail
        with pytest.raises(ValueError, match="Cannot approve"):
            await svc.approve(db_session, approval.id)

    @pytest.mark.asyncio
    async def test_reject_non_pending_raises(self, db_session: AsyncSession):
        """Rejecting a non-PENDING approval should raise ValueError."""
        svc = TaskApprovalService()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        approval = await svc.create_approval(db_session, task, step)

        await svc.approve(db_session, approval.id)

        with pytest.raises(ValueError, match="Cannot reject"):
            await svc.reject(db_session, approval.id)

    @pytest.mark.asyncio
    async def test_get_nonexistent_approval_raises(self, db_session: AsyncSession):
        """Getting a non-existent approval should return None from service."""
        svc = TaskApprovalService()
        result = await svc.get_approval(db_session, "does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_approvals_by_task(self, db_session: AsyncSession):
        """Listing approvals should filter by task_id."""
        svc = TaskApprovalService()
        task_a = await _create_test_task(db_session)
        step_a = await _create_test_step(db_session, task_a)
        await svc.create_approval(db_session, task_a, step_a)

        task_b = await _create_test_task(db_session)
        step_b = await _create_test_step(db_session, task_b)
        await svc.create_approval(db_session, task_b, step_b)

        approvals_for_a = await svc.list_approvals(db_session, task_id=task_a.id)
        assert len(approvals_for_a) == 1
        assert approvals_for_a[0].task_id == task_a.id


# ═══════════════════════════════════════════════════════════════
# Executor Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestExecutorApprovalIntegration:
    """Tests for Executor + Approval integration."""

    @pytest.mark.asyncio
    async def test_executor_raises_approval_required(self, db_session: AsyncSession):
        """Executor should raise ApprovalRequiredError when policy requires approval."""
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")
        events = TaskEventLogger(task.id)

        # Set policy to MEDIUM with approval required
        svc = TaskPolicyService()
        await svc.upsert_policy(
            db_session, task.id,
            risk_level=RiskLevel.MEDIUM,
            approval_required="1",
        )

        executor = TaskExecutor()
        approval_svc = executor.approval

        with pytest.raises(ApprovalRequiredError):
            await executor._execute_single_step(
                db_session, task, step,
                trace=None,
                events=events,
            )

        # Approval should have been created
        approval = await approval_svc.get_pending_approval_for_step(
            db_session, step.id
        )
        assert approval is not None
        assert approval.status == ApprovalStatus.PENDING

        # Task should be PAUSED
        task = await state.get_task(db_session, task.id)
        assert task.status == TaskStatus.PAUSED

    @pytest.mark.asyncio
    async def test_executor_skips_approval_when_not_needed(self, db_session: AsyncSession):
        """Executor should NOT pause for low-risk policy (no approval needed)."""
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="0")

        executor = TaskExecutor()
        # Default policy is LOW/approval_required=0 → no approval, no block
        policy_result = await executor.policy.evaluate_step(
            db_session, task, step
        )
        assert policy_result.allowed is True
        assert policy_result.requires_approval is False

    @pytest.mark.asyncio
    async def test_approve_then_executor_can_continue(self, db_session: AsyncSession):
        """After approval, the task is EXECUTING again and can be resumed."""
        svc = TaskApprovalService()
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")

        # Create approval (pauses task)
        approval = await svc.create_approval(db_session, task, step)

        # Verify paused
        task = await state.get_task(db_session, task.id)
        assert task.status == TaskStatus.PAUSED

        # Approve
        await svc.approve(db_session, approval.id, approved_by="admin")

        # Verify resumed
        task = await state.get_task(db_session, task.id)
        assert task.status == TaskStatus.EXECUTING

        # Approval should be APPROVED
        approval = await svc.get_approval(db_session, approval.id)
        assert approval.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_reject_then_task_is_cancelled(self, db_session: AsyncSession):
        """After rejection, the task is CANCELLED."""
        svc = TaskApprovalService()
        state = TaskStateManager()
        task = await _create_test_task(db_session)
        step = await _create_test_step(db_session, task, requires_approval="1")

        approval = await svc.create_approval(db_session, task, step)

        await svc.reject(db_session, approval.id, approved_by="admin", reason="Not needed")

        task = await state.get_task(db_session, task.id)
        assert task.status == TaskStatus.CANCELLED

        approval = await svc.get_approval(db_session, approval.id)
        assert approval.status == ApprovalStatus.REJECTED
