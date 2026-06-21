"""
memory_namespaces.py — STUB MODULE - NO RUNTIME EFFECT

⚠️ STUB — This module has no active runtime consumers.
    It is not imported by any execution path in the current system.
    Do not extend; memory features are not wired into the FSM pipeline.
"""

import logging
from typing import Optional

logger = logging.getLogger("memory_namespaces")


class MemoryNamespace:
    """Per-agent memory namespace."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    def write_history(self, role: str, content: str) -> None:
        pass

    def write_episodic(self, role: str, content: str) -> None:
        pass


_namespaces: dict[str, MemoryNamespace] = {}


def get_namespace(agent_id: str) -> MemoryNamespace:
    if agent_id not in _namespaces:
        _namespaces[agent_id] = MemoryNamespace(agent_id)
    return _namespaces[agent_id]
