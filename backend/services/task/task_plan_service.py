"""
task_plan_service.py — Planner → Task Integration Service (Phase C)

Bridges the Planner output (TaskPlan dataclass) to the Task execution layer.

Responsibilities:
  - save_plan(): Persist a Planner-generated TaskPlan as TaskPlanModel
  - get_plan(): Retrieve the active plan for a task
  - convert_plan_to_steps(): Convert a plan's step proposals into TaskStepModel
    records with source=PLANNER, after evaluating against TaskPolicy.

Flow:
  TaskPlan → save_plan → Policy evaluate → convert_plan_to_steps → Executor

Constraints:
  ❌ No MAEOS calls (plan is already generated before save)
  ❌ No TaskExecutor modification
  ✅ Uses existing TaskPolicyService for evaluation
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskPlanModel,
    TaskStepModel,
    TaskStepStatus,
    PlanStatus,
    RiskLevel,
)
from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_policy import TaskPolicyService
from backend.services.task.task_plan_review import (
    TaskPlanReviewService,
    ReviewGateBlockedError,
)

logger = logging.getLogger("task.plan.service")


class PlanConversionError(Exception):
    """Raised when plan-to-step conversion fails."""
    pass


class EmptyPlanError(PlanConversionError):
    """Raised when plan has no steps."""
    pass


class PolicyBlockedError(PlanConversionError):
    """Raised when policy blocks plan conversion."""
    pass


class NoActivePlanError(PlanConversionError):
    """Raised when no ACTIVE plan exists for the task."""
    pass


# ═══════════════════════════════════════════════════════════════
# TaskPlanService
# ═══════════════════════════════════════════════════════════════


class TaskPlanService:
    """Persist, retrieve, and convert TaskPlans to TaskSteps."""

    def __init__(self):
        self.state = TaskStateManager()
        self.policy = TaskPolicyService()
        self.review = TaskPlanReviewService()

    # ── Save ──

    async def save_plan(
        self,
        db: AsyncSession,
        task_id: str,
        *,
        title: str,
        description: str = "",
        steps: list[dict] | None = None,
        confidence: float = 0.0,
        rationale: str = "",
        risk_level: str = RiskLevel.LOW,
        estimated_cost: float = 0.0,
    ) -> TaskPlanModel:
        """
        Save a TaskPlan to the database.

        If an ACTIVE plan already exists for this task, it is superseded.
        Accepts plan data as parameters (typically deserialised from
        a TaskPlan or TaskStepProposal dataclass).

        Args:
            db: Database session.
            task_id: The owning task ID.
            title: Plan title.
            description: Plan description / summary.
            steps: List of step proposal dicts (each must have at least
                   'order', 'teammate_id', 'objective').
            confidence: Planner confidence score (0.0–1.0).
            rationale: Planning rationale.
            risk_level: Overall risk level.
            estimated_cost: Estimated total cost.

        Returns:
            The persisted TaskPlanModel.
        """
        # Supersede any existing ACTIVE plan
        existing = await self._find_active_plan(db, task_id)
        if existing:
            existing.status = PlanStatus.SUPERSEDED
            db.add(existing)
            logger.info(f"[PLAN] Superseded existing plan {existing.id} for task {task_id}")

        plan = TaskPlanModel(
            task_id=task_id,
            title=title,
            description=description,
            confidence=str(confidence),
            rationale=rationale,
            risk_level=risk_level,
            estimated_cost=str(estimated_cost),
            steps_json=json.dumps(steps or [], ensure_ascii=False),
            status=PlanStatus.ACTIVE,
        )
        db.add(plan)
        await db.flush()

        logger.info(
            f"[PLAN] Saved plan {plan.id} for task {task_id}: "
            f"{len(steps or [])} steps, risk={risk_level}, conf={confidence}"
        )
        return plan

    # ── Get ──

    async def get_plan(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> Optional[TaskPlanModel]:
        """Get the ACTIVE plan for a task, or None."""
        return await self._find_active_plan(db, task_id)

    async def get_plan_by_id(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> Optional[TaskPlanModel]:
        """Get a plan by its ID."""
        result = await db.execute(
            select(TaskPlanModel).where(TaskPlanModel.id == plan_id)
        )
        return result.scalar_one_or_none()

    # ── Convert Plan → Steps ──

    async def convert_plan_to_steps(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> list[TaskStepModel]:
        """
        Convert the ACTIVE plan for a task into TaskStepModel records.

        Flow:
          1. Find ACTIVE plan
          2. Parse step proposals from JSON
          3. Evaluate each step against policy
          4. Create TaskStepModel records with source=PLANNER
          5. Mark plan as APPLIED

        Args:
            db: Database session.
            task_id: The owning task ID.

        Returns:
            List of created TaskStepModel records.

        Raises:
            NoActivePlanError: If no ACTIVE plan exists.
            EmptyPlanError: If plan has zero steps.
            PolicyBlockedError: If policy blocks conversion.
        """
        plan = await self._find_active_plan(db, task_id)
        if plan is None:
            raise NoActivePlanError(
                f"No ACTIVE plan found for task {task_id}"
            )

        # Phase D: Review Gate — plan must be APPROVED before conversion
        await self.review.require_approval(db, plan.id)

        steps_data = self._parse_steps(plan.steps_json)
        if not steps_data:
            raise EmptyPlanError(
                f"Plan {plan.id} has no steps"
            )

        task = await self.state.get_task(db, task_id)
        if task is None:
            raise PlanConversionError(f"Task not found: {task_id}")

        # Policy evaluation (plan-level)
        policy_result = await self.policy.evaluate_cost(
            db, task_id,
            estimated_cost=float(plan.estimated_cost or "0"),
        )
        if not policy_result.allowed:
            raise PolicyBlockedError(policy_result.blocked_reason)

        # Policy: if plan has HIGH risk level → block
        if plan.risk_level == RiskLevel.HIGH:
            raise PolicyBlockedError(
                f"Plan risk_level=HIGH blocks conversion for task {task_id}"
            )

        # Create steps
        created_steps: list[TaskStepModel] = []
        for i, step_data in enumerate(steps_data):
            order = int(step_data.get("order", i + 1))
            teammate_id = str(step_data.get("teammate_id", ""))
            objective = str(step_data.get("objective", ""))

            step = await self.state.create_step(
                db,
                task_id=task_id,
                order=order,
                objective=objective,
                teammate_id=teammate_id,
                input_context=str(step_data.get("input_context_hint", "")),
            )
            # Override default source (create_step uses default "MANUAL")
            step.source = "PLANNER"
            db.add(step)
            logger.debug(
                f"[PLAN] Created step {step.id} (order={order}) "
                f"from plan {plan.id}"
            )

            created_steps.append(step)

        # Mark plan as APPLIED
        plan.status = PlanStatus.APPLIED
        db.add(plan)

        await db.flush()

        logger.info(
            f"[PLAN] Converted plan {plan.id} → {len(created_steps)} steps"
        )
        return created_steps

    # ── Internal ──

    async def _find_active_plan(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> Optional[TaskPlanModel]:
        """Find the ACTIVE plan for a task."""
        result = await db.execute(
            select(TaskPlanModel)
            .where(TaskPlanModel.task_id == task_id)
            .where(TaskPlanModel.status == PlanStatus.ACTIVE)
            .order_by(TaskPlanModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _parse_steps(self, steps_json: str) -> list[dict]:
        """Parse the steps_json field into a list of dicts."""
        try:
            steps = json.loads(steps_json or "[]")
            if not isinstance(steps, list):
                return []
            return steps
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse steps_json: {steps_json[:200]}")
            return []
