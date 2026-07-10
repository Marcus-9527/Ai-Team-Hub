"""
task_plan_review.py — Planner Review Gate (Phase D)

Provides the review gate between TaskPlan generation and application.

Responsibilities:
  - request_review(): Create a PENDING review for an ACTIVE plan
  - approve_review(): Mark a review as APPROVED
  - reject_review():  Mark a review as REJECTED
  - check_review_status(): Return review status for a plan
  - require_approval(): Raise if plan is not APPROVED (Review Gate)

Flow:
  Planner → TaskPlan(DRAFT/ACTIVE) → request_review → approve → apply_plan

Constraints:
  ❌ No Planner modification
  ❌ No TaskExecutor modification
  ✅ Isolated review layer with minimal coupling
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskPlanReviewModel,
    TaskPlanModel,
    PlanStatus,
    PlanReviewStatus,
)

logger = logging.getLogger("task.plan.review")


class ReviewError(Exception):
    """Base exception for review operations."""
    pass


class ReviewNotFoundError(ReviewError):
    """Raised when no review exists for a plan."""
    pass


class ReviewNotPendingError(ReviewError):
    """Raised when trying to approve/reject a non-PENDING review."""
    pass


class ReviewGateBlockedError(ReviewError):
    """Raised when a plan is not yet APPROVED (Review Gate)."""
    pass


# ═══════════════════════════════════════════════════════════════
# TaskPlanReviewService
# ═══════════════════════════════════════════════════════════════


class TaskPlanReviewService:
    """Manages plan-level review lifecycle."""

    # ── Request Review ──

    async def request_review(
        self,
        db: AsyncSession,
        plan_id: str,
        *,
        reviewer: str = "",
        comment: str = "",
    ) -> TaskPlanReviewModel:
        """
        Create a PENDING review for the given plan.

        If a review already exists for this plan, it is returned as-is
        (no duplicate creation — idempotent).

        Args:
            db: Database session.
            plan_id: The TaskPlanModel ID to review.
            reviewer: Who requested / will perform the review.
            comment: Initial comment (e.g. review instructions).

        Returns:
            The (existing or new) TaskPlanReviewModel.

        Raises:
            ValueError: If the plan does not exist or is not ACTIVE.
        """
        # Check plan exists and is ACTIVE
        plan = await self._get_plan(db, plan_id)
        if plan is None:
            raise ValueError(f"Plan not found: {plan_id}")
        if plan.status != PlanStatus.ACTIVE:
            raise ValueError(
                f"Plan {plan_id} status is {plan.status}, "
                f"only ACTIVE plans can be reviewed"
            )

        # Check if review already exists (idempotent)
        existing = await self.get_review(db, plan_id)
        if existing:
            logger.info(f"[REVIEW] Review already exists for plan {plan_id}, reusing")
            return existing

        review = TaskPlanReviewModel(
            plan_id=plan_id,
            status=PlanReviewStatus.PENDING,
            reviewer=reviewer,
            comment=comment,
        )
        db.add(review)
        await db.flush()

        logger.info(
            f"[REVIEW] Created review {review.id} for plan {plan_id} "
            f"(reviewer={reviewer})"
        )
        return review

    # ── Approve ──

    async def approve_review(
        self,
        db: AsyncSession,
        plan_id: str,
        *,
        reviewer: str = "",
        comment: str = "",
    ) -> TaskPlanReviewModel:
        """
        Approve a PENDING review.

        Args:
            db: Database session.
            plan_id: The plan ID to approve.
            reviewer: Who approved.
            comment: Optional approval note.

        Returns:
            The updated TaskPlanReviewModel.

        Raises:
            ReviewNotFoundError: If no review exists for the plan.
            ReviewNotPendingError: If review is not in PENDING state.
        """
        review = await self.get_review(db, plan_id)
        if review is None:
            raise ReviewNotFoundError(f"No review found for plan {plan_id}")

        if review.status != PlanReviewStatus.PENDING:
            raise ReviewNotPendingError(
                f"Review {review.id} is {review.status}, cannot approve"
            )

        review.status = PlanReviewStatus.APPROVED
        review.reviewer = reviewer or review.reviewer
        if comment:
            review.comment = comment
        db.add(review)
        await db.flush()

        logger.info(f"[REVIEW] Approved review {review.id} for plan {plan_id}")

        # ── Dispatch PLAN_APPROVED to TaskHookRegistry (V3.1 Phase A) ──
        await self._dispatch_plan_approved(db, plan_id, review)

        return review

    async def _dispatch_plan_approved(
        self,
        db: AsyncSession,
        plan_id: str,
        review: TaskPlanReviewModel,
    ) -> None:
        """Fire PLAN_APPROVED event to the task hook registry."""
        try:
            from backend.services.task.task_hooks import (
                TaskLifecycleEvent,
                TaskHookContext,
                get_task_hook_registry,
            )

            # Load plan to get summary + task_id
            plan = await self._get_plan(db, plan_id)
            if plan is None:
                logger.debug(f"[REVIEW] Cannot dispatch PLAN_APPROVED: plan {plan_id} not found")
                return

            registry = get_task_hook_registry()
            ctx = TaskHookContext(
                task_id=plan.task_id,
                plan_id=plan_id,
                plan_summary=plan.title or plan.description or "",
                extra={
                    "review_id": review.id,
                    "reviewer": review.reviewer or "",
                    "comment": review.comment or "",
                },
            )
            await registry.dispatch(TaskLifecycleEvent.PLAN_APPROVED, ctx)

        except Exception as e:
            logger.debug(f"[REVIEW] PLAN_APPROVED dispatch failed (non-fatal): {e}")

    # ── Reject ──

    async def reject_review(
        self,
        db: AsyncSession,
        plan_id: str,
        *,
        reviewer: str = "",
        comment: str = "",
    ) -> TaskPlanReviewModel:
        """
        Reject a PENDING review.

        Args:
            db: Database session.
            plan_id: The plan ID to reject.
            reviewer: Who rejected.
            comment: Rejection reason.

        Returns:
            The updated TaskPlanReviewModel.

        Raises:
            ReviewNotFoundError: If no review exists for the plan.
            ReviewNotPendingError: If review is not in PENDING state.
        """
        review = await self.get_review(db, plan_id)
        if review is None:
            raise ReviewNotFoundError(f"No review found for plan {plan_id}")

        if review.status != PlanReviewStatus.PENDING:
            raise ReviewNotPendingError(
                f"Review {review.id} is {review.status}, cannot reject"
            )

        review.status = PlanReviewStatus.REJECTED
        review.reviewer = reviewer or review.reviewer
        review.comment = comment
        db.add(review)
        await db.flush()

        logger.info(f"[REVIEW] Rejected review {review.id} for plan {plan_id}")
        return review

    # ── Check Status ──

    async def check_review_status(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> Optional[str]:
        """
        Return the current review status for a plan, or None if no review exists.

        Args:
            db: Database session.
            plan_id: The plan ID.

        Returns:
            PlanReviewStatus value (PENDING | APPROVED | REJECTED) or None.
        """
        review = await self.get_review(db, plan_id)
        return review.status if review else None

    # ── Review Gate ──

    async def require_approval(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> None:
        """
        Review Gate: raise if the plan is not APPROVED.

        Called by TaskPlanService before converting plan to steps.

        Args:
            db: Database session.
            plan_id: The plan ID to check.

        Raises:
            ReviewGateBlockedError: If no review exists or review is not APPROVED.
        """
        review = await self.get_review(db, plan_id)
        if review is None:
            raise ReviewGateBlockedError(
                f"Plan {plan_id} has not been reviewed — "
                f"submit a review before applying"
            )
        if review.status == PlanReviewStatus.REJECTED:
            raise ReviewGateBlockedError(
                f"Plan {plan_id} review was REJECTED: {review.comment}"
            )
        if review.status == PlanReviewStatus.PENDING:
            raise ReviewGateBlockedError(
                f"Plan {plan_id} review is PENDING — "
                f"approve the review before applying"
            )
        # APPROVED → pass

    # ── Internal ──

    async def get_review(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> Optional[TaskPlanReviewModel]:
        """Get the review for a plan, or None."""
        result = await db.execute(
            select(TaskPlanReviewModel).where(
                TaskPlanReviewModel.plan_id == plan_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _get_plan(
        db: AsyncSession,
        plan_id: str,
    ) -> Optional[TaskPlanModel]:
        """Get a plan by ID."""
        result = await db.execute(
            select(TaskPlanModel).where(TaskPlanModel.id == plan_id)
        )
        return result.scalar_one_or_none()
