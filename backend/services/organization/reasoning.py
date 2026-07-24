"""OrganizationReasoner — rule-based reasoning from state + experience.

Ponytail: reads already-computed OrganizationState and ctx.experience,
packages them into a structured reasoning dict.  No LLM, no new DB queries.
"""

from __future__ import annotations

from typing import Optional

from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_types import MemoryType


def reason(
    *,
    goal: str = "",
    members_info: Optional[dict] = None,
    experience: Optional[list[dict]] = None,
    successful_patterns: Optional[list[str]] = None,
    failure_patterns: Optional[list[str]] = None,
) -> dict:
    """Rule-based reasoning from org state + experience.

    Returns:
        {
            "decision_reason": str,
            "recommended_roles": list[str],
            "risk_factors": list[str],
            "confidence": float,
            "supporting_experience": list[dict],
        }
    """
    # Determine likely action from current state
    has_code_goal = "code" in goal.lower() or "fix" in goal.lower()
    has_goal = bool(goal)
    has_team = bool(members_info and len(members_info) >= 2)
    failure_count = len(failure_patterns or [])
    success_count = len(successful_patterns or [])

    # Decision reason
    if has_code_goal:
        decision_reason = "Code/debug goal detected"
    elif has_goal and has_team and success_count >= failure_count:
        decision_reason = "Goal + team capacity + success patterns"
    elif has_goal:
        decision_reason = "Goal driven"
    else:
        decision_reason = "Respond directly"

    # Recommended roles
    roles = ["generalist"]
    if has_code_goal:
        roles = ["developer"]
    elif has_goal and has_team:
        roles = ["orchestrator", "planner"]

    # Risk factors
    risk_factors: list[str] = []
    for fp in (failure_patterns or [])[:3]:
        risk_factors.append(f"Prior failure: {fp[:80]}")
    if failure_count > success_count:
        risk_factors.append("More failures than successes in history")
    if not has_team:
        risk_factors.append("Solo teammate — reduced capacity")

    # Confidence
    base = 0.5
    if success_count > 0:
        base += min(success_count * 0.08, 0.3)
    base -= min(failure_count * 0.05, 0.2)
    if has_goal:
        base += 0.1
    if has_team:
        base += 0.1
    confidence = round(max(0.1, min(0.99, base)), 2)

    # Supporting experience
    supporting_experience = [
        {"goal": e.get("goal", ""), "teammate": e.get("teammate", ""),
         "result": e.get("result", ""), "lesson": e.get("lesson", "")}
        for e in (experience or [])[:3]
    ]

    return {
        "decision_reason": decision_reason,
        "recommended_roles": roles,
        "risk_factors": risk_factors,
        "confidence": confidence,
        "supporting_experience": supporting_experience,
    }
