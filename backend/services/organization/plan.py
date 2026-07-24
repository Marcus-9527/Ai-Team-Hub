"""OrganizationPlan — multi-step plan generation.

Phase 16: lightweight task planning on top of OrganizationDecisionEngine.
Ponytail: rules + scoring, no LLM, no runtime integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

from backend.services.organization.actions import OrganizationAction

if TYPE_CHECKING:
    from backend.services.organization.context import OrganizationContext


@dataclass
class PlanStep:
    """A single step in an organization plan."""
    step_type: str
    action: OrganizationAction
    role: str
    reason: str
    confidence: float


@dataclass
class OrganizationPlan:
    """Lightweight multi-step plan generated from context.

    Not executed — just planning.
    """
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    reasoning: str = ""


class PlanBuilder:
    """Generates multi-step plans from context.

    Uses OrganizationDecisionEngine.decide() as the primary signal,
    then expands into steps based on plan templates.
    """

    def build(
        self,
        ctx: "OrganizationContext",
        decide: Callable,
    ) -> OrganizationPlan:
        """Build a plan from context.

        Args:
            ctx: OrganizationContext with goal/members/experience/failures.
            decide: Callable(ctx, user_input) -> OrganizationAction.
                    Typically OrganizationDecisionEngine().decide.
        """
        goal = (ctx.goal or "").strip()

        # Classify plan pattern from context
        pattern = self._classify(ctx, decide, goal)

        # Generate steps for the pattern
        steps = self._generate(pattern, goal)

        # Build reasoning summary
        reasoning = self._reason(pattern, goal, ctx)

        return OrganizationPlan(goal=goal, steps=steps, reasoning=reasoning)

    # ── Plan pattern classification ──

    @staticmethod
    def _classify(
        ctx: "OrganizationContext",
        decide: Callable,
        goal: str,
    ) -> str:
        """Classify the plan pattern: chat|dev|analysis|retry."""

        # 1. Failures → retry pattern
        failures = 0
        for t in (ctx.recent_turns or []):
            if isinstance(t, dict) and t.get("failure"):
                failures += 1
        if failures >= 2:
            return "retry"

        # 2. No goal → simple chat
        if not goal:
            return "chat"

        # 3. Goal-driven: keyword classification
        lower = goal.lower()

        dev_kw = {
            "implement", "build", "develop", "code", "refactor",
            "fix", "debug", "create", "write", "add ", "feature",
            "优化", "实现", "开发", "修复", "重构",
        }
        if any(k in lower for k in dev_kw):
            return "dev"

        analysis_kw = {
            "analyze", "research", "investigate", "find",
            "search", "compare", "evaluate", "understand",
            "what is", "how does", "分析", "研究", "查找",
        }
        if any(k in lower for k in analysis_kw):
            return "analysis"

        # 4. Long multi-step goal → dev
        if len(goal) > 100:
            return "dev"

        return "chat"

    # ── Step generation ──

    @staticmethod
    def _generate(pattern: str, goal: str) -> list[PlanStep]:
        """Generate up to 3 plan steps for a given pattern."""

        templates = {
            "chat": [
                PlanStep(
                    step_type="respond",
                    action=OrganizationAction.RESPOND,
                    role="communicator",
                    reason="Short chat — direct response",
                    confidence=0.80,
                ),
            ],
            "dev": [
                PlanStep(
                    step_type="plan",
                    action=OrganizationAction.PLAN,
                    role="planner",
                    reason="Plan implementation approach",
                    confidence=0.85,
                ),
                PlanStep(
                    step_type="execute",
                    action=OrganizationAction.EXECUTE,
                    role="developer",
                    reason="Execute planned development",
                    confidence=0.80,
                ),
                PlanStep(
                    step_type="review",
                    action=OrganizationAction.REVIEW,
                    role="reviewer",
                    reason="Review and verify results",
                    confidence=0.75,
                ),
            ],
            "analysis": [
                PlanStep(
                    step_type="research",
                    action=OrganizationAction.TOOL_CALL,
                    role="tool_user",
                    reason="Research and gather information",
                    confidence=0.80,
                ),
                PlanStep(
                    step_type="respond",
                    action=OrganizationAction.RESPOND,
                    role="communicator",
                    reason="Present findings and conclusions",
                    confidence=0.75,
                ),
            ],
            "retry": [
                PlanStep(
                    step_type="review",
                    action=OrganizationAction.REVIEW,
                    role="reviewer",
                    reason="Review previous failure and root cause",
                    confidence=0.85,
                ),
                PlanStep(
                    step_type="execute",
                    action=OrganizationAction.EXECUTE,
                    role="developer",
                    reason="Re-execute with fixes for identified issues",
                    confidence=0.80,
                ),
            ],
        }

        return templates.get(pattern, templates["chat"])

    @staticmethod
    def _reason(pattern: str, goal: str, ctx: "OrganizationContext") -> str:
        """Generate human-readable reasoning for the plan."""
        if pattern == "chat":
            return "Simple chat without specific goal — direct respond"
        if pattern == "dev":
            return f"Development task: \"{goal}\" — plan, execute, review"
        if pattern == "analysis":
            return f"Analysis request: \"{goal}\" — research then respond"
        if pattern == "retry":
            fails = sum(
                1 for t in (ctx.recent_turns or [])
                if isinstance(t, dict) and t.get("failure")
            )
            return f"Retry after {fails} failure(s) — review root cause, then re-execute"
        return "Respond to user input"
