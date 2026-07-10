"""task_policy.py — Task Policy Layer (Phase C2)

Replaces hardcoded step-level flags with a configurable per-task Policy
evaluated at runtime by the Executor.

Policy evaluation rules:
  - HIGH risk level → always blocked (POLICY_BLOCKED)
  - MEDIUM risk level → approval check applies
  - LOW risk level → auto-approve (proceed unless cost/teammate limits trigger)
  - Cost limit check: max_cost > 0 and estimated > max → COST_LIMIT_REACHED
  - Teammate permission: allowed_teammates non-empty + step.teammate_id not in list → blocked
  - Retry limit: step.retry_count >= max_retry → blocked

Default policy (when none configured):
  - approval_required=0, max_retry=2, max_cost=0 (unlimited),
    risk_level=LOW, allowed_teammates=[] (anyone)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskPolicyModel,
    RiskLevel,
    gen_uuid,
    utcnow,
)

logger = logging.getLogger("task.policy")


@dataclass
class PolicyResult:
    """Result of a policy evaluation."""
    allowed: bool = True
    requires_approval: bool = False
    blocked_reason: str = ""
    risk_level: str = RiskLevel.LOW
    max_retry: int = 2
    max_cost: int = 0


class TaskPolicyService:
    """Service for managing and evaluating task execution policies."""

    # ── Policy CRUD ──

    async def get_policy(
        self, db: AsyncSession, task_id: str
    ) -> TaskPolicyModel:
        """Get the policy for a task, creating a default if none exists."""
        result = await db.execute(
            select(TaskPolicyModel).where(TaskPolicyModel.task_id == task_id)
        )
        policy = result.scalar_one_or_none()
        if policy is None:
            policy = await self._create_default(db, task_id)
        return policy

    async def create_default_policy(
        self, db: AsyncSession, task_id: str
    ) -> TaskPolicyModel:
        """Create a default policy for a newly created task."""
        return await self._create_default(db, task_id)

    async def upsert_policy(
        self,
        db: AsyncSession,
        task_id: str,
        *,
        approval_required: Optional[str] = None,
        max_retry: Optional[int] = None,
        max_cost: Optional[int] = None,
        risk_level: Optional[str] = None,
        allowed_teammates: Optional[str] = None,
    ) -> TaskPolicyModel:
        """Create or update policy for a task. Only provided fields change."""
        policy = await self.get_policy(db, task_id)

        if approval_required is not None:
            policy.approval_required = approval_required
        if max_retry is not None:
            policy.max_retry = max_retry
        if max_cost is not None:
            policy.max_cost = max_cost
        if risk_level is not None:
            policy.risk_level = risk_level
        if allowed_teammates is not None:
            policy.allowed_teammates = allowed_teammates

        db.add(policy)
        return policy

    # ── Policy Evaluation ──

    async def evaluate_step(
        self,
        db: AsyncSession,
        task: TaskModel,
        step: TaskStepModel,
    ) -> PolicyResult:
        """Evaluate whether a step can be executed under the current policy.

        Returns a PolicyResult with:
          - allowed: whether execution may proceed
          - requires_approval: whether human approval is needed before execution
          - blocked_reason: why it was blocked (if allowed=False)
        """
        policy = await self.get_policy(db, task.id)
        result = PolicyResult(
            risk_level=policy.risk_level,
            max_retry=policy.max_retry,
            max_cost=policy.max_cost,
        )

        # 1. Risk level check
        if policy.risk_level == RiskLevel.HIGH:
            result.allowed = False
            result.blocked_reason = (
                f"Policy blocked: risk_level=HIGH for task {task.id}"
            )
            return result

        # 2. Retry limit check
        if step.retry_count and step.retry_count >= policy.max_retry:
            result.allowed = False
            result.blocked_reason = (
                f"Policy blocked: retry_count {step.retry_count} "
                f">= max_retry {policy.max_retry}"
            )
            return result

        # 3. Teammate permission check
        allowed = policy.get_allowed_teammates()
        if allowed and step.teammate_id and step.teammate_id not in allowed:
            result.allowed = False
            result.blocked_reason = (
                f"Policy blocked: teammate '{step.teammate_id}' "
                f"not in allowed_teammates {allowed}"
            )
            return result

        # 4. Approval check (MEDIUM or LOW with approval_required)
        if policy.risk_level == RiskLevel.MEDIUM:
            if policy.approval_required == "1":
                result.requires_approval = True
        elif policy.risk_level == RiskLevel.LOW:
            if policy.approval_required == "1":
                result.requires_approval = True

        return result

    async def evaluate_cost(
        self,
        db: AsyncSession,
        task_id: str,
        estimated_cost: float,
    ) -> PolicyResult:
        """Check if estimated cost exceeds policy limit.

        Returns a result with allowed=False and COST_LIMIT_REACHED info
        if estimated_cost > max_cost.
        """
        policy = await self.get_policy(db, task_id)
        result = PolicyResult(
            risk_level=policy.risk_level,
            max_retry=policy.max_retry,
            max_cost=policy.max_cost,
        )

        if policy.max_cost > 0 and estimated_cost > policy.max_cost:
            result.allowed = False
            result.blocked_reason = (
                f"Cost limit reached: estimated {estimated_cost} "
                f"> max {policy.max_cost}"
            )

        return result

    async def check_permission(
        self,
        db: AsyncSession,
        task_id: str,
        teammate_id: str,
    ) -> bool:
        """Check if a teammate is allowed to execute steps for this task."""
        policy = await self.get_policy(db, task_id)
        allowed = policy.get_allowed_teammates()
        if not allowed:
            return True  # empty = anyone
        return teammate_id in allowed

    # ── Internal ──

    async def _create_default(
        self, db: AsyncSession, task_id: str
    ) -> TaskPolicyModel:
        """Create a default policy record."""
        policy = TaskPolicyModel(
            task_id=task_id,
            approval_required="0",
            max_retry=2,
            max_cost=0,
            risk_level=RiskLevel.LOW,
            allowed_teammates="[]",
        )
        db.add(policy)
        await db.flush()
        logger.info(f"[POLICY] Created default policy for task {task_id}")
        return policy
