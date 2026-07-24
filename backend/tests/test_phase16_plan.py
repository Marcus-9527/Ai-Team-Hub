"""Phase 16: OrganizationPlan — tests.

Verifies:
1. PlanStep / OrganizationPlan data model
2. PlanBuilder classification (chat/dev/analysis/retry)
3. PlanBuilder generates correct steps per pattern
4. engine.plan() delegates correctly
5. Edge cases: no goal, empty ctx, mixed signals
"""

import pytest

from backend.services.organization.actions import OrganizationAction
from backend.services.organization.context import OrganizationContext


# ── Data model ──

class TestPlanModel:
    """PlanStep and OrganizationPlan dataclass basics."""

    def test_plan_step_fields(self):
        from backend.services.organization.plan import PlanStep
        step = PlanStep(
            step_type="execute",
            action=OrganizationAction.EXECUTE,
            role="developer",
            reason="Do the thing",
            confidence=0.85,
        )
        assert step.step_type == "execute"
        assert step.action == OrganizationAction.EXECUTE
        assert step.role == "developer"
        assert step.reason == "Do the thing"
        assert step.confidence == 0.85

    def test_organization_plan_defaults(self):
        from backend.services.organization.plan import OrganizationPlan
        plan = OrganizationPlan(goal="Test goal")
        assert plan.goal == "Test goal"
        assert plan.steps == []
        assert plan.reasoning == ""

    def test_organization_plan_with_steps(self):
        from backend.services.organization.plan import OrganizationPlan, PlanStep
        step = PlanStep("respond", OrganizationAction.RESPOND, "comm", "say hi", 0.8)
        plan = OrganizationPlan(
            goal="Hello",
            steps=[step],
            reasoning="Simple chat",
        )
        assert plan.goal == "Hello"
        assert len(plan.steps) == 1
        assert plan.steps[0].action == OrganizationAction.RESPOND
        assert plan.reasoning == "Simple chat"


# ── PlanBuilder classification ──

class TestPlanClassification:
    """PlanBuilder._classify correctly identifies patterns."""

    def test_no_goal_is_chat(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({"run_id": "r1"})
        pattern = PlanBuilder._classify(ctx, None, "")
        assert pattern == "chat"

    def test_dev_keywords_in_goal(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({"run_id": "r1", "goal": "Implement user auth"})
        pattern = PlanBuilder._classify(ctx, None, "Implement user auth")
        assert pattern == "dev"

    def test_dev_keywords_chinese(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({"run_id": "r1", "goal": "实现登录功能"})
        pattern = PlanBuilder._classify(ctx, None, "实现登录功能")
        assert pattern == "dev"

    def test_analysis_keywords_in_goal(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({"run_id": "r1", "goal": "Analyze performance data"})
        pattern = PlanBuilder._classify(ctx, None, "Analyze performance data")
        assert pattern == "analysis"

    def test_analysis_keywords_chinese(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({"run_id": "r1", "goal": "分析用户行为"})
        pattern = PlanBuilder._classify(ctx, None, "分析用户行为")
        assert pattern == "analysis"

    def test_long_goal_falls_to_dev(self):
        from backend.services.organization.plan import PlanBuilder
        goal = "This is a very long goal that exceeds the threshold " + "x" * 50
        ctx = OrganizationContext({"run_id": "r1", "goal": goal})
        pattern = PlanBuilder._classify(ctx, None, goal)
        assert pattern == "dev"

    def test_failures_override_to_retry(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Implement feature",
            "recent_turns": [
                {"failure": "Timeout"},
                {"failure": "Crash"},
            ],
        })
        # 2 failures → retry pattern wins over dev keywords
        pattern = PlanBuilder._classify(ctx, None, "Implement feature")
        assert pattern == "retry"

    def test_single_failure_not_enough_for_retry(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Implement feature",
            "recent_turns": [{"failure": "Timeout"}],
        })
        pattern = PlanBuilder._classify(ctx, None, "Implement feature")
        # Only 1 failure, goal says dev → dev
        assert pattern == "dev"

    def test_normal_goal_defaults_to_chat(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({"run_id": "r1", "goal": "How are you?"})
        pattern = PlanBuilder._classify(ctx, None, "How are you?")
        assert pattern == "chat"


# ── PlanBuilder step generation ──

class TestPlanGeneration:
    """PlanBuilder._generate produces correct steps per pattern."""

    def test_chat_generates_one_respond_step(self):
        from backend.services.organization.plan import PlanBuilder
        steps = PlanBuilder._generate("chat", "")
        assert len(steps) == 1
        assert steps[0].step_type == "respond"
        assert steps[0].action == OrganizationAction.RESPOND
        assert steps[0].role == "communicator"

    def test_dev_generates_three_steps(self):
        from backend.services.organization.plan import PlanBuilder
        steps = PlanBuilder._generate("dev", "Implement auth")
        assert len(steps) == 3
        types = [s.step_type for s in steps]
        assert types == ["plan", "execute", "review"]
        actions = [s.action for s in steps]
        assert actions == [
            OrganizationAction.PLAN,
            OrganizationAction.EXECUTE,
            OrganizationAction.REVIEW,
        ]

    def test_analysis_generates_two_steps(self):
        from backend.services.organization.plan import PlanBuilder
        steps = PlanBuilder._generate("analysis", "Research API")
        assert len(steps) == 2
        assert steps[0].step_type == "research"
        assert steps[0].action == OrganizationAction.TOOL_CALL
        assert steps[1].step_type == "respond"
        assert steps[1].action == OrganizationAction.RESPOND

    def test_retry_generates_review_then_execute(self):
        from backend.services.organization.plan import PlanBuilder
        steps = PlanBuilder._generate("retry", "Fix after crash")
        assert len(steps) == 2
        assert steps[0].step_type == "review"
        assert steps[0].action == OrganizationAction.REVIEW
        assert steps[1].step_type == "execute"
        assert steps[1].action == OrganizationAction.EXECUTE

    def test_unknown_pattern_falls_to_chat(self):
        from backend.services.organization.plan import PlanBuilder
        steps = PlanBuilder._generate("bogus", "")
        assert len(steps) == 1
        assert steps[0].step_type == "respond"


# ── PlanBuilder integration ──

class TestPlanBuilderBuild:
    """PlanBuilder.build() end-to-end."""

    def test_build_chat_plan(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({"run_id": "r1"})
        dummy_decide = lambda _ctx, _input: OrganizationAction.RESPOND
        plan = PlanBuilder().build(ctx, dummy_decide)
        assert plan.goal == ""
        assert len(plan.steps) == 1
        assert plan.steps[0].action == OrganizationAction.RESPOND
        assert "chat" in plan.reasoning.lower()

    def test_build_dev_plan(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Build new feature",
        })
        plan = PlanBuilder().build(ctx, None)
        assert plan.goal == "Build new feature"
        assert len(plan.steps) == 3
        assert plan.steps[0].step_type == "plan"
        assert "Development" in plan.reasoning

    def test_build_retry_plan(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Deploy service",
            "recent_turns": [
                {"failure": "Deploy failed"},
                {"failure": "Build error"},
            ],
        })
        plan = PlanBuilder().build(ctx, None)
        assert len(plan.steps) == 2
        assert plan.steps[0].step_type == "review"
        assert "Retry" in plan.reasoning

    def test_build_analysis_plan(self):
        from backend.services.organization.plan import PlanBuilder
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Analyze database performance",
        })
        plan = PlanBuilder().build(ctx, None)
        assert len(plan.steps) == 2
        assert plan.steps[0].step_type == "research"
        assert "analysis" in plan.reasoning.lower()


# ── engine.plan() integration ──

class TestEnginePlan:
    """OrganizationDecisionEngine.plan() delegates to PlanBuilder."""

    def test_plan_returns_organization_plan(self):
        from backend.services.organization.engine import OrganizationDecisionEngine
        from backend.services.organization.plan import OrganizationPlan

        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({"run_id": "r1"})
        result = eng.plan(ctx)
        assert isinstance(result, OrganizationPlan)
        assert len(result.steps) == 1  # chat

    def test_plan_with_dev_goal(self):
        from backend.services.organization.engine import OrganizationDecisionEngine
        from backend.services.organization.plan import OrganizationPlan

        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Refactor the authentication module",
        })
        result = eng.plan(ctx)
        assert isinstance(result, OrganizationPlan)
        assert len(result.steps) == 3  # dev: plan, execute, review

    def test_plan_with_retry_context(self):
        from backend.services.organization.engine import OrganizationDecisionEngine
        from backend.services.organization.plan import OrganizationPlan

        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Complete deployment",
            "recent_turns": [
                {"failure": "Timeout"},
                {"failure": "Auth error"},
            ],
        })
        result = eng.plan(ctx)
        assert isinstance(result, OrganizationPlan)
        assert len(result.steps) == 2  # retry: review, execute

    def test_plan_with_chinese_dev_goal(self):
        from backend.services.organization.engine import OrganizationDecisionEngine
        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "实现用户登录功能",
        })
        result = eng.plan(ctx)
        assert len(result.steps) == 3
        assert "Development" in result.reasoning

    def test_plan_each_step_has_all_fields(self):
        from backend.services.organization.engine import OrganizationDecisionEngine
        from backend.services.organization.plan import OrganizationPlan

        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "r1",
            "goal": "Build reporting dashboard",
        })
        plan = eng.plan(ctx)
        for step in plan.steps:
            assert step.step_type
            assert step.action
            assert step.role
            assert step.reason
            assert 0.0 <= step.confidence <= 1.0

    def test_plan_empty_goal_is_safe(self):
        from backend.services.organization.engine import OrganizationDecisionEngine
        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({"run_id": "r1", "goal": "   "})
        result = eng.plan(ctx)
        assert len(result.steps) == 1  # whitespace-only goal → chat
        assert result.goal == ""

    def test_plan_does_not_modify_ctx(self):
        """plan() is read-only on context."""
        from backend.services.organization.engine import OrganizationDecisionEngine
        ctx = OrganizationContext({"run_id": "r1", "goal": "Test"})
        expected = ctx.to_dict()
        eng = OrganizationDecisionEngine()
        eng.plan(ctx)
        assert ctx.to_dict() == expected
