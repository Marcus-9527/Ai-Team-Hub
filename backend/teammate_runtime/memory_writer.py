"""memory_writer.py — Teammate memory writer.

Saves only:
  - action + result → EXECUTION memory
  - decision summary → DECISION memory (brain fragment)

No chain-of-thought persistence.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_types import MemoryItem, MemoryType

logger = logging.getLogger("teammate_runtime.memory_writer")


async def save_execution(teammate_id: str, action: str,
                         result: Optional[dict] = None,
                         workspace_id: str = "") -> None:
    """Save action + result as EXECUTION memory."""
    content = json.dumps({
        "action": action,
        "status": (result or {}).get("status", "unknown"),
        "summary": ((result or {}).get("summary", "") or "")[:500],
    }, ensure_ascii=False)
    item = MemoryItem(
        memory_type=MemoryType.EXECUTION,
        content=content,
        source_id=teammate_id,
        created_at=datetime.now(timezone.utc),
    )
    svc = get_memory_service()
    await svc.store(item, workspace_id=workspace_id)


async def save_decision(teammate_id: str, summary: str,
                        source_action: str = "",
                        workspace_id: str = "") -> None:
    """Save a decision summary as DECISION memory."""
    content = json.dumps({
        "decision": summary[:500],
        "source_action": source_action,
    }, ensure_ascii=False)
    item = MemoryItem(
        memory_type=MemoryType.DECISION,
        content=content,
        source_id=teammate_id,
        created_at=datetime.now(timezone.utc),
    )
    svc = get_memory_service()
    await svc.store(item)
