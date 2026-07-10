"""
test_task_plan_service.py — Phase C: TaskPlanService tests.

Coverage:
  1. Save plan — creates TaskPlanModel with correct fields
  2. Get plan — retrieves ACTIVE plan
  3. Get plan by ID — retrieves by plan_id
  4. Supersede — re-saving supersedes old ACTIVE plan
  5. Convert plan → steps — creates TaskStepModel with source=PLANNER
  6. Empty plan — raises EmptyPlanError
  7. No active plan — raises NoActivePlanError
  8. Policy block — HIGH risk plan blocked
  9. Plan serialization — to_dict returns proper fields
"""

import json
import uuid
import pytest
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskPlanModel,
    PlanStatus,
    TaskStatus,
    TaskStepStatus,
)
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_plan_service import (
    TaskPlanService,
    NoActivePlanError,
    EmptyPlanError,
    PolicyBlockedError,
    PlanConversionError,
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
def _unique_title():
    return f"plan-test-{uuid.uuid4().hex[:8]}"


async def _create_task(db_session, state_mgr, title: str) -> TaskModel:
    """Helper: create a task in CREATED state."""
    task = await state_mgr.create_task(
        db_session,
        title=title,
        description=f"Integration test: {title}",
        channel_id="ch_plan_test",
        created_by="test",
    )
    await db_session.commit()
    await db_session.refresh(task)
    return task


# ═══════════════════════════════════════════════════════════════
# 1. Save Plan
# ═══════════════════════════════════════════════════════════════


class TestSavePlan:
    async def test_save_minimal(self, db_session, state_mgr, plan_svc, _unique_title):
        """Save a plan with minimal fields."""
        task = await _create_task(db_session, state_mgr, _unique_title)

        plan = await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="Test Plan",
            steps=[{"order": 1, "teammate_id": "teammate_a", "objective": "Step 1"}],
        )
        await db_session.commit()
        await db_session.refresh(plan)

        assert plan.id is not None
        assert plan.task_id == task.id
        assert plan.title == "Test Plan"
        assert plan.status == PlanStatus.ACTIVE
        assert plan.risk_level == "LOW"
        assert plan.confidence == "0.0"
        assert plan.estimated_cost == "0.0"

        steps = json.loads(plan.steps_json)
        assert len(steps) == 1
        assert steps[0]["order"] == 1
        assert steps[0]["objective"] == "Step 1"

    async def test_save_full(self, db_session, state_mgr, plan_svc, _unique_title):
        """Save a plan with all fields."""
        task = await _create_task(db_session, state_mgr, _unique_title)

        steps = [
            {"order": 1, "teammate_id": "teammate_b", "objective": "Research",
             "risk_level": "LOW", "confidence": 0.95},
            {"order": 2, "teammate_id": "teammate_a", "objective": "Implement",
             "risk_level": "MEDIUM", "confidence": 0.8},
        ]
        plan = await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="Full Plan",
            description="Complete plan with all metadata",
            steps=steps,
            confidence=0.85,
            rationale="User wants a feature",
            risk_level="LOW",
            estimated_cost=5000,
        )
        await db_session.commit()
        await db_session.refresh(plan)

        assert plan.title == "Full Plan"
        assert plan.description == "Complete plan with all metadata"
        assert plan.confidence == "0.85"
        assert plan.rationale == "User wants a feature"
        assert plan.estimated_cost == "5000"

        parsed = json.loads(plan.steps_json)
        assert len(parsed) == 2

    async def test_save_empty_steps(self, db_session, state_mgr, plan_svc, _unique_title):
        """Save a plan with no steps (allowed at save time)."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        plan = await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="Empty Plan",
            steps=[],
        )
        await db_session.commit()
        assert json.loads(plan.steps_json) == []


# ═══════════════════════════════════════════════════════════════
# 2. Get Plan
# ═══════════════════════════════════════════════════════════════


class TestGetPlan:
    async def test_get_active(self, db_session, state_mgr, plan_svc, _unique_title):
        """Get the ACTIVE plan for a task."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        await plan_svc.save_plan(
            db_session, task_id=task.id, title="Get Me",
            steps=[{"order": 1, "teammate_id": "t", "objective": "Do"}],
        )
        await db_session.commit()

        plan = await plan_svc.get_plan(db_session, task.id)
        assert plan is not None
        assert plan.title == "Get Me"
        assert plan.status == PlanStatus.ACTIVE

    async def test_get_nonexistent(self, db_session, plan_svc):
        """Get plan for a task with no plan returns None."""
        plan = await plan_svc.get_plan(db_session, "no-such-task")
        assert plan is None

    async def test_get_plan_by_id(self, db_session, state_mgr, plan_svc, _unique_title):
        """Get plan by plan_id."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        saved = await plan_svc.save_plan(
            db_session, task_id=task.id, title="By ID",
            steps=[{"order": 1, "teammate_id": "t", "objective": "Go"}],
        )
        await db_session.commit()

        plan = await plan_svc.get_plan_by_id(db_session, saved.id)
        assert plan is not None
        assert plan.id == saved.id

    async def test_get_plan_by_id_not_found(self, db_session, plan_svc):
        """Non-existent plan ID returns None."""
        plan = await plan_svc.get_plan_by_id(db_session, "no-such-id")
        assert plan is None


# ═══════════════════════════════════════════════════════════════
# 3. Supersede
# ═══════════════════════════════════════════════════════════════


class TestSupersede:
    async def test_save_supersedes_old(self, db_session, state_mgr, plan_svc, _unique_title):
        """Saving a new plan supersedes the old ACTIVE plan."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        await plan_svc.save_plan(
            db_session, task_id=task.id, title="Old",
            steps=[{"order": 1, "teammate_id": "t", "objective": "Old step"}],
        )
        await plan_svc.save_plan(
            db_session, task_id=task.id, title="New",
            steps=[{"order": 1, "teammate_id": "t", "objective": "New step"}],
        )
        await db_session.commit()

        active = await plan_svc.get_plan(db_session, task.id)
        assert active is not None
        assert active.title == "New"
        assert active.status == PlanStatus.ACTIVE

        # Old plan should be SUPERSEDED
        result = await db_session.execute(
            select(TaskPlanModel)
            .where(TaskPlanModel.task_id == task.id)
            .where(TaskPlanModel.title == "Old")
        )
        old = result.scalar_one_or_none()
        assert old is not None
        assert old.status == PlanStatus.SUPERSEDED


# ═══════════════════════════════════════════════════════════════
# 4. Convert Plan → Steps
# ═══════════════════════════════════════════════════════════════


class TestConvertPlanToSteps:
    async def test_convert_creates_steps_with_source_planner(
        self, db_session, state_mgr, plan_svc, _unique_title,
    ):
        """Convert plan creates TaskStepModel records with source=PLANNER."""
        task = await _create_task(db_session, state_mgr, _unique_title)

        await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="Convert Test",
            steps=[
                {"order": 1, "teammate_id": "teammate_a",
                 "objective": "Research options",
                 "risk_level": "LOW", "confidence": 0.9},
                {"order": 2, "teammate_id": "teammate_b",
                 "objective": "Implement solution",
                 "risk_level": "MEDIUM", "confidence": 0.8},
                {"order": 3, "teammate_id": "teammate_c",
                 "objective": "Review and test",
                 "risk_level": "LOW", "confidence": 0.95},
            ],
        )
        await db_session.commit()

        # Phase D: must request review and approve before convert
        from backend.services.task.task_plan_review import TaskPlanReviewService
        review_svc = TaskPlanReviewService()
        active_plan = await plan_svc.get_plan(db_session, task.id)
        await review_svc.request_review(db_session, active_plan.id, reviewer="tester")
        await review_svc.approve_review(db_session, active_plan.id, reviewer="tester")
        await db_session.commit()

        # Convert
        steps = await plan_svc.convert_plan_to_steps(db_session, task.id)
        await db_session.commit()

        assert len(steps) == 3
        for s in steps:
            assert s.source == "PLANNER"
            assert s.task_id == task.id
            assert s.status == TaskStepStatus.PENDING

        # Check order
        assert steps[0].order == 1
        assert steps[0].objective == "Research options"
        assert steps[1].order == 2
        assert steps[1].objective == "Implement solution"
        assert steps[2].order == 3
        assert steps[2].objective == "Review and test"

        # Plan should be APPLIED
        plan = await plan_svc.get_plan(db_session, task.id)
        assert plan is None  # No longer ACTIVE

        # Find by other status
        result = await db_session.execute(
            select(TaskPlanModel)
            .where(TaskPlanModel.task_id == task.id)
        )
        saved_plan = result.scalar_one_or_none()
        assert saved_plan.status == PlanStatus.APPLIED

    async def test_no_active_plan(self, db_session, state_mgr, plan_svc, _unique_title):
        """No active plan raises NoActivePlanError."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        # Don't save a plan

        with pytest.raises(NoActivePlanError):
            await plan_svc.convert_plan_to_steps(db_session, task.id)

    async def test_empty_plan(self, db_session, state_mgr, plan_svc, _unique_title):
        """Plan with no steps raises EmptyPlanError."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="Empty Plan",
            steps=[],
        )
        await db_session.commit()

        # Phase D: request review first (gate checks order: review → empty)
        from backend.services.task.task_plan_review import TaskPlanReviewService
        review_svc = TaskPlanReviewService()
        active_plan = await plan_svc.get_plan(db_session, task.id)
        await review_svc.request_review(db_session, active_plan.id, reviewer="tester")
        await review_svc.approve_review(db_session, active_plan.id, reviewer="tester")
        await db_session.commit()

        with pytest.raises(EmptyPlanError):
            await plan_svc.convert_plan_to_steps(db_session, task.id)

    async def test_policy_blocks_high_risk(
        self, db_session, state_mgr, plan_svc, _unique_title,
    ):
        """Plan with HIGH risk_level is blocked by policy."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="High Risk Plan",
            risk_level="HIGH",
            steps=[{"order": 1, "teammate_id": "t", "objective": "Risky step"}],
        )
        await db_session.commit()

        # Phase D: must review first (gate checks before policy)
        from backend.services.task.task_plan_review import TaskPlanReviewService
        review_svc = TaskPlanReviewService()
        active_plan = await plan_svc.get_plan(db_session, task.id)
        await review_svc.request_review(db_session, active_plan.id, reviewer="tester")
        await review_svc.approve_review(db_session, active_plan.id, reviewer="tester")
        await db_session.commit()

        with pytest.raises(PolicyBlockedError, match="risk_level=HIGH"):
            await plan_svc.convert_plan_to_steps(db_session, task.id)

    async def test_source_defaults_to_manual_for_manual_steps(
        self, db_session, state_mgr, _unique_title,
    ):
        """Steps created via state.create_step have default source=MANUAL."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        step = await state_mgr.create_step(
            db_session,
            task_id=task.id,
            order=1,
            objective="Manual step",
            teammate_id="teammate_a",
        )
        await db_session.commit()
        await db_session.refresh(step)

        assert step.source == "MANUAL"

    async def test_plan_to_dict(self, db_session, state_mgr, plan_svc, _unique_title):
        """Plan to_dict() returns expected fields."""
        task = await _create_task(db_session, state_mgr, _unique_title)
        plan = await plan_svc.save_plan(
            db_session,
            task_id=task.id,
            title="Dict Test",
            steps=[{"order": 1, "teammate_id": "t", "objective": "Step 1"}],
        )
        await db_session.commit()
        await db_session.refresh(plan)

        d = plan.to_dict()
        assert d["id"] == plan.id
        assert d["task_id"] == task.id
        assert d["title"] == "Dict Test"
        assert d["status"] == PlanStatus.ACTIVE
        assert d["steps_count"] == 1
        assert "created_at" in d
