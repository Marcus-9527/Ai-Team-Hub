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
    PolicyEffect,
    PolicyRuleModel,
    PolicyDecisionModel,
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

    async def evaluate_direct(
        self,
        db: AsyncSession,
        task: TaskModel,
        *,
        teammate_id: str = "",
        action: str = "task.execute",
    ) -> tuple[bool, str]:
        """Evaluate a direct (non-step) execution for policy compliance.

        Checks risk level and teammate permission only — no retry/approval
        (those apply at step level).

        Returns (allowed, reason).
        """
        policy = await self.get_policy(db, task.id)

        # 1. Risk level check
        if policy.risk_level == RiskLevel.HIGH:
            return False, f"Policy blocked: risk_level=HIGH for task {task.id}"

        # 2. Teammate permission check
        allowed = policy.get_allowed_teammates()
        if allowed and teammate_id and teammate_id not in allowed:
            return False, (
                f"Policy blocked: teammate '{teammate_id}' "
                f"not in allowed_teammates {allowed}"
            )

        return True, ""

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


# ── Chat Message Policy (Phase 15 — minimal gate) ──

async def check_message_policy(
    db: AsyncSession,
    teammate: dict,
    channel_id: str,
    action: str = "message.send",
    task_id: str = "",
) -> tuple[bool, str]:
    """Check if a teammate is allowed to send messages in a channel.

    ponytail: always allows, but writes audit record.
    Real policies (role-blacklist, channel-whitelist, rate-limit) slot in here.
    """
    subject = teammate.get("id", "?")
    _write_decision(db, subject, action, channel_id,
                    PolicyEffect.ALLOW, "", task_id, channel_id)
    return True, ""


# ═══════════════════════════════════════════════════════════════
# Phase 16: Tool Action Gate
# ═══════════════════════════════════════════════════════════════


_CHECKABLE_ACTIONS = frozenset({
    "file_write", "shell_exec", "git_commit", "git_merge",
    "task_create", "message_send",
})

# ponytail: approval-required action/resource patterns.
# Actions matching these patterns need human approval before execution.
# Upgrade to a rule-based system (PolicyRuleModel with effect=APPROVAL_REQUIRED)
# when more than ~10 rules exist.
_APPROVAL_REQUIRED_PATTERNS: list[tuple[str, str]] = [
    ("shell_exec", "*deploy*"),
    ("shell_exec", "*production*"),
    ("shell_exec", "*database_delete*"),
    ("shell_exec", "*credential_rotate*"),
    ("file_write", "*production*"),
    ("file_write", "*credential*rotate*"),
]

# ponytail: in-memory L1 cache (subject, action, resource → effect).
# If you add dynamic rule editing at the 95th percentile, slap redis in front.
_rules_cache: dict[str, str] = {}  # cache_key → effect
_rules_cached_at: float = 0


def _policy_cache_key(rules: list) -> str:
    """Stable hash of the current rule set for cache invalidation."""
    return str(len(rules)) + "|" + str(abs(hash(str([(r.id, r.effect) for r in rules]))))[:12]


async def check_tool_action(
    db: AsyncSession,
    subject: str,
    action: str,
    resource: str = "*",
    task_id: str = "",
    channel_id: str = "",
) -> tuple[bool, str]:
    """Check if `subject` is allowed to perform `action` on `resource`.

    Returns (allowed, reason).
    Every check writes a PolicyDecisionModel audit record.
    """
    if action not in _CHECKABLE_ACTIONS:
        return True, ""

    rules = await _load_rules(db)

    # 1. Subject-specific deny rules win.
    for r in rules:
        if r.effect == PolicyEffect.DENY and _match_rule(r, subject, action, resource):
            _write_decision(db, subject, action, resource, PolicyEffect.DENY,
                            r.reason, task_id, channel_id)
            return False, r.reason

    # 2. Approval-required patterns check.
    for pat_action, pat_resource in _APPROVAL_REQUIRED_PATTERNS:
        if pat_action == action and _resource_glob_match(pat_resource, resource):
            reason = f"APPROVAL_REQUIRED: {action}/{resource}"
            _write_decision(db, subject, action, resource, PolicyEffect.APPROVAL_REQUIRED,
                            reason, task_id, channel_id)
            return False, reason

    # 3. Default allow.
    _write_decision(db, subject, action, resource, PolicyEffect.ALLOW,
                    "", task_id, channel_id)
    return True, ""


def _resource_glob_match(pattern: str, target: str) -> bool:
    """Simple glob match: * matches any substring."""
    if pattern == "*":
        return True
    if pattern.startswith("*") and pattern.endswith("*"):
        return pattern[1:-1] in target
    if pattern.endswith("*"):
        return target.startswith(pattern[:-1])
    if pattern.startswith("*"):
        return target.endswith(pattern[1:])
    return target == pattern


def _write_decision(
    db: AsyncSession,
    subject: str,
    action: str,
    resource: str,
    effect: str,
    reason: str,
    task_id: str = "",
    channel_id: str = "",
) -> None:
    """Write a policy decision audit record."""
    from backend.models import PolicyDecisionModel
    decision = PolicyDecisionModel(
        teammate_id=subject,
        action=action,
        resource=resource,
        effect=effect,
        reason=reason,
        task_id=task_id,
        channel_id=channel_id,
    )
    db.add(decision)


def _match_rule(rule: "PolicyRuleModel", subject: str, action: str, resource: str) -> bool:
    """Check if a rule applies to this (subject, action, resource)."""
    if rule.subject != "*" and rule.subject != subject:
        return False
    if rule.action != action:
        return False
    if not rule._resource_matches(resource):
        return False
    return True


async def _load_rules(db: AsyncSession) -> list:
    """Load all DENY rules (the only kind the gate needs)."""
    from sqlalchemy import select
    from backend.models import PolicyRuleModel, PolicyEffect

    result = await db.execute(
        select(PolicyRuleModel).where(PolicyRuleModel.effect == PolicyEffect.DENY)
    )
    return list(result.scalars().all())


async def init_default_policy_rules(db: AsyncSession) -> list[str]:
    """Insert the default deny rules if they don't exist. Returns inserted IDs."""
    from sqlalchemy import select
    from backend.models import PolicyRuleModel, PolicyEffect

    defaults = [
        # Engineers cannot merge main or touch production secrets
        ("engineer", "git_merge", "main", "policy:no-main-merge"),
        ("engineer", "file_write", "*production*secret*", "policy:no-prod-secret"),
        ("engineer", "file_write", "*delete*workspace*", "policy:no-delete-workspace"),
        ("engineer", "shell_exec", "*rm -rf /*", "policy:no-force-delete"),
        # Reviewers cannot write files
        ("reviewer", "file_write", "*", "policy:reviewer-readonly"),
    ]

    inserted = []
    for subject, action, resource, reason in defaults:
        exists = await db.execute(
            select(PolicyRuleModel).where(
                PolicyRuleModel.subject == subject,
                PolicyRuleModel.action == action,
                PolicyRuleModel.resource == resource,
            )
        )
        if exists.scalar_one_or_none() is None:
            rule = PolicyRuleModel(
                subject=subject, action=action, resource=resource,
                effect=PolicyEffect.DENY, reason=reason,
            )
            db.add(rule)
            inserted.append(reason)
    if inserted:
        await db.flush()
        logger.info("[POLICY] Inserted %d default rules: %s", len(inserted), inserted)
    return inserted


async def list_policy_events(
    db: AsyncSession,
    limit: int = 50,
    effect: Optional[str] = None,
) -> list[PolicyDecisionModel]:
    """Query recent policy decision audit records."""
    from sqlalchemy import select, desc
    query = select(PolicyDecisionModel)
    if effect:
        query = query.where(PolicyDecisionModel.effect == effect)
    query = query.order_by(desc(PolicyDecisionModel.created_at)).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
