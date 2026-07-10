"""
workspace_memory.py — Workspace Memory Layer

Replaces execution memory with:
  - Decision history (what was decided and why)
  - Conversation history (human + teammate dialogue)
  - Teammate reasoning traces (why teammates made specific choices)
  - Revisions timeline (what changed and when)

This is the persistent memory of a workspace, built on top of
the event-sourced SharedContext.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.services.collaboration.shared_context import SharedContext, get_context_store

logger = logging.getLogger("workspace_memory")


# ═══════════════════════════════════════════════════════════
# Memory Entry Types
# ═══════════════════════════════════════════════════════════

class MemoryType(str, Enum):
    DECISION = "decision"           # A decision was made
    CONVERSATION = "conversation"   # Dialogue exchange
    REASONING = "reasoning"         # Agent reasoning trace
    REVISION = "revision"           # Content was revised
    CONTEXT = "context"             # Context update
    INTERRUPTION = "interruption"    # Human interrupted


@dataclass
class MemoryEntry:
    """A single memory entry in the workspace."""
    id: str
    workspace_id: str
    thread_id: str
    memory_type: str       # MemoryType
    content: str           # The actual content
    actor: str             # Who created this (human:xxx, teammate:xxx, system)
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "thread_id": self.thread_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════
# Workspace Memory
# ═══════════════════════════════════════════════════════════

class WorkspaceMemory:
    """
    Memory layer for a workspace.
    
    Provides structured access to:
      - Decision history
      - Conversation history
      - Reasoning traces
      - Revision timeline
    """
    
    def __init__(self, workspace_id: str, shared_context: SharedContext = None):
        self.workspace_id = workspace_id
        self._shared_ctx = shared_context or get_context_store().get_or_create(workspace_id)
        self._entries: list[MemoryEntry] = []
    
    # ── Recording ──
    
    async def record_decision(
        self,
        thread_id: str,
        decision: str,
        reasoning: str,
        actor: str = "system",
        metadata: dict = None,
    ) -> MemoryEntry:
        """Record a decision with reasoning."""
        entry = MemoryEntry(
            id=str(uuid.uuid4())[:12],
            workspace_id=self.workspace_id,
            thread_id=thread_id,
            memory_type=MemoryType.DECISION,
            content=decision,
            actor=actor,
            metadata={"reasoning": reasoning, **(metadata or {})},
        )
        self._entries.append(entry)
        
        # Persist to shared context
        await self._shared_ctx.write(
            f"memory:decision:{entry.id}",
            entry.to_dict(),
            teammate_id=actor,
        )
        
        logger.debug(f"[MEM:{self.workspace_id}] decision recorded: {decision[:80]}")
        return entry
    
    async def record_conversation(
        self,
        thread_id: str,
        content: str,
        actor: str,
        role: str = "message",
        metadata: dict = None,
    ) -> MemoryEntry:
        """Record a conversation exchange."""
        entry = MemoryEntry(
            id=str(uuid.uuid4())[:12],
            workspace_id=self.workspace_id,
            thread_id=thread_id,
            memory_type=MemoryType.CONVERSATION,
            content=content,
            actor=actor,
            metadata={"role": role, **(metadata or {})},
        )
        self._entries.append(entry)
        
        await self._shared_ctx.write(
            f"memory:conversation:{entry.id}",
            entry.to_dict(),
            teammate_id=actor,
        )
        
        return entry
    
    async def record_reasoning(
        self,
        thread_id: str,
        teammate_id: str,
        reasoning: str,
        output_summary: str = "",
        metadata: dict = None,
    ) -> MemoryEntry:
        """Record a teammate reasoning trace."""
        entry = MemoryEntry(
            id=str(uuid.uuid4())[:12],
            workspace_id=self.workspace_id,
            thread_id=thread_id,
            memory_type=MemoryType.REASONING,
            content=reasoning,
            actor=f"teammate:{teammate_id}",
            metadata={"output_summary": output_summary, **(metadata or {})},
        )
        self._entries.append(entry)
        
        await self._shared_ctx.write(
            f"memory:reasoning:{entry.id}",
            entry.to_dict(),
            teammate_id=teammate_id,
        )
        
        logger.debug(f"[MEM:{self.workspace_id}] reasoning recorded by {teammate_id}: {reasoning[:80]}")
        return entry
    
    async def record_revision(
        self,
        thread_id: str,
        original: str,
        revised: str,
        reason: str,
        actor: str = "human",
        metadata: dict = None,
    ) -> MemoryEntry:
        """Record a content revision."""
        entry = MemoryEntry(
            id=str(uuid.uuid4())[:12],
            workspace_id=self.workspace_id,
            thread_id=thread_id,
            memory_type=MemoryType.REVISION,
            content=revised,
            actor=actor,
            metadata={
                "original": original,
                "reason": reason,
                **(metadata or {}),
            },
        )
        self._entries.append(entry)
        
        await self._shared_ctx.write(
            f"memory:revision:{entry.id}",
            entry.to_dict(),
            teammate_id=actor,
        )
        
        logger.debug(f"[MEM:{self.workspace_id}] revision recorded: {reason}")
        return entry
    
    async def record_interruption(
        self,
        thread_id: str,
        reason: str,
        actor: str = "human",
        metadata: dict = None,
    ) -> MemoryEntry:
        """Record a human interruption."""
        entry = MemoryEntry(
            id=str(uuid.uuid4())[:12],
            workspace_id=self.workspace_id,
            thread_id=thread_id,
            memory_type=MemoryType.INTERRUPTION,
            content=reason,
            actor=actor,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        
        await self._shared_ctx.write(
            f"memory:interruption:{entry.id}",
            entry.to_dict(),
            teammate_id=actor,
        )
        
        logger.info(f"[MEM:{self.workspace_id}] interruption: {reason}")
        return entry
    
    # ── Querying ──
    
    def get_all(self) -> list[MemoryEntry]:
        """Get all memory entries."""
        return list(self._entries)
    
    def get_by_type(self, memory_type: str) -> list[MemoryEntry]:
        """Get entries by type."""
        return [e for e in self._entries if e.memory_type == memory_type]
    
    def get_by_thread(self, thread_id: str) -> list[MemoryEntry]:
        """Get all entries for a thread."""
        return [e for e in self._entries if e.thread_id == thread_id]
    
    def get_decisions(self) -> list[MemoryEntry]:
        """Get all decisions."""
        return self.get_by_type(MemoryType.DECISION)
    
    def get_reasoning_traces(self) -> list[MemoryEntry]:
        """Get all reasoning traces."""
        return self.get_by_type(MemoryType.REASONING)
    
    def get_revisions(self) -> list[MemoryEntry]:
        """Get all revisions."""
        return self.get_by_type(MemoryType.REVISION)
    
    def get_timeline(self) -> list[dict]:
        """Get full memory timeline."""
        return sorted(
            [e.to_dict() for e in self._entries],
            key=lambda e: e["timestamp"],
        )
    
    def search(self, query: str) -> list[MemoryEntry]:
        """Simple text search across all entries."""
        query_lower = query.lower()
        return [
            e for e in self._entries
            if query_lower in e.content.lower()
            or any(query_lower in str(v).lower() for v in e.metadata.values())
        ]
    
    def stats(self) -> dict:
        """Get memory statistics."""
        type_counts = {}
        for e in self._entries:
            type_counts[e.memory_type] = type_counts.get(e.memory_type, 0) + 1
        
        return {
            "total_entries": len(self._entries),
            "by_type": type_counts,
            "workspace_id": self.workspace_id,
        }


# ═══════════════════════════════════════════════════════════
# Memory Manager (per-workspace factory)
# ═══════════════════════════════════════════════════════════

class MemoryManager:
    """Manages workspace memory instances."""
