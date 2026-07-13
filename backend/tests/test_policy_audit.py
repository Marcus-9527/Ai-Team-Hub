"""test_policy_audit.py — Phase 17 Policy Audit Tests

Coverage:
  1. deny produces audit record
  2. allow produces audit record
  3. approval blocks execution
  4. approval required then allowed (non-matching action passes)
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PolicyDecisionModel, PolicyEffect
from backend.services.task.task_policy import (
    check_tool_action,
    init_default_policy_rules,
    list_policy_events,
)


@pytest.mark.asyncio
async def test_deny_produces_audit(db_session: AsyncSession):
    """DENY decision writes a PolicyDecisionModel row with effect=deny."""
    await init_default_policy_rules(db_session)
    allowed, _ = await check_tool_action(
        db_session, subject="engineer", action="git_merge", resource="main",
    )
    assert not allowed

    result = await db_session.execute(
        select(PolicyDecisionModel).where(PolicyDecisionModel.effect == PolicyEffect.DENY)
    )
    rows = list(result.scalars().all())
    assert len(rows) >= 1
    row = rows[-1]
    assert row.teammate_id == "engineer"
    assert row.action == "git_merge"


@pytest.mark.asyncio
async def test_allow_produces_audit(db_session: AsyncSession):
    """ALLOW decision writes a PolicyDecisionModel row with effect=allow."""
    allowed, _ = await check_tool_action(
        db_session, subject="engineer", action="file_write", resource="src/hello.py",
    )
    assert allowed

    result = await db_session.execute(
        select(PolicyDecisionModel).where(PolicyDecisionModel.effect == PolicyEffect.ALLOW)
    )
    rows = list(result.scalars().all())
    assert len(rows) >= 1
    row = rows[-1]
    assert row.teammate_id == "engineer"


@pytest.mark.asyncio
async def test_approval_blocks_execution(db_session: AsyncSession):
    """deploy/production actions return APPROVAL_REQUIRED."""
    allowed, reason = await check_tool_action(
        db_session, subject="engineer", action="shell_exec", resource="deploy --env production",
    )
    assert not allowed
    assert "APPROVAL_REQUIRED" in reason

    # Confirm audit record written
    result = await db_session.execute(
        select(PolicyDecisionModel)
        .where(PolicyDecisionModel.effect == PolicyEffect.APPROVAL_REQUIRED)
        .limit(1)
    )
    row = result.scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
async def test_approval_required_then_non_matching_passes(db_session: AsyncSession):
    """Non-matching actions pass through after approval-required pattern check."""
    allowed, reason = await check_tool_action(
        db_session, subject="engineer", action="shell_exec", resource="pytest",
    )
    assert allowed
    assert not reason.startswith("APPROVAL_REQUIRED:")


@pytest.mark.asyncio
async def test_list_policy_events(db_session: AsyncSession):
    """list_policy_events returns recent decisions."""
    await init_default_policy_rules(db_session)
    await check_tool_action(
        db_session, subject="engineer", action="git_merge", resource="main",
    )
    await check_tool_action(
        db_session, subject="engineer", action="file_write", resource="src/hello.py",
    )

    events = await list_policy_events(db_session, limit=10)
    assert len(events) >= 2

    deny_events = await list_policy_events(db_session, limit=10, effect=PolicyEffect.DENY)
    assert len(deny_events) >= 1
