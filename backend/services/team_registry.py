"""
team_registry.py — Teammate registration and routing.  [DEPRECATED]

.. deprecated::
    Not imported by any active code path. Teammate contexts are now built
    inline via `services/team_context.py` and `services/kernel/context_kernel`
    (the latter also deprecated/merged). Registration/routing logic here is dead.

    Migration: teammate metadata flows through the DB models (`backend/models.py`)
    and `services/maeos.py`. This file is retained for reference only and will be
    removed in a later cleanup.
"""

import logging
from typing import Optional
from pathlib import Path
from backend.services.team_context import TeammateContext, TeammateRole

logger = logging.getLogger("team_registry")

BASE_DIR = Path(__file__).parent.parent / "data" / "teammates"
MEMORY_DIR = BASE_DIR / "memory"
HISTORY_DIR = BASE_DIR / "history"
VECTOR_DIR = BASE_DIR / "vector_db"


def _ensure_dirs():
    for teammate_id in ["teammate_a", "teammate_b", "teammate_c", "teammate_j"]:
        (MEMORY_DIR / teammate_id).mkdir(parents=True, exist_ok=True)
        (HISTORY_DIR / teammate_id).mkdir(parents=True, exist_ok=True)
        (VECTOR_DIR / teammate_id).mkdir(parents=True, exist_ok=True)


_ensure_dirs()

COMMON_STYLE = """
[STYLE RULES]
1. 回复要简短。像微信聊天，不是写文章。
2. 不要列 1/2/3 点，不要加粗标题。
3. 一句话能说清的不写三段。
4. 像跟朋友聊天一样，口语化，随意。
5. 回复长度控制在 50-150 字以内。
"""

TEAMMATE_DEFINITIONS: dict[str, dict] = {
    "teammate_a": {
        "role": TeammateRole.ANALYSIS,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Teammate A (Analysis Teammate).\n{COMMON_STYLE}",
        "tools": ["search", "analyze", "summarize"],
    },
    "teammate_b": {
        "role": TeammateRole.CODE,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Teammate B (Code Teammate).\n{COMMON_STYLE}",
        "tools": ["code_gen", "code_review", "debug", "test"],
    },
    "teammate_c": {
        "role": TeammateRole.REASONING,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Teammate C (Reasoning Teammate).\n{COMMON_STYLE}",
        "tools": ["reason", "decompose", "evaluate", "decide"],
    },
    "teammate_j": {
        "role": TeammateRole.JUDGE,
        "system_prompt": f"[IDENTITY LOCK]\nYou are Teammate J (Judge Teammate).\n{COMMON_STYLE}",
        "tools": ["evaluate", "rank", "merge", "decide"],
    },
}


def get_teammate_context(teammate_id: str) -> Optional[TeammateContext]:
    if teammate_id not in TEAMMATE_DEFINITIONS:
        return None
    d = TEAMMATE_DEFINITIONS[teammate_id]
    return TeammateContext(
        teammate_id=teammate_id,
        role=d["role"],
        system_prompt=d["system_prompt"],
        memory_namespace=teammate_id,
        history_namespace=teammate_id,
        retrieval_namespace=teammate_id,
        tools_subset=d["tools"],
    )


def get_all_teammate_ids() -> list[str]:
    return list(TEAMMATE_DEFINITIONS.keys())


def get_teammates_for_intent(intent: str) -> list[str]:
    routing_rules = {
        "analysis": ["teammate_a", "teammate_c"],
        "code": ["teammate_b"],
        "reasoning": ["teammate_c"],
        "final": ["teammate_a"],
        "judge": ["teammate_j"],
        "complex": ["teammate_a", "teammate_b", "teammate_c"],
    }
    return routing_rules.get(intent, ["teammate_a"])


def get_namespace(teammate_id: str):
    from backend.services.memory_namespaces import get_namespace as _get_ns
    return _get_ns(teammate_id)
