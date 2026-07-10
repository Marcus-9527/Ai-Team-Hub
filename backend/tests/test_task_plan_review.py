"""
test_task_plan_review.py — Phase D: Planner Review Layer tests.

Coverage:
  1. Request review — creates PENDING review linked to plan
  2. Approve review — changes status to APPROVED
  3. Reject review — changes status to REJECTED
  4. Idempotent request — re-requesting returns existing review
  5. Non-ACTIVE plan rejected — cannot review non-ACTIVE plans
  6. Cannot approve already approved — raises ReviewNotPendingError
  7. Cannot reject already rejected — raises ReviewNotPendingError
  8. Review gate blocks unapproved plan — convert raises ReviewGateBlockedError
  9. Review gate allows approved plan — convert succeeds after approve
  10. Review gate blocks rejected plan — convert raises ReviewGateBlockedError
"""

import uuid
import pytest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskPlanModel,
    PlanStatus,
    PlanReviewStatus,
    TaskStepStatus,
)
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_plan_service import TaskPlanService
from backend.services.task.task_plan_review import (
    TaskPlanReviewService,
    ReviewNotFoundError,
    ReviewNotPendingError,
    ReviewGateBlockedError,
)

pytestmark = pytest.mark.asyncio

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def state_mgr():
    return TaskStateManager()


@pytest.fixture
def plan_svc():
    return TaskPlanService()


@pytest.fixture
def review_svc():
    return TaskPlanReviewService()


@pytest.fixture
def _unique_title():
    return f"review-test-{uuid.uuid4().hex[:8]}"


async def _create_task(db_session, state_mgr, title: str) -> TaskModel:
    """Helper: create a task in CREATED state."""
    task = await state_mgr.create_task(
        db_session,
        title=title,
        description=f"Review test: {title}",
        channel_id="ch_review_test",
        created_by="test",
    )
    await db_session.commit()
    await db_session.refresh(task)
    return task


async def _create_and_save_plan(
    db_session, state_mgr, plan_svc, title: str,
) -> tuple[TaskModel, TaskPlanModel]:
    """Helper: create task + save plan, return (task, plan)."""
    task = await _create_task(db_session, state_mgr, title)
    plan = await plan_svc.save_plan(
        db_session,
        task_id=task.id,
        title=title,
        steps=[
            {"order": 1, "teammate_id": "t_a", "objective": "Step 1",
             "risk_level": "LOW", "confidence": 0.9},
        ],
    )
    await db_session.commit()
    await db_session.refresh(plan)
    return task, plan


# ═══════════════════════════════════════════════════════════════
# 1. Request Review
# ═══════════════════════════════════════════════════════════════


class TestRequestReview:
    async def test_request_creates_pending(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Request review creates a PENDING review entry."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )

        review = await review_svc.request_review(
            db_session, plan.id,
            reviewer="reviewer_a",
            comment="Please review this plan",
        )
        await db_session.commit()
        await db_session.refresh(review)

        assert review.id is not None
        assert review.plan_id == plan.id
        assert review.status == PlanReviewStatus.PENDING
        assert review.reviewer == "reviewer_a"
        assert review.comment == "Please review this plan"

    async def test_request_idempotent(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Requesting review twice returns the same review."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )

        review1 = await review_svc.request_review(
            db_session, plan.id, reviewer="r1",
        )
        await db_session.commit()

        review2 = await review_svc.request_review(
            db_session, plan.id, reviewer="r2",
        )
        await db_session.commit()

        assert review1.id == review2.id
        assert review2.reviewer == "r1"  # unchanged (first request)

    async def test_non_active_plan_rejected(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Non-ACTIVE plan raises ValueError."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        plan = await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="To Supersede",
            steps=[{"order": 1, "teammate_id": "t", "objective": "Old"}],
        )
        await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="New One",
            steps=[{"order": 1, "teammate_id": "t", "objective": "New"}],
        )
        await db_session.commit()

        # Plan is now SUPERSEDED
        with pytest.raises(ValueError, match="only ACTIVE plans"):
            await review_svc.request_review(db_session, plan.id)

    async def test_nonexistent_plan(
        self, db_session, review_svc,
    ):
        """Non-existent plan raises ValueError."""
        with pytest.raises(ValueError, match="Plan not found"):
            await review_svc.request_review(
                db_session, "no-such-plan",
                reviewer="tester",
            )


# ═══════════════════════════════════════════════════════════════
# 2. Approve Review
# ═══════════════════════════════════════════════════════════════


class TestApproveReview:
    async def test_approve_success(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Approve changes status from PENDING to APPROVED."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await db_session.commit()

        review = await review_svc.approve_review(
            db_session, plan.id,
            reviewer="approver_a",
            comment="Looks good, proceed",
        )
        await db_session.commit()

        assert review.status == PlanReviewStatus.APPROVED
        assert review.reviewer == "approver_a"
        assert review.comment == "Looks good, proceed"

    async def test_approve_no_review(
        self, db_session, review_svc,
    ):
        """Approve without existing review raises ReviewNotFoundError."""
        with pytest.raises(ReviewNotFoundError):
            await review_svc.approve_review(
                db_session, "no-such-plan",
                reviewer="approver",
            )

    async def test_approve_already_approved(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Approve an already-approved review raises ReviewNotPendingError."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await review_svc.approve_review(db_session, plan.id, reviewer="r")
        await db_session.commit()

        with pytest.raises(ReviewNotPendingError, match="cannot approve"):
            await review_svc.approve_review(db_session, plan.id)

    async def test_approve_rejected(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Approve a rejected review raises ReviewNotPendingError."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await review_svc.reject_review(
            db_session, plan.id, reviewer="r", comment="Nope",
        )
        await db_session.commit()

        with pytest.raises(ReviewNotPendingError, match="cannot approve"):
            await review_svc.approve_review(db_session, plan.id)


# ═══════════════════════════════════════════════════════════════
# 3. Reject Review
# ═══════════════════════════════════════════════════════════════


class TestRejectReview:
    async def test_reject_success(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Reject changes status from PENDING to REJECTED."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await db_session.commit()

        review = await review_svc.reject_review(
            db_session, plan.id,
            reviewer="rejector_a",
            comment="Needs more detail",
        )
        await db_session.commit()

        assert review.status == PlanReviewStatus.REJECTED
        assert review.reviewer == "rejector_a"
        assert review.comment == "Needs more detail"

    async def test_reject_no_review(
        self, db_session, review_svc,
    ):
        """Reject without existing review raises ReviewNotFoundError."""
        with pytest.raises(ReviewNotFoundError):
            await review_svc.reject_review(
                db_session, "no-such-plan",
                reviewer="rejector",
            )

    async def test_reject_already_rejected(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Reject an already-rejected review raises ReviewNotPendingError."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await review_svc.reject_review(db_session, plan.id, reviewer="r")
        await db_session.commit()

        with pytest.raises(ReviewNotPendingError, match="cannot reject"):
            await review_svc.reject_review(db_session, plan.id)


# ═══════════════════════════════════════════════════════════════
# 4. Check Review Status
# ═══════════════════════════════════════════════════════════════


class TestCheckReviewStatus:
    async def test_status_none(
        self, db_session, review_svc,
    ):
        """No review returns None."""
        status = await review_svc.check_review_status(
            db_session, "no-such-plan"
        )
        assert status is None

    async def test_status_pending(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """After request, status is PENDING."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id)
        await db_session.commit()

        status = await review_svc.check_review_status(db_session, plan.id)
        assert status == PlanReviewStatus.PENDING

    async def test_status_approved(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """After approve, status is APPROVED."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id)
        await review_svc.approve_review(db_session, plan.id, reviewer="r")
        await db_session.commit()

        status = await review_svc.check_review_status(db_session, plan.id)
        assert status == PlanReviewStatus.APPROVED

    async def test_status_rejected(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """After reject, status is REJECTED."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id)
        await review_svc.reject_review(
            db_session, plan.id, reviewer="r", comment="no",
        )
        await db_session.commit()

        status = await review_svc.check_review_status(db_session, plan.id)
        assert status == PlanReviewStatus.REJECTED


# ═══════════════════════════════════════════════════════════════
# 5. Review Gate (integration with TaskPlanService)
# ═══════════════════════════════════════════════════════════════


class TestReviewGate:
    async def test_convert_without_review_blocked(
        self, db_session, state_mgr, plan_svc, _unique_title,
    ):
        """Convert plan without review raises ReviewGateBlockedError."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )

        with pytest.raises(ReviewGateBlockedError, match="not been reviewed"):
            await plan_svc.convert_plan_to_steps(db_session, task.id)

    async def test_convert_with_pending_review_blocked(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Convert plan with PENDING review raises ReviewGateBlockedError."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await db_session.commit()

        with pytest.raises(ReviewGateBlockedError, match="PENDING"):
            await plan_svc.convert_plan_to_steps(db_session, task.id)

    async def test_convert_with_rejected_review_blocked(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Convert plan with REJECTED review raises ReviewGateBlockedError."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await review_svc.reject_review(
            db_session, plan.id, reviewer="r", comment="Not ready",
        )
        await db_session.commit()

        with pytest.raises(ReviewGateBlockedError, match="REJECTED"):
            await plan_svc.convert_plan_to_steps(db_session, task.id)

    async def test_convert_after_approve_succeeds(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Convert plan after approve creates TaskSteps successfully."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        await review_svc.request_review(db_session, plan.id, reviewer="r")
        await review_svc.approve_review(
            db_session, plan.id, reviewer="r", comment="Approved",
        )
        await db_session.commit()

        steps = await plan_svc.convert_plan_to_steps(db_session, task.id)
        await db_session.commit()

        assert len(steps) == 1
        assert steps[0].source == "PLANNER"
        assert steps[0].status == TaskStepStatus.PENDING
        assert steps[0].task_id == task.id

        # Plan should be APPLIED now
        result = await db_session.execute(
            select(TaskPlanModel).where(TaskPlanModel.id == plan.id)
        )
        saved_plan = result.scalar_one_or_none()
        assert saved_plan.status == PlanStatus.APPLIED

    async def test_review_to_dict(
        self, db_session, state_mgr, plan_svc, review_svc, _unique_title,
    ):
        """Review to_dict() returns expected fields."""
        task, plan = await _create_and_save_plan(
            db_session, state_mgr, plan_svc, _unique_title,
        )
        review = await review_svc.request_review(
            db_session, plan.id, reviewer="r", comment="Please check",
        )
        await db_session.commit()
        await db_session.refresh(review)

        d = review.to_dict()
        assert d["id"] == review.id
        assert d["plan_id"] == plan.id
        assert d["status"] == PlanReviewStatus.PENDING
        assert d["reviewer"] == "r"
        assert d["comment"] == "Please check"
        assert "created_at" in d
