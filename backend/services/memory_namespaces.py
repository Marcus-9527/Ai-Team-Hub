"""
memory_namespaces.py — Per-teammate memory namespaces.

Used by the memory layer to scope memory entries per teammate.
"""

import logging
from typing import Optional

logger = logging.getLogger("memory_namespaces")


class MemoryNamespace:
    """Per-teammate memory namespace."""

    def __init__(self, teammate_id: str):
        self.teammate_id = teammate_id

    def write_history(self, role: str, content: str) -> None:
        pass

    def write_episodic(self, role: str, content: str) -> None:
        pass


_namespaces: dict[str, MemoryNamespace] = {}


def get_namespace(teammate_id: str) -> MemoryNamespace:
    if teammate_id not in _namespaces:
        _namespaces[teammate_id] = MemoryNamespace(teammate_id)
    return _namespaces[teammate_id]
