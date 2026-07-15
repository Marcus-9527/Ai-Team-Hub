"""executor.py — Teammate executor.

Delegates to existing agent workflows (run_engineer_workflow) or a
generic LLM call for non-engineer roles.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.services.runtime.agent import run_engineer_workflow
from backend.services.runtime.teammate_runner import resolve_api_key, detect_role

logger = logging.getLogger("teammate_runtime.executor")


async def call_executor(teammate: dict, plan: dict,
                        workspace_id: str = "") -> dict:
    """Execute a plan step using the teammate's role-appropriate workflow."""
    action = plan.get("action", "execute")
    description = plan.get("description", "")

    api_key = (await resolve_api_key(teammate))[0] or ""
    role = detect_role(teammate)

    if role == "engineer":
        return await run_engineer_workflow(
            teammate=teammate,
            task_description=description,
            workspace_id=workspace_id,
            api_key=api_key,
        )

    # ponytail: non-engineer roles fall through to summary-only.
    # Extend with reviewer/techlead workflows when needed.
    return {"summary": f"[{role}] {action}: {description[:100]}", "status": "ok"}
