"""
workspace.py — Workspace Abstraction Layer (v9)

Architecture Shift:
  FROM: Task → Execution → Output
  TO:   Workspace → Event Stream → Execution → Continuous Updates

Workspace is the primary system unit (NOT task).
A workspace contains:
  - threads (task threads)
  - context (shared knowledge)
  - messages (human + teammate)
  - event history (timeline)
  - memory (decisions, reasoning, revisions)
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.services.collaboration.event_bus import EventBus, EventType, get_event_bus
from backend.services.collaboration.shared_context import SharedContext, ContextStore, get_context_store

logger = logging.getLogger("workspace")


# ═══════════════════════════════════════════════════════════
# Workspace Status & Types
# ═══════════════════════════════════════════════════════════

class WorkspaceStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ThreadStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_HUMAN = "waiting_human"
    PAUSED = "paused"
    COMPLETED = "completed"
    CLOSED = "closed"


class ParticipantType(str, Enum):
    HUMAN = "human"
    TEAMMATE = "teammate"
    SYSTEM = "system"


# ═══════════════════════════════════════════════════════════
# Thread — Task Thread within Workspace
# ═══════════════════════════════════════════════════════════

@dataclass
class Thread:
    """
    A thread is a focused conversation/task within a workspace.
    
    Threads support:
      - Multiple participants (human + teammates)
      - Status tracking (open → in_progress → waiting_human → completed)
      - Linked execution tasks (MAEOS task IDs)
      - Event-sourced message history
    """
    id: str
    workspace_id: str
    title: str
    status: str = ThreadStatus.OPEN
    participants: list = field(default_factory=list)  # [{id, type, name}]
    linked_tasks: list = field(default_factory=list)  # [task_id]
    context_keys: list = field(default_factory=list)  # keys into SharedContext
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        self.updated_at = time.time()
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "status": self.status,
            "participants": self.participants,
            "linked_tasks": self.linked_tasks,
            "context_keys": self.context_keys,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════
# Message — Thread Message (Human or Agent)
# ═══════════════════════════════════════════════════════════

@dataclass
class Message:
    """A message in a thread."""
    id: str
    thread_id: str
    workspace_id: str
    participant_id: str
    participant_type: str  # human | teammate | system
    content: str
    role: str = "message"  # message | interruption | clarification | revision
    reply_to: str = None  # message_id this replies to
    metadata: dict = field(default_factory=dict)
    created_at: float = 0.0
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "workspace_id": self.workspace_id,
            "participant_id": self.participant_id,
            "participant_type": self.participant_type,
            "content": self.content,
            "role": self.role,
            "reply_to": self.reply_to,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


# ═══════════════════════════════════════════════════════════
# Workspace — Primary System Unit
# ═══════════════════════════════════════════════════════════

class Workspace:
    """
    Task Workspace — the primary system unit.
    
    Contains:
      - context (shared knowledge base)
      - threads (task threads)
      - messages (human + teammate interactions)
      - event history (timeline)
      - memory (decision history, reasoning traces, revisions)
    """
    
    def __init__(
        self,
        workspace_id: str,
        title: str = "",
        description: str = "",
        event_bus: EventBus = None,
        context_store: ContextStore = None,
    ):
        self.id = workspace_id
        self.title = title
        self.description = description
        self.status = WorkspaceStatus.ACTIVE
        self.created_at = time.time()
        self.updated_at = time.time()
        self.metadata: dict = {}
        
        # Subsystems
        self._event_bus = event_bus or get_event_bus()
        self._context_store = context_store or get_context_store()
        self._shared_ctx = self._context_store.get_or_create(workspace_id)
        
        # In-memory collections (ephemeral, rebuilt from events)
        self._threads: dict[str, Thread] = {}
        self._messages: list[Message] = []
        
        # Human-in-the-loop state
        self._pending_human_input: Optional[asyncio.Event] = None
        self._interrupt_event = asyncio.Event()
        self._modification_queue: asyncio.Queue = asyncio.Queue()
    
    # ── Properties ──
    
    @property
    def threads(self) -> list[Thread]:
        return list(self._threads.values())
    
    @property
    def messages(self) -> list[Message]:
        return list(self._messages)
    
    @property
    def active_threads(self) -> list[Thread]:
        return [t for t in self._threads.values() if t.status in (ThreadStatus.OPEN, ThreadStatus.IN_PROGRESS, ThreadStatus.WAITING_HUMAN)]
    
    # ── Thread Management ──
    
    async def create_thread(
        self,
        title: str,
        participants: list = None,
        linked_task: str = None,
    ) -> Thread:
        """Create a new thread in this workspace."""
        thread = Thread(
            id=str(uuid.uuid4())[:12],
            workspace_id=self.id,
            title=title,
            participants=participants or [],
            linked_tasks=[linked_task] if linked_task else [],
        )
        self._threads[thread.id] = thread
        self.updated_at = time.time()
        
        # Emit event
        await self._event_bus.emit(
            event_type=EventType.TASK_CREATED,
            source="workspace",
            task_id=self.id,
            data={
                "event": "thread_created",
                "thread_id": thread.id,
                "thread_title": title,
            },
        )
        
        logger.info(f"[WORKSPACE:{self.id}] thread created: {thread.id} — {title}")
        return thread
    
    def get_thread(self, thread_id: str) -> Optional[Thread]:
        return self._threads.get(thread_id)
    
    async def update_thread_status(self, thread_id: str, status: str, reason: str = "") -> bool:
        """Update thread status."""
        thread = self._threads.get(thread_id)
        if not thread:
            return False
        old_status = thread.status
        thread.status = status
        thread.updated_at = time.time()
        
        await self._event_bus.emit(
            event_type=EventType.TASK_UPDATED,
            source="workspace",
            task_id=self.id,
            data={
                "event": "thread_status_changed",
                "thread_id": thread_id,
                "from": old_status,
                "to": status,
                "reason": reason,
            },
        )
        return True
    
    # ── Message Management ──
    
    async def add_message(
        self,
        thread_id: str,
        participant_id: str,
        participant_type: str,
        content: str,
        role: str = "message",
        reply_to: str = None,
        metadata: dict = None,
    ) -> Message:
        """Add a message to a thread."""
        msg = Message(
            id=str(uuid.uuid4())[:12],
            thread_id=thread_id,
            workspace_id=self.id,
            participant_id=participant_id,
            participant_type=participant_type,
            content=content,
            role=role,
            reply_to=reply_to,
            metadata=metadata or {},
        )
        self._messages.append(msg)
        self.updated_at = time.time()
        
        # Emit event
        await self._event_bus.emit(
            event_type=EventType.USER_MESSAGE if participant_type == "human" else EventType.TEAMMATE_MESSAGE,
            source=f"{participant_type}:{participant_id}",
            task_id=self.id,
            data={
                "event": "message_added",
                "thread_id": thread_id,
                "message_id": msg.id,
                "role": role,
                "content_preview": content[:200],
            },
        )
        
        # Write to shared context
        await self._shared_ctx.write(
            f"thread:{thread_id}:last_message",
            content,
            teammate_id=participant_id,
        )
        
        return msg
    
    def get_thread_messages(self, thread_id: str) -> list[Message]:
        """Get all messages in a thread."""
        return [m for m in self._messages if m.thread_id == thread_id]
    
    # ── Context Access ──
    
    async def write_context(self, key: str, value: Any, teammate_id: str = "system"):
        """Write to shared workspace context."""
        await self._shared_ctx.write(key, value, teammate_id=teammate_id)
    
    def read_context(self, key: str) -> Any:
        """Read from shared workspace context."""
        return self._shared_ctx.read(key)
    
    def get_context_timeline(self) -> list[dict]:
        """Get full context timeline."""
        return self._shared_ctx.get_timeline()
    
    # ── Human-in-the-Loop ──
    
    async def request_human_input(
        self,
        thread_id: str,
        question: str,
        context: str = "",
    ) -> Optional[str]:
        """
        Pause execution and request human input.
        
        Returns the human's response, or None if interrupted.
        """
        # Set thread to waiting
        await self.update_thread_status(thread_id, ThreadStatus.WAITING_HUMAN, "awaiting human input")
        
        # Add system message requesting input
        await self.add_message(
            thread_id=thread_id,
            participant_id="system",
            participant_type="system",
            content=question,
            role="clarification",
            metadata={"context": context},
        )
        
        # Create event for human response
        self._pending_human_input = asyncio.Event()
        self._pending_human_input.response = None  # Will be set by human
        
        logger.info(f"[WORKSPACE:{self.id}] waiting for human input on thread {thread_id}")
        
        # Wait (with timeout)
        try:
            await asyncio.wait_for(self._pending_human_input.wait(), timeout=300.0)  # 5 min timeout
            response = getattr(self._pending_human_input, 'response', None)
            return response
        except asyncio.TimeoutError:
            logger.warning(f"[WORKSPACE:{self.id}] human input timeout on thread {thread_id}")
            return None
        finally:
            self._pending_human_input = None
            await self.update_thread_status(thread_id, ThreadStatus.IN_PROGRESS, "human input received/timeout")
    
    async def provide_human_input(self, response: str) -> bool:
        """
        Provide human input to a waiting thread.
        Called by API when human responds.
        """
        if self._pending_human_input is None:
            logger.warning(f"[WORKSPACE:{self.id}] no pending human input")
            return False
        
        self._pending_human_input.response = response
        self._pending_human_input.set()
        return True
    
    async def interrupt(self, thread_id: str, reason: str = "human interrupt"):
        """Interrupt current execution in a thread."""
        self._interrupt_event.set()
        await self.update_thread_status(thread_id, ThreadStatus.PAUSED, reason)
        await self.add_message(
            thread_id=thread_id,
            participant_id="system",
            participant_type="system",
            content=f"Execution interrupted: {reason}",
            role="interruption",
        )
        logger.info(f"[WORKSPACE:{self.id}] thread {thread_id} interrupted: {reason}")
    
    async def modify_task(self, thread_id: str, modification: str) -> None:
        """Queue a task modification request."""
        await self._modification_queue.put({
            "thread_id": thread_id,
            "modification": modification,
            "timestamp": time.time(),
        })
        await self.add_message(
            thread_id=thread_id,
            participant_id="human",
            participant_type="human",
            content=modification,
            role="revision",
        )
    
    def is_interrupted(self) -> bool:
        return self._interrupt_event.is_set()
    
    def clear_interrupt(self):
        self._interrupt_event.clear()
    
    async def get_modification(self) -> Optional[dict]:
        """Get next modification request (non-blocking)."""
        try:
            return self._modification_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
    
    # ── Serialization ──
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "threads": [t.to_dict() for t in self.threads],
            "active_threads": len(self.active_threads),
            "message_count": len(self._messages),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }
    
    def get_timeline(self) -> list[dict]:
        """Get full workspace timeline (messages + context changes)."""
        events = []
        for msg in self._messages:
            events.append({
                "type": "message",
                "timestamp": msg.created_at,
                "data": msg.to_dict(),
            })
        for entry in self._shared_ctx.get_timeline():
            events.append({
                "type": "context_update",
                "timestamp": entry.get("timestamp", 0),
                "data": entry,
            })
        events.sort(key=lambda e: e["timestamp"])
        return events


# ═══════════════════════════════════════════════════════════
# Workspace Manager
# ═══════════════════════════════════════════════════════════

class WorkspaceManager:
    """
    Manages all workspaces in the system.
    
    Usage:
        mgr = get_workspace_manager()
        ws = await mgr.create_workspace("Project Alpha")
        thread = await ws.create_thread("Implement auth")
    """
    
    def __init__(self):
        self._workspaces: dict[str, Workspace] = {}
        self._event_bus = get_event_bus()
        self._context_store = get_context_store()
    
    async def create_workspace(
        self,
        title: str,
        description: str = "",
        workspace_id: str = None,
    ) -> Workspace:
        """Create a new workspace."""
        ws_id = workspace_id or str(uuid.uuid4())[:12]
        ws = Workspace(
            workspace_id=ws_id,
            title=title,
            description=description,
            event_bus=self._event_bus,
            context_store=self._context_store,
        )
        self._workspaces[ws_id] = ws
        
        await self._event_bus.emit(
            event_type=EventType.TASK_CREATED,
            source="workspace_manager",
            task_id=ws_id,
            data={"event": "workspace_created", "title": title},
        )
        
        logger.info(f"[WORKSPACE_MGR] created workspace: {ws_id} — {title}")
        return ws
    
    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        return self._workspaces.get(workspace_id)
    
    def list_workspaces(self, status: str = None) -> list[Workspace]:
        """List all workspaces, optionally filtered by status."""
        workspaces = list(self._workspaces.values())
        if status:
            workspaces = [w for w in workspaces if w.status.value == status]
        return workspaces
    
    async def archive_workspace(self, workspace_id: str) -> bool:
        """Archive a workspace."""
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return False
        ws.status = WorkspaceStatus.ARCHIVED
        ws.updated_at = time.time()
        
        await self._event_bus.emit(
            event_type=EventType.TASK_UPDATED,
            source="workspace_manager",
            task_id=workspace_id,
            data={"event": "workspace_archived"},
        )
        return True
    
    def stats(self) -> dict:
        return {
            "total_workspaces": len(self._workspaces),
            "active_workspaces": sum(1 for w in self._workspaces.values() if w.status == WorkspaceStatus.ACTIVE),
            "total_threads": sum(len(w.threads) for w in self._workspaces.values()),
            "total_messages": sum(len(w.messages) for w in self._workspaces.values()),
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    global _manager
    if _manager is None:
        _manager = WorkspaceManager()
    return _manager
