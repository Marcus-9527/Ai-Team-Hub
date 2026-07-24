"""Phase 18: OrganizationState Intelligence — tests.

Verifies:
1. OrganizationStateManager builds state from existing data
2. DecisionEngine._score_context uses optional organization_state
3. Default behaviour unchanged when org_state not provided
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure all models are registered for Base.metadata.create_all
from backend.models.chat import Teammate  # noqa: F401

pytestmark = pytest.mark.asyncio

# ════════════════════════════════════════════════
# 1. build_state — empty workspace
# ════════════════════════════════════════════════


async def test_build_state_empty_workspace(db_session):
    """No teammates → all fields empty."""
    from backend.services.organization.state import OrganizationStateManager

    mgr = OrganizationStateManager(db_session)
    state = await mgr.build_state("ws-empty")

    assert state["preferred_roles"] == {}
    assert state["successful_patterns"] == []
    assert state["failure_patterns"] == []
    assert state["team_strengths"] == {}
    assert state["team_weaknesses"] == {}


# ════════════════════════════════════════════════
# 2. build_state — with teammates
# ════════════════════════════════════════════════


async def test_build_state_with_teammates(db_session):
    """Teammate strengths/weaknesses/patterns are aggregated."""
    from backend.services.organization.state import OrganizationStateManager
    from backend.models.chat import Teammate

    db_session.add(Teammate(
        id="tm-1", name="Dev A", role="engineer",
        workspace_id="ws-1",
        strengths=["Python", "React", "API design"],
        weaknesses=["testing", "documentation"],
        learned_patterns=["async patterns"],
        failed_patterns=["sync locking"],
        success_rate=0.85, execution_count=20,
        model_provider="openai", model_name="gpt-4",
    ))
    db_session.add(Teammate(
        id="tm-2", name="Dev B", role="engineer",
        workspace_id="ws-1",
        strengths=["Python", "testing"],
        weaknesses=["frontend"],
        learned_patterns=[],
        failed_patterns=["db migration"],
        success_rate=0.72, execution_count=10,
        model_provider="openai", model_name="gpt-4",
    ))
    db_session.add(Teammate(
        id="tm-3", name="Analyst", role="analyst",
        workspace_id="ws-1",
        strengths=["data analysis"],
        weaknesses=["coding"],
        success_rate=0.0, execution_count=0,  # no executions — excluded from roles
        model_provider="openai", model_name="gpt-4",
    ))
    await db_session.commit()

    mgr = OrganizationStateManager(db_session)
    state = await mgr.build_state("ws-1")

    # team_strengths: frequency-sorted top 10
    assert "Python" in state["team_strengths"]
    assert state["team_strengths"]["Python"] == 2
    assert state["team_strengths"]["testing"] == 1

    # team_weaknesses
    assert "frontend" in state["team_weaknesses"]

    # preferred_roles — only roles with execution_count > 0
    assert "engineer" in state["preferred_roles"]
    assert "analyst" not in state["preferred_roles"]  # execution_count=0
    eng = state["preferred_roles"]["engineer"]
    assert eng["count"] == 2
    assert eng["avg_success_rate"] == pytest.approx(0.785, abs=0.01)

    # patterns
    assert "async patterns" in state["successful_patterns"]
    failure_set = set(state["failure_patterns"])
    assert "sync locking" in failure_set
    assert "db migration" in failure_set


# ════════════════════════════════════════════════
# 3. build_state — cross-workspace isolation
# ════════════════════════════════════════════════


async def test_build_state_workspace_isolation(db_session):
    """Teammates from other workspaces don't leak in."""
    from backend.services.organization.state import OrganizationStateManager
    from backend.models.chat import Teammate

    db_session.add(Teammate(
        id="tm-other", name="Other", role="engineer",
        workspace_id="ws-other",
        strengths=["Java"],
        weaknesses=["tests"],
        success_rate=0.9, execution_count=5,
        model_provider="openai", model_name="gpt-4",
    ))
    await db_session.commit()

    mgr = OrganizationStateManager(db_session)
    state = await mgr.build_state("ws-unrelated")

    assert state["team_strengths"] == {}
    assert state["preferred_roles"] == {}


# ════════════════════════════════════════════════
# 4. DecisionEngine — default behaviour unchanged
# ════════════════════════════════════════════════


def test_decide_default_no_org_state():
    """decide() without organization_state behaves exactly as before."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine
    from backend.services.organization.actions import OrganizationAction

    eng = OrganizationDecisionEngine()
    ctx = OrganizationContext({"run_id": "r1", "members": ["tm-1", "tm-2"]})

    assert eng.decide(ctx, "Hello") == OrganizationAction.RESPOND
    assert eng.decide(ctx, "```python\nx=1\n```") == OrganizationAction.EXECUTE
    assert eng.decide(ctx, "Fix this bug") == OrganizationAction.EXECUTE


def test_explain_default_no_org_state():
    """explain() without organization_state matches prior behaviour."""
    from backend.services.organization.decision import OrganizationDecisionEngine
    from backend.services.organization.actions import OrganizationAction

    reason, conf = OrganizationDecisionEngine.explain(OrganizationAction.DELEGATE)
    assert reason == "Multi-step or long input detected"
    assert conf == 0.85

    reason2, conf2 = OrganizationDecisionEngine.explain(OrganizationAction.EXECUTE)
    assert conf2 == 0.90


# ════════════════════════════════════════════════
# 5. DecisionEngine — org_state influences scores
# ════════════════════════════════════════════════


def test_score_context_with_org_state():
    """organization_state adds scores when provided."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine
    from backend.services.organization.actions import OrganizationAction

    ctx = OrganizationContext({
        "run_id": "r1",
        "goal": "Build auth",
        "members": ["tm-1", "tm-2"],
        "members_info": {"tm-1": {"role": "engineer"}},
    })

    # Without org_state
    base = OrganizationDecisionEngine._score_context(ctx)
    base_del = base[OrganizationAction.DELEGATE]

    # With org_state
    org_state = {
        "preferred_roles": {"engineer": {"count": 5, "avg_success_rate": 0.88}},
        "successful_patterns": ["async worked", "api design pattern"],
        "failure_patterns": [],
        "team_strengths": {"Python": 3},
        "team_weaknesses": {},
    }
    boosted = OrganizationDecisionEngine._score_context(ctx, organization_state=org_state)
    boosted_del = boosted[OrganizationAction.DELEGATE]

    # DELEGATE should be higher: preferred_roles(+0.05) + successful_patterns(+0.05)
    assert boosted_del == pytest.approx(base_del + 0.10, abs=0.001)
    # EXECUTE gets +0.03 from team_strengths
    assert boosted[OrganizationAction.EXECUTE] == pytest.approx(
        base[OrganizationAction.EXECUTE] + 0.03, abs=0.001,
    )


def test_score_context_with_org_state_failure_patterns():
    """failure_patterns dampens DELEGATE."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine
    from backend.services.organization.actions import OrganizationAction

    ctx = OrganizationContext({
        "run_id": "r1", "goal": "Build",
        "members": ["tm-1", "tm-2"],
    })
    base = OrganizationDecisionEngine._score_context(ctx)
    base_del = base[OrganizationAction.DELEGATE]

    org_state = {
        "preferred_roles": {},
        "successful_patterns": [],
        "failure_patterns": ["db migration", "timeout issue"],
        "team_strengths": {},
        "team_weaknesses": {"frontend": 1},
    }
    dampened = OrganizationDecisionEngine._score_context(ctx, organization_state=org_state)
    dampened_del = dampened[OrganizationAction.DELEGATE]

    # DELEGATE gets -0.05 from failure patterns
    assert dampened_del == pytest.approx(base_del - 0.05, abs=0.001)


# ════════════════════════════════════════════════
# 6. DecisionEngine — decide with org_state changes outcome
# ════════════════════════════════════════════════


def test_decide_org_state_shifts_marginal_case():
    """org_state can tip a marginal case from RESPOND to DELEGATE."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine
    from backend.services.organization.actions import OrganizationAction

    eng = OrganizationDecisionEngine()

    # Marginal: long input, goal set, 2 members, but no identity
    ctx = OrganizationContext({
        "run_id": "r1", "goal": "Some goal",
        "members": ["tm-1", "tm-2"],
    })

    # Without org_state — RESPOND (no identity boost for DELEGATE)
    # goal +0.10 DELEGATE, no identity +0, 2 members → no solo dampen
    # DELEGATE=0.10, RESPOND=-0.05 → DELEGATE beats RESPOND
    result_no = eng.decide(ctx, "This is a fairly long input about something")
    # With 2 members, goal: delegate=0.10, respond=-0.05 → DELEGATE wins
    # Actually let me just check what it returns — with goal+2 members it's DELEGATE
    # Let's instead test with solo member where it's RESPOND without org_state

    # Solo → DELEGATE dampened by -0.15
    solo_ctx = OrganizationContext({
        "run_id": "r1", "goal": "Some goal",
        "members": ["tm-1"],
    })
    result_solo = eng.decide(solo_ctx, "This is a fairly long input about something")
    assert result_solo == OrganizationAction.RESPOND

    # With org_state that provides preferred roles + success patterns (+0.10)
    # DELEGATE gets +0.10 (goal) - 0.15 (solo) + 0.10 (org_state) = +0.05
    # RESPOND gets -0.05 (goal) + ??? → DELEGATE > RESPOND
    org_state = {
        "preferred_roles": {"engineer": {"count": 5, "avg_success_rate": 0.88}},
        "successful_patterns": ["pattern work"],
        "failure_patterns": [],
        "team_strengths": {"Python": 3},
        "team_weaknesses": {},
    }
    result_with = eng.decide(
        solo_ctx, "This is a fairly long input about something",
        organization_state=org_state,
    )
    # org_state adds +0.05 (preferred) + 0.05 (success) = +0.10 to DELEGATE
    # DELEGATE = +0.10 (goal) - 0.15 (solo) + 0.10 = +0.05
    # RESPOND = -0.05 (goal)
    # → DELEGATE wins
    assert result_with == OrganizationAction.DELEGATE


# ════════════════════════════════════════════════
# 7. DecisionEngine — explain adapts with org_state
# ════════════════════════════════════════════════


def test_explain_with_org_state():
    """explain() adjusts confidence when org_state is passed."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine
    from backend.services.organization.actions import OrganizationAction

    ctx = OrganizationContext({
        "run_id": "r1", "goal": "Big task",
        "members": ["tm-1", "tm-2"],
        "members_info": {"tm-1": {"role": "engineer"}},
    })

    base_conf = OrganizationDecisionEngine.explain(
        OrganizationAction.DELEGATE, ctx,
    )[1]

    org_state = {
        "preferred_roles": {"engineer": {"count": 5, "avg_success_rate": 0.88}},
        "successful_patterns": ["good patterns"],
        "failure_patterns": [],
        "team_strengths": {"Python": 3},
        "team_weaknesses": {},
    }
    boosted_conf = OrganizationDecisionEngine.explain(
        OrganizationAction.DELEGATE, ctx, organization_state=org_state,
    )[1]

    assert boosted_conf > base_conf
