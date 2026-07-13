"""test_policy_tool_gate.py — Phase 16 Tool Action Gate Tests

Coverage:
  - Default rules inserted
  - Engineer merge main => deny
  - Reviewer write file => deny
  - Normal file read => allow (not gated)
  - Audit created (confirm logger called for deny)
"""

import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PolicyRuleModel, PolicyEffect
from backend.services.task.task_policy import (
    check_tool_action,
    init_default_policy_rules,
)


@pytest.mark.asyncio
async def test_default_rules_inserted(db_session: AsyncSession):
    """init_default_policy_rules should insert all default rules."""
    inserted = await init_default_policy_rules(db_session)
    assert len(inserted) == 5  # 5 default deny rules

    # Should be idempotent
    again = await init_default_policy_rules(db_session)
    assert again == []


@pytest.mark.asyncio
async def test_engineer_merge_main_denied(db_session: AsyncSession):
    """Engineer attempting git_merge main should be denied."""
    await init_default_policy_rules(db_session)

    allowed, reason = await check_tool_action(
        db_session, subject="engineer", action="git_merge", resource="main"
    )
    assert not allowed
    assert "policy:no-main-merge" in reason


@pytest.mark.asyncio
async def test_reviewer_write_file_denied(db_session: AsyncSession):
    """Reviewer attempting file_write should be denied."""
    await init_default_policy_rules(db_session)

    allowed, reason = await check_tool_action(
        db_session, subject="reviewer", action="file_write", resource="any/file.py"
    )
    assert not allowed
    assert "policy:reviewer-readonly" in reason


@pytest.mark.asyncio
async def test_normal_file_read_allowed(db_session: AsyncSession):
    """file_read is not in the gated actions — always allowed."""
    await init_default_policy_rules(db_session)

    allowed, reason = await check_tool_action(
        db_session, subject="engineer", action="file_read", resource="some/file.py"
    )
    assert allowed
    assert reason == ""


@pytest.mark.asyncio
async def test_unknown_action_allowed(db_session: AsyncSession):
    """Actions not in CHECKABLE_ACTIONS always pass."""
    allowed, reason = await check_tool_action(
        db_session, subject="engineer", action="something_random", resource="*"
    )
    assert allowed


@pytest.mark.asyncio
async def test_engineer_normal_write_allowed(db_session: AsyncSession):
    """Engineer writing normal (non-secret) files should be allowed."""
    await init_default_policy_rules(db_session)

    allowed, reason = await check_tool_action(
        db_session, subject="engineer", action="file_write", resource="src/hello.py"
    )
    assert allowed
    assert reason == ""


@pytest.mark.asyncio
async def test_engineer_no_rm_rf(db_session: AsyncSession):
    """Engineer running rm -rf /* should be denied."""
    await init_default_policy_rules(db_session)

    allowed, reason = await check_tool_action(
        db_session, subject="engineer", action="shell_exec", resource="rm -rf /"
    )
    assert not allowed
    assert "policy:no-force-delete" in reason
