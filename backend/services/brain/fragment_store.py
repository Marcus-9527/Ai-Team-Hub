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
    CHANNEL_SUMMARY = "brain:channel_summary"  # per-channel 频道摘要 (min version)
    CHAT_MEMORY = "brain:chat_memory"  # 每轮聊天提炼的频道记忆 (min version, 无向量库)


@dataclass
class BrainFragment:
    """A single brain fragment — thin wrapper over MemoryItem metadata.

    Persisted as a MemoryItem with type=brain:*.
    Versioning: each write inserts a new row; version tracked in metadata["fragment_version"].
    """
    teammate_id: str = ""
    workspace_id: str = ""  # 焊死隔离：每条记忆必须带 workspace_id
    channel_id: str = ""  # 关联频道（chat_memory 用）
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
                "workspace_id": self.workspace_id,  # 隔离字段，必填
                "channel_id": self.channel_id,  # 关联频道
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
            workspace_id=meta.get("workspace_id", ""),
            channel_id=meta.get("channel_id", ""),
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
            "workspace_id": self.workspace_id,
            "channel_id": self.channel_id,
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

    async def get_latest(self, teammate_id: str, fragment_type: str, workspace_id: str = "") -> Optional[BrainFragment]:
        """Get the current (latest-version) fragment for a teammate+type."""
        all_items = await self._svc.query(memory_type=fragment_type, source_id=teammate_id, limit=100)
        if workspace_id:
            all_items = [i for i in all_items if (i.metadata or {}).get("workspace_id") == workspace_id]
        if not all_items:
            return None
        best = max(all_items, key=lambda i: int(i.metadata.get("fragment_version", 0)) if i.metadata else 0)
        return BrainFragment.from_memory_item(best)

    async def list_versions(self, teammate_id: str, fragment_type: str, workspace_id: str = "") -> list[BrainFragment]:
        """List all versions of a fragment type for a teammate (newest first)."""
        items = await self._svc.query(memory_type=fragment_type, source_id=teammate_id, limit=100)
        if workspace_id:
            items = [i for i in items if (i.metadata or {}).get("workspace_id") == workspace_id]
        fragments = [BrainFragment.from_memory_item(i) for i in items]
        fragments.sort(key=lambda f: f.version, reverse=True)
        return fragments

    async def get_all_by_teammate(self, teammate_id: str, workspace_id: str = "") -> list[BrainFragment]:
        """Get the latest version of each fragment type for a teammate."""
        # Over-fetch all brain:* items, then pick latest per type
        types = [e.value for e in BrainFragmentType]
        items = await self._svc.query_by_types(types, limit=500)
        # Filter to this teammate (and workspace if provided)
        teammate_items = [
            i for i in items
            if (i.source_id == teammate_id or (i.metadata or {}).get("teammate_id") == teammate_id)
            and (not workspace_id or (i.metadata or {}).get("workspace_id") == workspace_id)
        ]
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

    async def recent_chat_memory(
        self, teammate_id: str, workspace_id: str, limit: int = 8,
    ) -> list[BrainFragment]:
        """最近 N 条聊天记忆（注入用）。

        WHERE memory_type='brain:chat_memory' AND source_id=:teammate_id
        （teammate_id 列级精确匹配），再按 workspace_id 精确过滤，时间倒序取 N。
        不按时间盲目取 —— 必须同时命中 teammate_id + workspace_id。
        """
        if not teammate_id or not workspace_id:
            return []
        items = await self._svc.query(
            memory_type=BrainFragmentType.CHAT_MEMORY.value,
            source_id=teammate_id,
            limit=200,
        )
        matched = [
            i for i in items
            if (i.metadata or {}).get("workspace_id") == workspace_id
        ]
        matched.sort(
            key=lambda i: i.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return [BrainFragment.from_memory_item(i) for i in matched[:limit]]

    async def list_chat_memory_by_workspace(
        self, workspace_id: str, limit: int = 200,
    ) -> list[BrainFragment]:
        """某 workspace 下所有队友的聊天记忆（前端列表用）。

        WHERE memory_type='brain:chat_memory'（source_id 跨队友不固定），
        Python 侧按 workspace_id 精确过滤，时间倒序。
        """
        if not workspace_id:
            return []
        items = await self._svc.query(
            memory_type=BrainFragmentType.CHAT_MEMORY.value,
            limit=500,
        )
        matched = [
            i for i in items
            if (i.metadata or {}).get("workspace_id") == workspace_id
        ]
        matched.sort(
            key=lambda i: i.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return [BrainFragment.from_memory_item(i) for i in matched[:limit]]

    async def rollback(self, teammate_id: str, fragment_type: str, target_version: int, workspace_id: str = "") -> Optional[str]:
        """Rollback to a specific version by copying its content as a new version."""
        items = await self._svc.query(memory_type=fragment_type, source_id=teammate_id, limit=100)
        if workspace_id:
            items = [i for i in items if (i.metadata or {}).get("workspace_id") == workspace_id]
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
