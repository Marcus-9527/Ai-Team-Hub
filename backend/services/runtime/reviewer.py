"""
runtime/reviewer.py — Reviewer Runtime (one function, same execution chain).

Reads the REAL git diff the Engineer produced in the workspace, runs the
test command through the same allow-listed tool runtime, and asks the
Reviewer teammate (loaded with its own identity) for an approve/reject verdict.

Reuses stream_ai_response + resolve_api_key — no second execution chain.
"""

import json
import re
from typing import Optional

from backend.services.ai_service import stream_ai_response
from backend.services.runtime.teammate_runner import resolve_api_key
from backend.services.runtime.tool_runtime import (
    execute_tool,
    git_work_diff,
)

REVIEW_PROMPT = """\
You are the REVIEWER. Audit the Engineer's git diff and test output.
Decide: APPROVE (ship it) or REJECT (list concrete blockers).
Reply ONLY with a JSON object:
{"verdict": "approve"|"reject", "summary": str, "blockers": [str]}
Rules: reject if tests fail, or if there are security issues (eval/exec of
untrusted input), hardcoded secrets, or changes that don't match the task."""


async def run_reviewer_workflow(
    teammate: dict,
    task_description: str,
    workspace_id: str,
    git_commit: str = "",
    api_key: str = "",
    base_url: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """
    Run the Reviewer workflow. Returns:
        {
          "verdict": "approve" | "reject",
          "summary": str,
          "blockers": [str],
          "git_commit": str,
          "tests_passed": bool,
          "diff": str,
        }
    """
    api_key = api_key or (await resolve_api_key(teammate))[0] or ""
    provider = provider or teammate.get("model_provider", "openrouter")
    model = model or teammate.get("model_name", "openrouter/auto")

    # 1. Read the REAL artifact the Engineer left in the workspace.
    diff = git_work_diff(workspace_id)

    # 2. Run tests via the SAME allow-listed tool runtime.
    test_out = await execute_tool(
        {"tool": "shell_exec", "args": {"command": "pytest"}}, workspace_id,
        subject="reviewer"
    )
    test_text = ((test_out.get("output") or {}).get("stdout", "") or "")[:4000]

    user_msg = (
        f"TASK:\n{task_description}\n\n"
        f"ENGINEER COMMIT: {git_commit}\n\n"
        f"GIT DIFF:\n{diff}\n\n"
        f"TEST OUTPUT:\n{test_text}"
    )

    chunks = []
    async for c in stream_ai_response(
        system_prompt=(teammate.get("system_prompt", "") + "\n\n" + REVIEW_PROMPT),
        messages=[{"role": "user", "content": user_msg}],
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url or None,
        max_tokens=1024,
    ):
        chunks.append(c)

    text = "".join(chunks).strip()
    verdict = "reject"
    summary = text
    blockers: list[str] = []
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        v = str(data.get("verdict", "")).lower()
        verdict = "approve" if "approve" in v else "reject"
        summary = data.get("summary", text)
        blockers = data.get("blockers", []) or []
    except Exception:
        # Heuristic fallback: trust the tests if the model didn't speak JSON.
        verdict = "reject" if (
            "reject" in text.lower() or "fail" in test_text.lower()
        ) else "approve"

    return {
        "verdict": verdict,
        "summary": summary,
        "blockers": blockers,
        "git_commit": git_commit,
        "tests_passed": ("passed" in test_text.lower() or "ok" in test_text.lower()),
        "diff": diff,
    }
