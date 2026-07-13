"""brain/fragment_store.py — Brain Fragment 存储层 (Phase 12.1)

基于现有的 MemoryService + memory_items 表实现 Fragment CRUD。
Fragment = MemoryItem 的 brain:* 子类型，版本信息放在 metadata 中。

Ponytail: 不加新表/新 Model。现有持久化层够用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import get_memory_service, MemoryService

logger = logging.getLogger("brain.fragment_store")


class BrainFragmentType(str, Enum):
    """Brain fragment type taxonomy."""
    IDENTITY = "brain:identity"
    PERSONALITY = "brain:personality"
    PRINCIPLES = "brain:principles"
    RESPONSIBILITIES = "brain:responsibilities"
    SKILLS = "brain:skills"
    LESSONS = "brain:lessons"
    DECISIONS = "brain:decisions"
    PREFERENCES = "brain:preferences"
    BEHAVIOR_SUGGESTION = "brain:behavior_suggestion"
    PROPOSAL = "brain:proposal"  # pending core-personality change


@dataclass
class BrainFragment:
    """A single brain fragment — thin wrapper over MemoryItem metadata.

    Persisted as a MemoryItem with type=brain:*.
    Versioning: each write inserts a new row; version tracked in metadata["fragment_version"].
    """
    teammate_id: str = ""
    fragment_type: str = BrainFragmentType.IDENTITY
    content: str = ""
    version: int = 1
    confidence: float = 0.8
    source: str = ""  # "manual" | "reflection" | "consolidation" | "proposal"
    editable: bool = True
    id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_memory_item(self) -> MemoryItem:
        """Convert to MemoryItem for persistence via MemoryService."""
        return MemoryItem(
            id=self.id,
            memory_type=self.fragment_type,  # "brain:identity" etc
            content=self.content,
            source_id=self.teammate_id,
            relevance_score=self.confidence,
            metadata={
                "teammate_id": self.teammate_id,
                "fragment_type": self.fragment_type,
                "fragment_version": self.version,
                "source": self.source,
                "editable": "1" if self.editable else "0",
                "created_at": (self.created_at or datetime.now(timezone.utc)).isoformat(),
                "updated_at": (self.updated_at or datetime.now(timezone.utc)).isoformat(),
            },
        )

    @classmethod
    def from_memory_item(cls, item: MemoryItem) -> BrainFragment:
        meta = item.metadata or {}
        return cls(
            id=item.id,
            teammate_id=meta.get("teammate_id", item.source_id),
            fragment_type=item.memory_type,
            content=item.content,
            version=int(meta.get("fragment_version", 1)),
            confidence=item.relevance_score,
            source=meta.get("source", "manual"),
            editable=meta.get("editable", "1") == "1",
            created_at=item.created_at,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "teammate_id": self.teammate_id,
            "type": self.fragment_type,
            "content": self.content,
            "version": self.version,
            "confidence": self.confidence,
            "source": self.source,
            "editable": self.editable,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BrainFragmentStore:
    """Fragment CRUD backed by MemoryService.

    Versioning scheme: each write creates a new row.
    "Current" version = highest fragment_version for (teammate_id, fragment_type).
    Rollback = write a copy of the older version with version+1.
    """

    def __init__(self, svc: Optional[MemoryService] = None):
        self._svc = svc or get_memory_service()

    async def store(self, fragment: BrainFragment) -> str:
        """Store a fragment (always inserts — new version)."""
        # Auto-increment version
        latest = await self.get_latest(fragment.teammate_id, fragment.fragment_type)
        fragment.version = (latest.version if latest else 0) + 1
        fragment.created_at = datetime.now(timezone.utc)
        fragment.updated_at = fragment.created_at
        item = fragment.to_memory_item()
        await self._svc.store(item)
        logger.debug("[Brain] stored %s v%d for teammate %s", fragment.fragment_type, fragment.version, fragment.teammate_id[:8])
        return fragment.id

    async def get_latest(self, teammate_id: str, fragment_type: str) -> Optional[BrainFragment]:
        """Get the current (latest-version) fragment for a teammate+type."""
        all_items = await self._svc.query(memory_type=fragment_type, source_id=teammate_id, limit=100)
        if not all_items:
            return None
        best = max(all_items, key=lambda i: int(i.metadata.get("fragment_version", 0)) if i.metadata else 0)
        return BrainFragment.from_memory_item(best)

    async def list_versions(self, teammate_id: str, fragment_type: str) -> list[BrainFragment]:
        """List all versions of a fragment type for a teammate (newest first)."""
        items = await self._svc.query(memory_type=fragment_type, source_id=teammate_id, limit=100)
        fragments = [BrainFragment.from_memory_item(i) for i in items]
        fragments.sort(key=lambda f: f.version, reverse=True)
        return fragments

    async def get_all_by_teammate(self, teammate_id: str) -> list[BrainFragment]:
        """Get the latest version of each fragment type for a teammate."""
        # Over-fetch all brain:* items, then pick latest per type
        types = [e.value for e in BrainFragmentType]
        items = await self._svc.query_by_types(types, limit=500)
        # Filter to this teammate
        teammate_items = [i for i in items if i.source_id == teammate_id or (i.metadata or {}).get("teammate_id") == teammate_id]
        # Group by type, keep latest version
        by_type: dict[str, list[MemoryItem]] = {}
        for item in teammate_items:
            t = item.memory_type
            by_type.setdefault(t, []).append(item)
        result = []
        for t, lst in by_type.items():
            best = max(lst, key=lambda i: int(i.metadata.get("fragment_version", 0)) if i.metadata else 0)
            result.append(BrainFragment.from_memory_item(best))
        return result

    async def rollback(self, teammate_id: str, fragment_type: str, target_version: int) -> Optional[str]:
        """Rollback to a specific version by copying its content as a new version."""
        items = await self._svc.query(memory_type=fragment_type, source_id=teammate_id, limit=100)
        target = None
        for item in items:
            meta = item.metadata or {}
            if int(meta.get("fragment_version", 0)) == target_version:
                target = item
                break
        if target is None:
            return None
        frag = BrainFragment.from_memory_item(target)
        frag.id = __import__("uuid").uuid4().hex[:12]
        frag.source = f"rollback_from_v{target_version}"
        return await self.store(frag)


# Singleton
_store: Optional[BrainFragmentStore] = None


def get_brain_fragment_store() -> BrainFragmentStore:
    global _store
    if _store is None:
        _store = BrainFragmentStore()
    return _store
