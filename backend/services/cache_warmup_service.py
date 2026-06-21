"""
cache_warmup_service.py — Cache warmup state tracking.
"""

import logging
import asyncio
from typing import Optional

logger = logging.getLogger("cache_warmup")

# In-memory warmup state
_deepseek_warmed: dict[str, bool] = {}
_deepseek_warmed_lock = asyncio.Lock()


def is_warmed_up(teammate_id: str, channel_id: str) -> bool:
    """Check if cache is warmed up for this teammate+channel."""
    key = f"{teammate_id}:{channel_id}"
    return _deepseek_warmed.get(key, False)


def mark_warmed_up(teammate_id: str, channel_id: str) -> None:
    """Mark cache as warmed up."""
    key = f"{teammate_id}:{channel_id}"
    _deepseek_warmed[key] = True


def invalidate_warmup(teammate_id: str) -> None:
    """Invalidate all warmup state for a teammate."""
    keys_to_remove = [k for k in _deepseek_warmed if k.startswith(f"{teammate_id}:")]
    for k in keys_to_remove:
        del _deepseek_warmed[k]
