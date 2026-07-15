"""planner.py — Teammate planner.

Delegates to existing PlanningEngine or a simple LLM call.
Returns a plan dict with at least {"action": str, ...}.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.services.planner.planning_engine import PlanningEngine

logger = logging.getLogger("teammate_runtime.planner")

_engine: Optional[PlanningEngine] = None


def _get_engine() -> PlanningEngine:
    global _engine
    if _engine is None:
        _engine = PlanningEngine()
    return _engine


async def call_planner(teammate: dict, goal: str,
                       context: Optional[dict] = None) -> dict:
    """Produce a plan dict for this round.

    For simple goals, returns {"action": "execute", "description": goal}.
    For complex goals, delegates to PlanningEngine for DAG decomposition,
    then returns the first actionable step.

    Ponytail: single-step execute is the common case; full DAG planning
    only fires for multi-step goals. Add replanning loop when needed.
    """
    if not goal.strip():
        return {}

    ctx = context or {}
    actions_taken = ctx.get("actions_taken", [])

    # First round: try full planning engine for multi-step decomposition
    if not actions_taken:
        _engine = _get_engine()
        try:
            dag = await _engine.plan(goal, context=ctx)
            # Return first actionable node
            if dag.nodes:
                first = sorted(dag.nodes.items())[0][1]
                return {
                    "action": "execute",
                    "description": first.objective or goal,
                    "node_id": first.id,
                    "skills": first.required_skills or [],
                }
        except Exception as e:
            logger.info("[PLAN] full planning fell back: %s", e)

        # Fallback: direct execution
        return {"action": "execute", "description": goal, "skills": []}

    # Subsequent rounds: continue toward goal
    return {"action": "execute", "description": goal, "skills": []}
