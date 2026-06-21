"""
agent_functions.py — Pure Function Agents

Each agent is a stateless pure function:
  input: structured JSON
  output: structured JSON only

No role explanation. No conversation style. No meta commentary.
No agent decides next step.
"""

import json
import time
import logging
from dataclasses import dataclass
from typing import Optional

from backend.services.ai_service import stream_ai_response

logger = logging.getLogger("agent_functions")


# ── Output Schema ──

@dataclass
class AgentOutput:
    """Pure function output — no extra fields, no conversation."""
    status: str       # "success" | "error"
    result: str       # main output
    reasoning: str    # brief reasoning (max 100 chars)

    def to_dict(self) -> dict:
        return {"status": self.status, "result": self.result, "reasoning": self.reasoning}


# ── JSON Output Schema (injected into every prompt) ──

OUTPUT_SCHEMA = '{"status":"success|error","result":"...","reasoning":"..."}'


# ── LLM Call Helper ──

async def _call_llm(
    system_prompt: str,
    user_message: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = None,
) -> str:
    """Call LLM and return raw text. Errors raised to orchestrator."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    full = ""
    async for chunk in stream_ai_response(
        system_prompt=system_prompt,
        messages=messages,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    ):
        full += chunk
    if not full:
        raise RuntimeError("LLM returned empty response")
    return full


def _parse_json_output(raw: str) -> AgentOutput:
    """Parse LLM response into AgentOutput. No fallback to raw text."""
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # Extract JSON
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return AgentOutput(status="error", result="", reasoning="No JSON found in response")
    try:
        data = json.loads(text[start:end + 1])
        return AgentOutput(
            status=data.get("status", "success"),
            result=data.get("result", ""),
            reasoning=data.get("reasoning", "")[:200],
        )
    except json.JSONDecodeError as e:
        return AgentOutput(status="error", result="", reasoning=f"JSON parse error: {e}")


# ── Planner (Pure Function) ──

PLANNER_SYSTEM = """You are a task decomposition function.

Input: a task description
Output: a structured plan JSON

Rules:
- Output ONLY valid JSON, no markdown, no extra text
- Result field must contain the structured plan
- Reasoning field must be under 100 characters
- Do not write code, do not analyze, do not make decisions
- Decompose into subtasks with: name, description, assigned_to, dependencies

Output format:
{"status":"result":"[plan JSON array]","reasoning":"[brief reason]"}"""


async def planner_fn(
    task: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = None,
) -> AgentOutput:
    """
    Pure function: task → plan JSON

    Input: task description string
    Output: AgentOutput with structured plan in result field
    """
    user_msg = f"Decompose this task into subtasks:\n{task}\n\nOutput JSON only: {OUTPUT_SCHEMA}"
    raw = await _call_llm(PLANNER_SYSTEM, user_msg, provider, model, api_key, base_url)
    return _parse_json_output(raw)


# ── Executor (Pure Function) ──

EXECUTOR_SYSTEM = """You are a code execution function.

Input: a plan JSON + original task
Output: execution result JSON

Rules:
- Output ONLY valid JSON, no markdown, no extra text
- Result field must contain the complete execution output
- Reasoning field must be under 100 characters
- Do not analyze, do not research, do not make decisions
- Implement exactly what the plan specifies

Output format:
{"status":"success","result":"[execution output]","reasoning":"[brief reason]"}"""


async def executor_fn(
    plan: dict,
    original_task: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = None,
) -> AgentOutput:
    """
    Pure function: plan JSON + task → execution result JSON

    Input: plan dict and original task string
    Output: AgentOutput with execution result in result field
    """
    plan_str = json.dumps(plan, ensure_ascii=False) if isinstance(plan, dict) else str(plan)
    user_msg = (
        f"Original task: {original_task}\n"
        f"Plan: {plan_str}\n\n"
        f"Execute the plan. Output JSON only: {OUTPUT_SCHEMA}"
    )
    raw = await _call_llm(EXECUTOR_SYSTEM, user_msg, provider, model, api_key, base_url)
    return _parse_json_output(raw)


# ── Reviewer (Pure Function) ──

REVIEWER_SYSTEM = """You are a code review function.

Input: execution result JSON + original task
Output: validation JSON

Rules:
- Output ONLY valid JSON, no markdown, no extra text
- Result field must contain: {"pass": true/false, "issues": [...], "coverage": "..."}
- Reasoning field must be under 100 characters
- Do not write code, do not fix code, do not analyze
- Only validate and report issues

Output format:
{"status":"success","result":"{\"pass\":true,\"issues\":[],\"coverage\":\"...\"}","reasoning":"[brief reason]"}"""


async def reviewer_fn(
    result: str,
    original_task: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = None,
) -> AgentOutput:
    """
    Pure function: result JSON + task → validation JSON

    Input: execution result string and original task string
    Output: AgentOutput with validation result in result field
    """
    # Truncate result to avoid token overflow
    truncated = result[:3000] if len(result) > 3000 else result
    user_msg = (
        f"Original task: {original_task}\n"
        f"Result to review:\n{truncated}\n\n"
        f"Review and validate. Output JSON only: {OUTPUT_SCHEMA}\n"
        f'Result must contain: {{"pass": true/false, "issues": [...], "coverage": "..."}}'
    )
    raw = await _call_llm(REVIEWER_SYSTEM, user_msg, provider, model, api_key, base_url)
    return _parse_json_output(raw)
