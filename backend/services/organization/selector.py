"""TeammateSelector — deterministic identity-aware teammate selection.

Scores each candidate on capability_match (+50), skill_match (0-30),
and performance (0-20). No LLM, no new models.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TeammateSelector:
    """Identity-scored teammate selection for DELEGATE actions."""

    CAPABILITY_SCORE = 50
    SKILL_HIT_SCORE = 10
    SKILL_MAX = 30
    PERF_WEIGHT = 20

    def __init__(self, db: AsyncSession):
        self.db = db

    async def select(
        self,
        task_description: str,
        required_capabilities: list[str],
        members: Sequence[str],
        experience: Optional[list[dict]] = None,
    ) -> dict | None:
        """Score each member and return best candidate, or None.

        experience: list of past experience dicts with 'teammate' and 'result'.
        Returns: {teammate_id, score, reasons} or None.
        """
        if not members:
            return None

        from backend.services.organization.identity import TeammateIdentityService

        id_svc = TeammateIdentityService(self.db)
        candidates: list[dict] = []

        # Build teammate→experience lookup: {teammate: {result, lesson}}
        exp_map: dict[str, dict] = {}
        if experience:
            for e in experience:
                tm = e.get("teammate", "")
                if tm:
                    exp_map[tm] = {
                        "result": e.get("result", ""),
                        "lesson": e.get("lesson", ""),
                    }

        for mid in members:
            identity = await id_svc.get_identity(mid)
            score = 0.0
            reasons: list[str] = []

            # ── Capability match: +50 if intersection —─
            caps = set(identity.get("capabilities", []))
            req = set(required_capabilities)
            matched = caps & req
            if matched:
                score += self.CAPABILITY_SCORE
                reasons.append(f"capability matched: {', '.join(sorted(matched))}")

            # ── Skill match: +10 per hit (max 30) —─
            skills = [s.lower() for s in identity.get("skills", [])]
            desc_lower = task_description.lower()
            words = [w for w in desc_lower.split() if len(w) > 2]
            hits = 0
            for s in skills:
                if any(w in s for w in words):
                    hits += 1
            skill_pt = min(hits * self.SKILL_HIT_SCORE, self.SKILL_MAX)
            if skill_pt > 0:
                score += skill_pt
                reasons.append(f"skill match: +{int(skill_pt)}")

            # ── Performance: success_rate * 20 —─
            perf = identity.get("recent_performance", {})
            total = perf.get("total_actions", 0)
            if total > 0:
                rate = perf.get("completed", 0) / total
                perf_pt = round(rate * self.PERF_WEIGHT, 1)
                score += perf_pt
                if perf_pt > 0:
                    reasons.append(f"performance: +{perf_pt}")

            # ── Experience bonus: +20 if teammate succeeded on similar task —─
            exp_bonus = 0
            if mid in exp_map:
                result = exp_map[mid].get("result", "")
                if result and "fail" not in result.lower() and "error" not in result.lower():
                    exp_bonus = 20
                    reasons.append("experience: +20 (similar task succeeded)")
            if exp_bonus:
                score += exp_bonus

            candidates.append({
                "teammate_id": mid,
                "score": round(score, 1),
                "reasons": reasons,
            })

        if not candidates:
            return None

        best = max(candidates, key=lambda c: c["score"])
        if best["score"] <= 0:
            return None
        return best
