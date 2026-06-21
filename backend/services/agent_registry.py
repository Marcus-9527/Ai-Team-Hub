"""
agent_registry.py — Agent registration and routing.
"""

import logging
from typing import Optional
from pathlib import Path
from backend.services.agent_context import AgentContext, AgentRole

logger = logging.getLogger("agent_registry")

BASE_DIR = Path(__file__).parent.parent / "data" / "agents"
MEMORY_DIR = BASE_DIR / "memory"
HISTORY_DIR = BASE_DIR / "history"
VECTOR_DIR = BASE_DIR / "vector_db"


def _ensure_dirs():
    for agent_id in ["agent_a", "agent_b", "agent_c", "agent_j"]:
        (MEMORY_DIR / agent_id).mkdir(parents=True, exist_ok=True)
        (HISTORY_DIR / agent_id).mkdir(parents=True, exist_ok=True)
        (VECTOR_DIR / agent_id).mkdir(parents=True, exist_ok=True)


_ensure_dirs()

COMMON_STYLE = """
[STYLE RULES]
1. 回复要简短。像微信聊天，不是写文章。
2. 不要列 1/2/3 点，不要加粗标题。
3. 一句话能说清的不写三段。
4. 像跟朋友聊天一样，口语化，随意。
5. 回复长度控制在 50-150 字以内。
"""

AGENT_DEFINITIONS: dict[str, dict] = {
    "agent_a": {
        "role": AgentRole.ANALYSIS,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Agent A (Analysis Agent).\n{COMMON_STYLE}",
        "tools": ["search", "analyze", "summarize"],
    },
    "agent_b": {
        "role": AgentRole.CODE,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Agent B (Code Agent).\n{COMMON_STYLE}",
        "tools": ["code_gen", "code_review", "debug", "test"],
    },
    "agent_c": {
        "role": AgentRole.REASONING,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Agent C (Reasoning Agent).\n{COMMON_STYLE}",
        "tools": ["reason", "decompose", "evaluate", "decide"],
    },
    "agent_j": {
        "role": AgentRole.JUDGE,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Agent J (Judge Agent).\n{COMMON_STYLE}",
        "tools": ["evaluate", "rank", "merge", "decide"],
    },
}


def get_agent_context(agent_id: str) -> Optional[AgentContext]:
    if agent_id not in AGENT_DEFINITIONS:
        return None
    d = AGENT_DEFINITIONS[agent_id]
    return AgentContext(
        agent_id=agent_id,
        role=d["role"],
        system_prompt=d["system_prompt"],
        memory_namespace=agent_id,
        history_namespace=agent_id,
        retrieval_namespace=agent_id,
        tools_subset=d["tools"],
    )


def get_all_agent_ids() -> list[str]:
    return list(AGENT_DEFINITIONS.keys())


def get_agents_for_intent(intent: str) -> list[str]:
    routing_rules = {
        "analysis": ["agent_a", "agent_c"],
        "code": ["agent_b"],
        "reasoning": ["agent_c"],
        "final": ["agent_a"],
        "judge": ["agent_j"],
        "complex": ["agent_a", "agent_b", "agent_c"],
    }
    return routing_rules.get(intent, ["agent_a"])


def get_namespace(agent_id: str):
    from backend.services.memory_namespaces import get_namespace as _get_ns
    return _get_ns(agent_id)
