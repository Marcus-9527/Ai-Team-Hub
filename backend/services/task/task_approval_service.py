"""task_approval_service.py — Human Approval Layer (Phase C1)

Provides:
  - create_approval:  Pause task + create PENDING approval when a step needs review
  - approve:          Resume task, mark approval APPROVED
  - reject:           Cancel task, mark approval REJECTED
  - expire:           Mark approval EXPIRED (timeout / system action)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskStepStatus,
    TaskApprovalModel,
    ApprovalStatus,
    TaskStatus,
    gen_uuid,
    utcnow,
)
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_events import TaskEventLogger

logger = logging.getLogger("task.approval")


class TaskApprovalService:
    """Business logic for human-in-the-loop approval of task steps."""

    def __init__(self):
        self.state = TaskStateManager()

    # ── Create Approval Request ──

    async def create_approval(
        self,
        db: AsyncSession,
        task: TaskModel,
        step: TaskStepModel,
        reason: str = "",
        events: Optional[TaskEventLogger] = None,
    ) -> TaskApprovalModel:
        """
        Pause the task and create a PENDING approval request.

        Called by Executor when encountering a step with requires_approval=True.

        Steps:
          1. Reload step to confirm it's RUNNING
          2. Pause the task (EXECUTING → PAUSED)
          3. Create PENDING approval record
          4. Emit APPROVAL_REQUIRED event (if logger provided)
          5. Return approval record
        """
        # 1. Pause the task
        task = await self.state.transition_task_status(
            db, task, TaskStatus.PAUSED
        )

        # 2. Create approval request
        approval = TaskApprovalModel(
            task_id=task.id,
            step_id=step.id,
            status=ApprovalStatus.PENDING,
            reason=reason or "",
            requested_at=datetime.now(timezone.utc),
        )
        db.add(approval)
        await db.flush()

        logger.info(
            f"[APPROVAL] Created {approval.id} for task {task.id}, "
            f"step {step.id} (order={step.order})"
        )

        # 3. Emit event
        if events:
            events.log_approval_required(
                step_id=step.id,
                step_order=step.order,
                approval_id=approval.id,
                reason=reason,
            )

        return approval

    # ── Approve ──

    async def approve(
        self,
        db: AsyncSession,
        approval_id: str,
        approved_by: str = "system",
        reason: str = "",
        events: Optional[TaskEventLogger] = None,
    ) -> TaskApprovalModel:
        """Approve a pending request → resume the task."""
        approval = await self._get_approval(db, approval_id)
        if not approval:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Cannot approve: approval is {approval.status}, "
                f"expected PENDING"
            )

        # 1. Mark approval APPROVED
        approval.status = ApprovalStatus.APPROVED
        approval.approved_at = datetime.now(timezone.utc)
        approval.approved_by = approved_by
        if reason:
            approval.reason = reason

        # 2. Resume the task (PAUSED → EXECUTING)
        task = await self.state.get_task(db, approval.task_id)
        if task and task.status == TaskStatus.PAUSED:
            task = await self.state.transition_task_status(
                db, task, TaskStatus.RUNNING
            )

        await db.flush()

        logger.info(
            f"[APPROVAL] Approved {approval.id} by {approved_by}, "
            f"task {approval.task_id} resumed"
        )

        # 3. Emit event
        if events:
            step = await self._get_step(db, approval.step_id)
            events.log_approved(
                step_id=approval.step_id or "",
                step_order=step.order if step else 0,
                approval_id=approval.id,
                approved_by=approved_by,
            )

        return approval

    # ── Reject ──

    async def reject(
        self,
        db: AsyncSession,
        approval_id: str,
        approved_by: str = "system",
        reason: str = "",
        events: Optional[TaskEventLogger] = None,
    ) -> TaskApprovalModel:
        """Reject a pending request → cancel the task."""
        approval = await self._get_approval(db, approval_id)
        if not approval:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Cannot reject: approval is {approval.status}, "
                f"expected PENDING"
            )

        # 1. Mark approval REJECTED
        approval.status = ApprovalStatus.REJECTED
        approval.approved_at = datetime.now(timezone.utc)
        approval.approved_by = approved_by
        if reason:
            approval.reason = reason

        # 2. Cancel the task (PAUSED → CANCELLED)
        task = await self.state.get_task(db, approval.task_id)
        if task and task.status == TaskStatus.PAUSED:
            task = await self.state.transition_task_status(
                db, task, TaskStatus.CANCELLED
            )

        await db.flush()

        logger.info(
            f"[APPROVAL] Rejected {approval.id} by {approved_by}, "
            f"task {approval.task_id} cancelled"
        )

        # 3. Emit event
        if events:
            step = await self._get_step(db, approval.step_id)
            events.log_rejected(
                step_id=approval.step_id or "",
                step_order=step.order if step else 0,
                approval_id=approval.id,
                reason=reason,
            )

        return approval

    # ── Expire ──

    async def expire(
        self,
        db: AsyncSession,
        approval_id: str,
        reason: str = "Approval request expired",
    ) -> TaskApprovalModel:
        """Expire a pending request without modifying task state."""
        approval = await self._get_approval(db, approval_id)
        if not approval:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.status != ApprovalStatus.PENDING:
            logger.warning(
                f"[APPROVAL] Cannot expire {approval_id}: "
                f"status is {approval.status}"
            )
            return approval

        approval.status = ApprovalStatus.EXPIRED
        approval.approved_at = datetime.now(timezone.utc)
        approval.reason = reason

        await db.flush()

        logger.info(f"[APPROVAL] Expired {approval.id}: {reason}")
        return approval

    # ── Queries ──

    async def get_approval(
        self, db: AsyncSession, approval_id: str
    ) -> Optional[TaskApprovalModel]:
        return await self._get_approval(db, approval_id)

    async def list_approvals(
        self,
        db: AsyncSession,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[TaskApprovalModel]:
        query = select(TaskApprovalModel)
        if task_id:
            query = query.where(TaskApprovalModel.task_id == task_id)
        if status:
            query = query.where(TaskApprovalModel.status == status)
        query = query.order_by(TaskApprovalModel.requested_at.desc())
        query = query.limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_pending_approval_for_step(
        self, db: AsyncSession, step_id: str
    ) -> Optional[TaskApprovalModel]:
        """Get the PENDING approval for a specific step, if any."""
        result = await db.execute(
            select(TaskApprovalModel)
            .where(TaskApprovalModel.step_id == step_id)
            .where(TaskApprovalModel.status == ApprovalStatus.PENDING)
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Helpers ──

    async def _get_approval(
        self, db: AsyncSession, approval_id: str
    ) -> Optional[TaskApprovalModel]:
        result = await db.execute(
            select(TaskApprovalModel).where(TaskApprovalModel.id == approval_id)
        )
        return result.scalar_one_or_none()

    async def _get_step(
        self, db: AsyncSession, step_id: Optional[str]
    ) -> Optional[TaskStepModel]:
        if not step_id:
            return None
        result = await db.execute(
            select(TaskStepModel).where(TaskStepModel.id == step_id)
        )
        return result.scalar_one_or_none()
