"""OrganizationLoop — action decision engine.

Only decision (OrganizationDecisionEngine) + action generation.
Execution dispatch handled by OrganizationActionRouter.
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.organization.actions import OrganizationAction

logger = logging.getLogger(__name__)


class OrganizationDecisionEngine:
    """Deterministic action router — rules over LLM.

    Phase 14: context-aware scoring on top of keyword rules.
    Phase 16: lightweight plan generation via plan().
    """

    def decide(
        self,
        ctx: "OrganizationContext",
        user_input: str,
        *,
        organization_state: Optional[dict] = None,
        reasoning: Optional[dict] = None,
    ) -> OrganizationAction:
        """Map (context, input) → OrganizationAction via rule priority + context scores.

        Args:
            organization_state: Optional org-level intelligence dict from
                OrganizationStateManager.build_state(). Used only in context scoring.
                Default None → behaviour unchanged.
            reasoning: Optional OrganizationReasoner output. Risk factors further
                dampen DELEGATE in _score_context.
        """
        text = (user_input or "").strip()
        lower = text.lower()
        if self._has_code(text) or self._has_debug_keywords(lower):
            return OrganizationAction.EXECUTE
        if self._has_tool_keywords(lower):
            return OrganizationAction.TOOL_CALL
        if self._is_multi_step(lower, text):
            return OrganizationAction.DELEGATE
        if self._is_complete_signal(lower):
            return OrganizationAction.COMPLETE
        if not text or len(text) < 4:
            return OrganizationAction.RESPOND

        # ── Context-aware fallback (inputs > 20 chars, no keyword match) ──
        if len(text) > 20:
            ctx_scores = self._score_context(
                ctx, organization_state=organization_state, reasoning=reasoning,
            )
            if ctx_scores.get(OrganizationAction.DELEGATE, 0.0) > ctx_scores.get(OrganizationAction.RESPOND, 0.0):
                return OrganizationAction.DELEGATE
        return OrganizationAction.RESPOND

    def plan(self, ctx: "OrganizationContext") -> "OrganizationPlan":
        """Generate a lightweight multi-step plan from context.

        Uses decide() as the primary signal, then expands into
        plan steps via PlanBuilder. No runtime integration.
        """
        from backend.services.organization.plan import PlanBuilder
        return PlanBuilder().build(ctx, self.decide)

    @staticmethod
    def explain(
        action: OrganizationAction,
        ctx: Optional["OrganizationContext"] = None,
        *,
        organization_state: Optional[dict] = None,
        reasoning: Optional[dict] = None,
    ) -> tuple[str, float]:
        """Derive reason + confidence from a decided action and context.

        Confidence adjusted by context scores when ctx is provided.
        organization_state optionally boosts/dampens via _score_context.
        reasoning optionally overrides confidence via reasoner output.
        """
        reason, base_conf = {
            OrganizationAction.EXECUTE: ("Code or debug keywords detected", 0.90),
            OrganizationAction.TOOL_CALL: ("Tool keywords detected", 0.90),
            OrganizationAction.DELEGATE: ("Multi-step or long input detected", 0.85),
            OrganizationAction.COMPLETE: ("Completion signal detected", 0.90),
            OrganizationAction.RESPOND: ("Direct response or short input", 0.80),
        }.get(action, ("Unknown", 0.5))
        if ctx is not None:
            bias = OrganizationDecisionEngine._score_context(
                ctx, organization_state=organization_state, reasoning=reasoning,
            ).get(action, 0.0)
            conf = max(0.1, min(0.99, base_conf + bias))
        else:
            conf = base_conf
        # Reasoning confidence can override if higher (upgrade, never downgrade)
        if reasoning and reasoning.get("confidence", 0) > conf:
            conf = min(0.99, reasoning["confidence"])
        return reason, conf

    @staticmethod
    def suggested_roles(
        action: OrganizationAction,
        ctx: Optional["OrganizationContext"] = None,
    ) -> list[str]:
        """Derive suggested teammate roles from action type + context.

        Ponytail: static mapping, no LLM. ctx accepted for future
        context-aware role assignment.
        """
        _ = ctx  # ponytail: ctx accepted for future context-aware roles
        return {
            OrganizationAction.EXECUTE: ["developer"],
            OrganizationAction.DELEGATE: ["orchestrator", "planner"],
            OrganizationAction.TOOL_CALL: ["tool_user"],
            OrganizationAction.COMPLETE: ["reviewer"],
            OrganizationAction.RESPOND: ["communicator"],
        }.get(action, ["generalist"])

    @staticmethod
    def _score_context(
        ctx: "OrganizationContext",
        organization_state: Optional[dict] = None,
        reasoning: Optional[dict] = None,
    ) -> dict[OrganizationAction, float]:
        """Context-aware scoring — ponders goal, team, identity, failures, org state.

        Returns per-action score adjustments (positive = more likely).
        ponytail: simple additive scores, no ML, no deps.

        When organization_state (from OrganizationStateManager.build_state) is
        provided, additional signals (preferred roles, patterns, team profile)
        are factored in. Default None → pure Phase 14 behaviour unchanged.

        When reasoning (from OrganizationReasoner) is provided, risk factors
        further dampen DELEGATE.
        """
        scores: dict[OrganizationAction, float] = {a: 0.0 for a in OrganizationAction}
        if not ctx:
            return scores

        # 1. Active goal → prefer DELEGATE over RESPOND in ambiguous cases
        if ctx.goal:
            scores[OrganizationAction.DELEGATE] += 0.10
            scores[OrganizationAction.RESPOND] -= 0.05

        # 2. Solo teammate → can't delegate effectively
        if len(ctx.members or []) <= 1:
            scores[OrganizationAction.DELEGATE] -= 0.15
            scores[OrganizationAction.RESPOND] += 0.05

        # 3. Teammate identity → bias toward matching action types
        for info in (ctx.members_info or {}).values():
            role = (info or {}).get("role", "").lower()
            if "developer" in role or "engineer" in role:
                scores[OrganizationAction.EXECUTE] += 0.08
            if "orchestrator" in role or "planner" in role:
                scores[OrganizationAction.DELEGATE] += 0.08

        # 4. org experience (from ctx.experience — a dict)
        exp = ctx.experience or {}
        similar_tasks = exp.get("similar_tasks", [])
        if similar_tasks:
            scores[OrganizationAction.EXECUTE] += 0.05
            scores[OrganizationAction.DELEGATE] += 0.03

        # 5. Previous failures in recent turns → conservative (avoid DELEGATE)
        failures = 0
        for t in (ctx.recent_turns or []):
            if isinstance(t, dict) and t.get("failure"):
                failures += 1
        if failures > 0:
            dampen = min(failures, 3) * 0.08
            scores[OrganizationAction.DELEGATE] -= dampen
            scores[OrganizationAction.RESPOND] += dampen * 0.3

        # 6. Phase 18: OrganizationState intelligence (optional, additive)
        if organization_state:
            org = organization_state
            # Preferred roles → encourage delegation to proven roles
            if org.get("preferred_roles"):
                for info in (ctx.members_info or {}).values():
                    role = (info or {}).get("role", "").lower()
                    if role in org["preferred_roles"]:
                        scores[OrganizationAction.DELEGATE] += 0.05
                        break

            # Successful patterns → confidence in delegation
            if org.get("successful_patterns"):
                scores[OrganizationAction.DELEGATE] += 0.05

            # Failure patterns → cautious (avoid DELEGATE)
            if org.get("failure_patterns"):
                scores[OrganizationAction.DELEGATE] -= 0.05

            # Team strengths → slight execute / tool_call boost
            if org.get("team_strengths"):
                scores[OrganizationAction.EXECUTE] += 0.03

        # 7. Phase 20: Reasoning risk factors (optional, additive)
        if reasoning:
            risk_count = len(reasoning.get("risk_factors", []))
            if risk_count > 0:
                dampen = min(risk_count, 3) * 0.03
                scores[OrganizationAction.DELEGATE] -= dampen
                scores[OrganizationAction.EXECUTE] -= dampen * 0.3

        return scores

    @staticmethod
    def _has_code(text: str) -> bool:
        if "```" in text:
            return True
        if re.search(r"`[a-z_]\w*\s*\(", text):
            return True
        if re.search(r"[/\\][a-zA-Z0-9_\-]+[/\\]", text):
            return True
        return False

    @staticmethod
    def _has_debug_keywords(text: str) -> bool:
        kw = {
            "bug", "debug", "error", "traceback", "crash", "exception",
            "fix", "broken", "not working", "issue", "fail", "failed",
            "修复", "报错", "异常", "问题",
        }
        return any(k in text for k in kw)

    @staticmethod
    def _has_tool_keywords(text: str) -> bool:
        kw = {
            "run ", "execute ", "search ", "grep ",
            "tool:", "!tool", "!!",
        }
        return any(k in text for k in kw)

    @staticmethod
    def _is_multi_step(text: str, raw: str) -> bool:
        if len(text) > 300:
            return True
        step_kw = {
            "step 1", "first step", "plan", "roadmap",
            "multiple", "several", "sequence", "pipeline",
            "phase", "然后", "第一步", "步骤", "多个",
        }
        if any(k in text for k in step_kw):
            return True
        if raw.count("\n") >= 3 and ("\n- " in raw or "\n* " in raw):
            return True
        return False

    @staticmethod
    def _is_complete_signal(text: str) -> bool:
        kw = {
            "done", "complete", "finished", "all set",
            "that's it", "no more", "stop", "exit", "quit",
            "结束", "完成", "没有了",
        }
        return any(k in text for k in kw)


class OrganizationLoop:
    """Decision + action generation hub.

    Execution is routed through OrganizationActionRouter → OrganizationExecutor.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Unified run: decide → emit decision event ──

    async def run(
        self,
        ctx: "OrganizationContext",
        user_input: str,
        *,
        trigger_id: str = "",
        run_id: str = "",
        teammates: Optional[list[dict]] = None,
        channel_id: str = "",
        shared_attachment_context: Optional[dict] = None,
        force_action: Optional[OrganizationAction] = None,
    ) -> AsyncGenerator[str, None]:
        """Decision engine → action.decided event → dispatch via caller.

        Yields SSE chunks from RESPOND execution via inline service call.
        For DELEGATE/EXECUTE/TOOL_CALL, yields structured decision event
        so the caller (OrganizationActionRouter) can dispatch.
        """
        action = (
            force_action
            if force_action is not None
            else OrganizationDecisionEngine().decide(ctx, user_input)
        )
        reason_, confidence_ = OrganizationDecisionEngine.explain(action, ctx)
        roles_ = OrganizationDecisionEngine.suggested_roles(action, ctx)

        hooks = self._hooks()
        await hooks.emit_event(
            trigger_id, event_type="action.decided",
            payload={
                "run_id": run_id, "action": action.value,
                "reason": reason_, "confidence": confidence_,
                "suggested_roles": roles_,
            },
        )

        if action == OrganizationAction.RESPOND:
            from backend.services.team_collaboration import generate_team_response

            async for chunk in generate_team_response(
                teammates=teammates or [],
                user_message=user_input,
                channel_id=channel_id,
                shared_attachment_context=shared_attachment_context,
            ):
                yield chunk

        elif action == OrganizationAction.COMPLETE:
            yield "data: [DONE]\n\n"

        else:
            # EXECUTE / DELEGATE / TOOL_CALL — emit decision event for the caller (Router)
            yield json.dumps({
                "type": "action_decided",
                "action": action.value,
                "reason": reason_,
                "confidence": confidence_,
            }, ensure_ascii=False)

            if action == OrganizationAction.DELEGATE:
                from backend.services.task.task_orchestrator import TaskOrchestrator
                orch = TaskOrchestrator()
                await orch.start_task(
                    self.db, ctx.task_id or "", ctx.goal or user_input,
                    trigger_id=trigger_id,
                )
            else:
                logger.info(
                    "[OrgLoop] %s action decided — caller must dispatch",
                    action.value,
                )

    # ── helpers ──

    def _hooks(self):
        from backend.services.session.session_hooks import SessionHooks
        return SessionHooks(self.db)
