"""
memory_store.py — STUB MODULE - NO RUNTIME EFFECT

⚠️ STUB — This module has no active runtime consumers.
    It is not imported by any execution path in the current system.
    Do not extend; memory features are not wired into the FSM pipeline.
"""

import logging
from typing import Optional

logger = logging.getLogger("memory_store")


class MemoryStore:
    """Simple memory store (file-based)."""

    def get_latest_summary(self, channel_id: str, teammate_id: str) -> Optional[str]:
        return None

    def search_semantic(self, channel_id: str, teammate_id: str, query: str, top_k: int = 3) -> list[str]:
        return []


_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
