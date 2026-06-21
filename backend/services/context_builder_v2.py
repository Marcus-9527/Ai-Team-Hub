"""
context_builder_v2.py — LEGACY MODULE - DO NOT EXTEND

⚠️ LEGACY — Only used by coordinator.py (which is itself DEPRECATED).
    Do not add new functionality here. New orchestration uses orchestrator_fsm.py.
"""

from typing import Optional


def build_agent_context(agent_id: str, message: str) -> Optional[dict]:
    """Build agent context from storage."""
    from backend.services.agent_registry import get_agent_context
    ctx = get_agent_context(agent_id)
    if not ctx:
        return None
    return {
        "system": ctx.system_prompt,
        "memory_block": "",
        "history_block": "",
        "input": message,
        "tools": ctx.tools_subset,
        "identity_lock": ctx.identity_lock,
    }


def format_prompt_for_llm(context: dict) -> str:
    """Format context dict into LLM prompt string."""
    parts = [
        context.get("identity_lock", ""),
        "",
        context.get("system", ""),
        "",
        context.get("memory_block", ""),
        "",
        context.get("history_block", ""),
        "",
        f"[CURRENT USER INPUT]\n{context.get('input', '')}",
        "",
        "[AVAILABLE TOOLS]",
        ", ".join(context.get("tools", [])) or "none",
    ]
    return "\n".join(parts)
