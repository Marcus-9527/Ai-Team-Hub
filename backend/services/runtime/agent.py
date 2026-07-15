"""
runtime/agent.py — Minimal Engineer workflow.

Fixed loop, bounded autonomy (no open-ended agent):
    1. analyze task
    2. read code (file_read)
    3. modify files (file_write)
    4. run tests (shell_exec: pytest | npm test)
    5. report result

The teammate's identity (system_prompt) is reused verbatim from chat — one persona.
Tool calls are parsed from the model output (fenced <TOOL> blocks) and executed
through the unified tool_runtime.execute_tool(). The loop is capped at MAX_ROUNDS.

ponytail: no ReAct framework, no planner graph. A bounded while-loop + a parser.
"""

import json
import logging
import re
from typing import Any, Optional

from backend.services.runtime.teammate_runner import (
    resolve_api_key,
    detect_role,
)
from backend.services.runtime.tool_runtime import (
    execute_tool,
    workspace_root,
    git_ensure,
    git_commit,
)
from backend.services.ai_service import stream_ai_response

logger = logging.getLogger("runtime.agent")

MAX_ROUNDS = 6

_TOOL_INSTRUCTIONS = """\
You are operating as a software engineer inside a constrained workspace.
Follow this fixed workflow and stop when done:
  1. ANALYZE the task.
  2. READ the relevant files with file_read to understand the code.
  3. MODIFY files with file_write (full file content, create or overwrite).
  4. RUN tests with shell_exec (commands: "pytest", "npm test", "git status", "git diff")
     or use code_exec for arbitrary scripts (python3/node/bash, 30s timeout).
  5. REPORT the result in plain text (no <TOOL> blocks).

Your workspace root is: {ws_root}
You may ONLY access files under that root. Paths are relative to it.

To use a tool, emit ONE OR MORE fenced blocks exactly like this:
<TOOL>
{{"tool": "file_read", "args": {{"path": "backend/auth.py"}}}}
</TOOL>

<TOOL>
{{"tool": "file_write", "args": {{"path": "backend/auth.py", "content": "<full new file text>"}}}}
</TOOL>

<TOOL>
{{"tool": "shell_exec", "args": {{"command": "pytest"}}}}
</TOOL>

First think briefly, then act. When the task is complete, reply with a final
plain-text report (summary of changes + test result). Do NOT emit <TOOL> blocks
in your final report.
"""


def _parse_tool_calls(text: str) -> list[dict]:
    """Extract <TOOL>...</TOOL> JSON blocks from model output."""
    calls = []
    for m in re.finditer(r"<TOOL>\s*(.*?)\s*</TOOL>", text, re.DOTALL):
        raw = m.group(1).strip()
        try:
            calls.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning(f"[AGENT] dropped malformed tool call: {raw[:120]}")
    return calls


async def run_engineer_workflow(
    teammate: dict,
    task_description: str,
    workspace_id: str,
    api_key: str = "",
    base_url: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """
    Run the Engineer workflow. Returns the structured TaskOutput:
        {
          "summary": str,
          "files_changed": [str],
          "commands_run": [str],
          "git_commit": str,
          "test_result": str,
        }
    """
    api_key = api_key or (await resolve_api_key(teammate))[0] or ""
    provider = provider or teammate.get("model_provider", "openrouter")
    model = model or teammate.get("model_name", "openrouter/auto")
    ws_root = workspace_root(workspace_id)

    # Git Workspace Flow: baseline repo + a feature branch for this task.
    # The Reviewer later diffs this branch's history.
    feat_branch = f"feat/{workspace_id}"
    git_ensure(workspace_id, branch=feat_branch)

    system_prompt = (teammate.get("system_prompt") or "You are a helpful engineer.") \
        + "\n\n" + _TOOL_INSTRUCTIONS.format(ws_root=ws_root)

    messages = [
        {"role": "user", "content": f"TASK:\n{task_description}\n\nBegin by analyzing the task."}
    ]

    files_changed: list[str] = []
    commands_run: list[str] = []
    git_commit = ""
    test_result = ""
    last_text = ""

    for _ in range(MAX_ROUNDS):
        # Collect model response
        chunks = []
        async for chunk in stream_ai_response(
            system_prompt=system_prompt,
            messages=messages,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            max_tokens=4096,
        ):
            chunks.append(chunk)
        text = "".join(chunks).strip()
        last_text = text
        messages.append({"role": "assistant", "content": text})

        calls = _parse_tool_calls(text)
        if not calls:
            # No tool calls → treat as final report.
            break

        # Execute each tool call and feed results back.
        results_parts: list[str] = []
        for call in calls:
            role = teammate.get("role", "engineer") if isinstance(teammate, dict) else "engineer"
            res = await execute_tool(call, workspace_id, subject=role)
            if res["ok"]:
                tool = call.get("tool")
                args = call.get("args", {})
                if tool == "file_write":
                    p = args.get("path", "")
                    if p not in files_changed:
                        files_changed.append(p)
                elif tool == "shell_exec":
                    cmd = args.get("command", "")
                    commands_run.append(cmd)
                    if cmd.strip() == "pytest":
                        test_result = (res["output"] or {}).get("stdout", "")
                    elif cmd.strip() == "git commit":
                        # capture commit hash from stdout
                        m = re.search(r"\[[^\]]+\s([0-9a-f]{7,40})\]", (res["output"] or {}).get("stdout", ""))
                        if m:
                            git_commit = m.group(1)

            # Engineer auto-commits every round of edits to its feature branch.
            if files_changed:
                commit = await git_commit(
                    workspace_id, f"engineer: {task_description[:60]}"
                )
                if commit["ok"] and not git_commit:
                    git_commit = commit["hash"]
                results_parts.append(f"<TOOL_RESULT>{json.dumps(res, ensure_ascii=False)}</TOOL_RESULT>")
            else:
                results_parts.append(f"<TOOL_RESULT>{json.dumps(res, ensure_ascii=False)}</TOOL_RESULT>")

        messages.append({
            "role": "user",
            "content": "Tool results:\n" + "\n".join(results_parts)
            + "\n\nContinue the workflow (next tool call or final report).",
        })

    return {
        "summary": last_text,
        "files_changed": files_changed,
        "commands_run": commands_run,
        "git_commit": git_commit,
        "test_result": test_result,
    }
