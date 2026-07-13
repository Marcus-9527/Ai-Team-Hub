"""Memory Intelligence Layer — Pure dataclass types.

MemoryType enum and MemoryItem dataclass.
NO SQLAlchemy Model references — pure Python only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class MemoryType(str, Enum):
    """Scope / category of a memory item.

    Ordered by semantic breadth (widest first):
      GLOBAL      — system-wide rules, learned patterns, persistent facts
      WORKSPACE   — per-workspace decisions, conventions, preferences
      TEAMMATE    — per-teammate preferences, style, learned patterns
      CHANNEL     — per-channel conversation themes, active topics
      TASK        — per-task goals, constraints, past plans
      EXECUTION   — per-execution outcomes, errors, performance signals
      DECISION    — specific decisions made during execution
      EVENT       — notable events (interruptions, approvals, failures)
    """

    GLOBAL = "GLOBAL"
    WORKSPACE = "WORKSPACE"
    TEAMMATE = "TEAMMATE"
    CHANNEL = "CHANNEL"
    TASK = "TASK"
    EXECUTION = "EXECUTION"
    DECISION = "DECISION"
    EVENT = "EVENT"

    @classmethod
    def priority(cls, memory_type: str) -> int:
        """Lower number = higher priority for retention/ranking."""
        order = [
            cls.EXECUTION,
            cls.DECISION,
            cls.TASK,
            cls.TEAMMATE,
            cls.CHANNEL,
            cls.WORKSPACE,
            cls.EVENT,
            cls.GLOBAL,
        ]
        try:
            return order.index(cls(memory_type))
        except (ValueError, KeyError):
            return 99


@dataclass
class MemoryItem:
    """A single memory record in the intelligence layer.

    Pure dataclass — no ORM, no SQLAlchemy, no framework dependency.
    Persisted by MemoryService via raw SQL.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: str = MemoryType.EVENT  # MemoryType enum value
    content: str = ""
    source_id: str = ""       # FK-like: task_id | channel_id | workspace_id | execution_id
    relevance_score: float = 0.0
    embedding: list[float] = field(default_factory=list)  # vector for semantic search
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "content": self.content,
            "source_id": self.source_id,
            "relevance_score": self.relevance_score,
            "embedding": self.embedding,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryItem:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            memory_type=data.get("memory_type", MemoryType.EVENT),
            content=data.get("content", ""),
            source_id=data.get("source_id", ""),
            relevance_score=float(data.get("relevance_score", 0.0)),
            embedding=list(data.get("embedding", [])),
            created_at=_parse_dt(data.get("created_at")),
            metadata=data.get("metadata", {}),
        )

    def __len__(self) -> int:
        """Rough char-length (token estimate ~ len/4)."""
        return len(self.content) + len(str(self.metadata))


def _parse_dt(val: Optional[str]) -> datetime:
    """Parse ISO datetime string, falling back to now()."""
    if not val:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
