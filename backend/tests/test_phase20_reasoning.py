"""Phase 20: Organization Reasoning Layer — tests.

Covers:
1. reasoning includes experience when patterns are provided
2. failure patterns increase risk
3. confidence computed correctly from patterns
4. optional reasoning param in DecisionEngine doesn't affect old calls
"""

import math
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.organization.actions import OrganizationAction

pytestmark = pytest.mark.asyncio


# ════════════════════════════════════════════════
# 1. reason() — basic output shape
# ════════════════════════════════════════════════


def test_reason_returns_all_keys():
    """reason() returns the full dict with all expected keys."""
    from backend.services.organization.reasoning import reason

    r = reason()
    assert isinstance(r, dict)
    assert "decision_reason" in r
    assert "recommended_roles" in r
    assert "risk_factors" in r
    assert "confidence" in r
    assert "supporting_experience" in r
    assert 0.1 <= r["confidence"] <= 0.99


# ════════════════════════════════════════════════
# 2. experience inclusion
# ════════════════════════════════════════════════


def test_reason_with_experience():
    """supporting_experience includes provided experience entries."""
    from backend.services.organization.reasoning import reason

    exp = [
        {"goal": "fixed API timeout", "teammate": "tm-1", "result": "success", "lesson": "increase timeout"},
        {"goal": "deployed k8s", "teammate": "tm-2", "result": "failure", "lesson": "check config"},
    ]
    r = reason(goal="deploy", experience=exp)
    assert len(r["supporting_experience"]) == 2
    assert r["supporting_experience"][0]["teammate"] == "tm-1"


def test_reason_experience_limited_to_three():
    """At most 3 experience entries in reasoning."""
    from backend.services.organization.reasoning import reason

    exp = [{"goal": f"task {i}", "teammate": f"tm-{i}"} for i in range(10)]
    r = reason(experience=exp)
    assert len(r["supporting_experience"]) <= 3


# ════════════════════════════════════════════════
# 3. failure patterns increase risk
# ════════════════════════════════════════════════


def test_failure_patterns_add_risk():
    """Each failure pattern becomes a risk factor."""
    from backend.services.organization.reasoning import reason

    patterns = ["db timeout on migration", "API rate limit", "memory leak in worker"]
    r = reason(failure_patterns=patterns)
    assert len(r["risk_factors"]) >= 3
    assert any("db timeout" in f for f in r["risk_factors"])


def test_no_failures_no_risk():
    """No failure patterns → no failure-related risk factors."""
    from backend.services.organization.reasoning import reason

    r = reason(failure_patterns=[])
    assert all("Prior failure" not in f for f in r["risk_factors"])


# ════════════════════════════════════════════════
# 4. confidence calculation
# ════════════════════════════════════════════════


def test_confidence_increases_with_successes():
    """More success patterns → higher confidence."""
    from backend.services.organization.reasoning import reason

    low = reason(successful_patterns=[])
    high = reason(successful_patterns=["p1"] * 5)
    assert high["confidence"] > low["confidence"]


def test_confidence_decreases_with_failures():
    """Failure patterns reduce confidence."""
    from backend.services.organization.reasoning import reason

    base = reason(goal="build")
    risky = reason(goal="build", failure_patterns=["crash", "timeout"])
    assert risky["confidence"] < base["confidence"]


def test_team_goal_boosts_confidence():
    """Having a goal and team increases confidence."""
    from backend.services.organization.reasoning import reason

    solo = reason()
    team = reason(goal="build", members_info={"tm-1": {"role": "dev"}, "tm-2": {"role": "ops"}})
    assert team["confidence"] > solo["confidence"]


# ════════════════════════════════════════════════
# 5. DecisionEngine optional reasoning param
# ════════════════════════════════════════════════


def test_decide_no_reasoning_unchanged():
    """decide() without reasoning behaves exactly as before."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine

    eng = OrganizationDecisionEngine()
    ctx = OrganizationContext({"run_id": "r1", "members": ["tm-1"]})
    assert eng.decide(ctx, "Hello") == OrganizationAction.RESPOND
    assert eng.decide(ctx, "Fix bug") == OrganizationAction.EXECUTE


def test_score_context_reasoning_risk_dampens_delegate():
    """Reasoning risk factors further dampen DELEGATE."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine

    ctx = OrganizationContext({"run_id": "r1", "goal": "build", "members": ["tm-1", "tm-2"]})
    base = OrganizationDecisionEngine._score_context(ctx)
    reasoning = {"risk_factors": ["Prior failure: db crash", "Prior failure: timeout"]}
    dampened = OrganizationDecisionEngine._score_context(ctx, reasoning=reasoning)

    base_del = base.get(OrganizationAction.DELEGATE, 0)
    damp_del = dampened.get(OrganizationAction.DELEGATE, 0)
    assert damp_del < base_del


def test_explain_reasoning_boosts_confidence():
    """Reasoning confidence can raise explain() confidence."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine

    ctx = OrganizationContext({"run_id": "r1", "members": ["tm-1"]})
    base_conf = OrganizationDecisionEngine.explain(OrganizationAction.RESPOND, ctx)[1]
    reasoning = {"confidence": 0.95}
    boosted = OrganizationDecisionEngine.explain(OrganizationAction.RESPOND, ctx, reasoning=reasoning)[1]
    assert boosted >= base_conf


def test_explain_reasoning_lower_confidence_ignored():
    """Reasoning confidence lower than computed → not used (no downgrade)."""
    from backend.services.organization.context import OrganizationContext
    from backend.services.organization.decision import OrganizationDecisionEngine

    ctx = OrganizationContext({"run_id": "r1", "goal": "big goal", "members": ["tm-1", "tm-2"]})
    base_conf = OrganizationDecisionEngine.explain(OrganizationAction.DELEGATE, ctx)[1]
    reasoning = {"confidence": 0.1}
    same = OrganizationDecisionEngine.explain(OrganizationAction.DELEGATE, ctx, reasoning=reasoning)[1]
    assert same == base_conf
