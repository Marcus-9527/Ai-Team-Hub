"""reflection.py — Teammate reflection.

Delegates to ReflectionService for structured lesson generation.
Decides whether the goal is achieved (should_stop) based on result.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("teammate_runtime.reflection")


async def call_reflection(teammate_id: str, plan: dict,
                          exec_result: dict) -> dict:
    """Analyse execution result and decide whether to continue.

    Returns:
        {
            "should_stop": bool,
            "decision": str,      # brief decision summary
            "summary": str,       # full summary if goal achieved
        }
    """
    if not exec_result:
        return {"should_stop": True, "decision": "no result — stop",
                "summary": ""}

    summary = exec_result.get("summary", "")
    files_changed = exec_result.get("files_changed", [])
    test_result = exec_result.get("test_result", "")

    # ponytail: simple stop conditions — goal summary or test success.
    # Add LLM-based goal-achieved check when needed.
    should_stop = False
    decision_parts = []

    if test_result and "FAILED" not in test_result.upper():
        decision_parts.append("tests passed")
        should_stop = True
    elif files_changed and not test_result:
        # Changes made without tests — allow one more round for testing
        decision_parts.append("files changed, no test result yet")

    if should_stop:
        decision_parts.append("goal achieved")
    else:
        decision_parts.append("continue")

    return {
        "should_stop": should_stop,
        "decision": ", ".join(decision_parts),
        "summary": summary,
    }
