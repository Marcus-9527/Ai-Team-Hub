"""
runtime/agent.py — Minimal Engineer workflow (AgentLoop edition).

替代旧代码：
  - _parse_tool_calls()  —— 已删除（正则解析 <TOOL>...</TOOL>）
  - _TOOL_INSTRUCTIONS    —— 已删除（纯文本工具说明 → provider 原生 tool_calls）
  - run_engineer_workflow() 内循环 —— 已替换为 AgentLoop.run()

验收标准：
  - 工具调用走 provider 原生 tool_calls，不再解析 <TOOL>...</TOOL> 文本
  - on_tool_call 回调保持 side-effect 追踪（files_changed / commands_run）
    和自动 git 提交行为
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from backend.services.runtime.agent_loop import AgentLoop, AgentLoopResult
from backend.services.runtime.llm_client_and_tools import (
    create_llm_client,
    ToolExecutorAdapter,
)
from backend.services.organization.capability import CapabilityRegistry
from backend.services.runtime.teammate_runner import (
    resolve_api_key,
    detect_role,
)
from backend.services.runtime.tool_runtime import (
    git_ensure,
    git_commit,
)

logger = logging.getLogger("runtime.agent")

MAX_ROUNDS = 6

_SYSTEM_INSTRUCTIONS = """\
You are operating as a software engineer inside a constrained workspace.
Follow this fixed workflow and stop when done:
  1. ANALYZE the task.
  2. READ the relevant files with file_read to understand the code.
  3. MODIFY files with file_write (full file content, create or overwrite).
  4. RUN tests with shell_exec (commands: "pytest", "npm test", "git status", "git diff")
     or use code_exec for arbitrary scripts (python3/node/bash, 30s timeout).
  5. REPORT the result in plain text (no tool calls).

Your workspace root is: {ws_root}
You may ONLY access files under that root. Paths are relative to it.

All tool calls must use the available tools. Do NOT use <TOOL> fenced blocks.
"""


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
    Run the Engineer workflow via AgentLoop (native tool_calls).

    Returns the structured TaskOutput:
        {
          "summary": str,
          "files_changed": [str],
          "commands_run": [str],
          "git_commit": str,
          "test_result": str,
        }
    """
    # ── Resolve credentials ──
    if not api_key:
        ak, bu, prov, fb_model = await resolve_api_key(teammate)
        api_key = ak or ""
        base_url = base_url or bu or ""
        provider = provider or prov or teammate.get("model_provider", "openrouter")
        model = model or fb_model or teammate.get("model_name", "openrouter/auto")
    else:
        provider = provider or teammate.get("model_provider", "openrouter")
        model = model or teammate.get("model_name", "openrouter/auto")

    ws_root = _ws_root(workspace_id)

    # ── Git workspace setup ──
    feat_branch = f"feat/{workspace_id}"
    git_ensure(workspace_id, branch=feat_branch)

    system_prompt = (teammate.get("system_prompt") or "You are a helpful engineer.") \
        + "\n\n" + _SYSTEM_INSTRUCTIONS.format(ws_root=ws_root)

    # ── Brain context: member experience + team state + project facts ──
    try:
        from backend.services.brain.brain_loader import get_brain_loader
        brain = await get_brain_loader().build_prompt(
            teammate_id=teammate.get("id", ""),
            workspace_id=workspace_id,
            query=task_description,
            recent_memory_limit=5,
        )
        if brain:
            system_prompt = brain + "\n\n" + system_prompt
    except Exception:
        logger.debug("[engineer] brain context skipped", exc_info=True)

    messages = [
        {"role": "user", "content": f"TASK:\n{task_description}\n\nBegin by analyzing the task."}
    ]

    # ── Side-effect tracking (replaces old inline logic) ──
    files_changed: list[str] = []
    commands_run: list[str] = []
    git_commit_hash = ""
    test_result = ""

    async def _on_tool_call(tc, tr):
        nonlocal git_commit_hash, test_result
        if tr.is_error:
            return
        name = tc.name
        args = tc.arguments

        if name == "file_write":
            p = args.get("path", "")
            if p not in files_changed:
                files_changed.append(p)
            # Auto-commit after each file write (per-round behavior preserved)
            c = await asyncio.to_thread(git_commit, workspace_id, f"engineer: {task_description[:60]}")
            if c.get("ok") and not git_commit_hash:
                git_commit_hash = c["hash"]

        elif name == "shell_exec":
            cmd = args.get("command", "")
            commands_run.append(cmd)
            if cmd.strip() == "pytest":
                # tr.content is json-dumped shell_exec output
                import json
                try:
                    shell_out = json.loads(tr.content)
                    test_result = shell_out.get("stdout", "")
                except (json.JSONDecodeError, TypeError):
                    test_result = tr.content

    # ── Run AgentLoop ──
    llm_client = create_llm_client(
        api_key=api_key, model=model, provider=provider, base_url=base_url or "",
    )
    executor = ToolExecutorAdapter()
    role = detect_role(teammate)

    # Resolve tools from Organization CapabilityRegistry
    cap_reg = CapabilityRegistry()
    tools = cap_reg.resolve_tools(role)

    loop = AgentLoop(llm_client=llm_client, tool_executor=executor, max_turns=MAX_ROUNDS)
    result: AgentLoopResult = await loop.run(
        system_prompt=system_prompt,
        messages=messages,
        tools=tools,
        workspace_id=workspace_id,
        subject=role,
        on_tool_call=_on_tool_call,
    )

    # ── Final commit if any changes remain uncommitted ──
    if files_changed and not git_commit_hash:
        c = await asyncio.to_thread(git_commit, workspace_id, f"engineer: {task_description[:60]}")
        if c.get("ok"):
            git_commit_hash = c["hash"]

    return {
        "summary": result.final_text,
        "files_changed": files_changed,
        "commands_run": commands_run,
        "git_commit": git_commit_hash,
        "test_result": test_result,
    }


def _ws_root(workspace_id: str) -> str:
    """Sync re-export of tool_runtime.workspace_root to avoid circular deps."""
    from backend.services.runtime.tool_runtime import workspace_root as _wr
    return _wr(workspace_id)
