"""
routes/workspace.py — Workspace API Endpoints

Provides:
  POST   /api/workspaces              — Create workspace
  GET    /api/workspaces              — List workspaces
  GET    /api/workspaces/{id}         — Get workspace details
  PATCH  /api/workspaces/{id}         — Update workspace
  DELETE /api/workspaces/{id}         — Archive workspace
  
  POST   /api/workspaces/{id}/threads           — Create thread
  GET    /api/workspaces/{id}/threads           — List threads
  GET    /api/workspaces/{id}/threads/{tid}     — Get thread details
  PATCH  /api/workspaces/{id}/threads/{tid}     — Update thread status
  
  POST   /api/workspaces/{id}/threads/{tid}/messages  — Add message
  GET    /api/workspaces/{id}/threads/{tid}/messages  — Get messages
  
  POST   /api/workspaces/{id}/threads/{tid}/interrupt  — Interrupt
  POST   /api/workspaces/{id}/threads/{tid}/modify    — Modify task
  POST   /api/workspaces/{id}/threads/{tid}/respond   — Human response
  
  GET    /api/workspaces/{id}/timeline     — Full timeline
  GET    /api/workspaces/{id}/memory       — Memory entries
  GET    /api/workspaces/{id}/context      — Context state
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ═══════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════

class CreateWorkspaceRequest(BaseModel):
    title: str
    description: str = ""


class CreateThreadRequest(BaseModel):
    title: str
    participants: list = []
    linked_task: str = None


class AddMessageRequest(BaseModel):
    thread_id: str
    participant_id: str
    participant_type: str = "human"
    content: str
    role: str = "message"
    reply_to: str = None


class InterruptRequest(BaseModel):
    reason: str = "human interrupt"


class ModifyRequest(BaseModel):
    modification: str


class RespondRequest(BaseModel):
    response: str


# ═══════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════

@router.post("")
async def create_workspace(req: CreateWorkspaceRequest):
    """Create a new workspace."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = await mgr.create_workspace(title=req.title, description=req.description)
    return ws.to_dict()


@router.get("")
async def list_workspaces(status: str = None):
    """List all workspaces."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    workspaces = mgr.list_workspaces(status=status)
    return [ws.to_dict() for ws in workspaces]


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str):
    """Get workspace details."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws.to_dict()


@router.patch("/{workspace_id}")
async def update_workspace(workspace_id: str, updates: dict):
    """Update workspace fields."""
    from backend.services.workspace import get_workspace_manager, WorkspaceStatus
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if "title" in updates:
        ws.title = updates["title"]
    if "description" in updates:
        ws.description = updates["description"]
    if "status" in updates:
        ws.status = WorkspaceStatus(updates["status"])
    
    ws.updated_at = __import__("time").time()
    return ws.to_dict()


@router.delete("/{workspace_id}")
async def archive_workspace(workspace_id: str):
    """Archive a workspace."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ok = await mgr.archive_workspace(workspace_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"status": "archived", "workspace_id": workspace_id}


# ── Thread Routes ──

@router.post("/{workspace_id}/threads")
async def create_thread(workspace_id: str, req: CreateThreadRequest):
    """Create a new thread in workspace."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    thread = await ws.create_thread(
        title=req.title,
        participants=req.participants,
        linked_task=req.linked_task,
    )
    return thread.to_dict()


@router.get("/{workspace_id}/threads")
async def list_threads(workspace_id: str, status: str = None):
    """List threads in workspace."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    threads = ws.threads
    if status:
        threads = [t for t in threads if t.status == status]
    return [t.to_dict() for t in threads]


@router.get("/{workspace_id}/threads/{thread_id}")
async def get_thread(workspace_id: str, thread_id: str):
    """Get thread details."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    thread = ws.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread.to_dict()


@router.patch("/{workspace_id}/threads/{thread_id}")
async def update_thread(workspace_id: str, thread_id: str, updates: dict):
    """Update thread status."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if "status" in updates:
        ok = await ws.update_thread_status(thread_id, updates["status"], updates.get("reason", ""))
        if not ok:
            raise HTTPException(status_code=404, detail="Thread not found")
    
    thread = ws.get_thread(thread_id)
    return thread.to_dict()


# ── Message Routes ──

@router.post("/{workspace_id}/messages")
async def add_message(workspace_id: str, req: AddMessageRequest):
    """Add a message to a thread."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    msg = await ws.add_message(
        thread_id=req.thread_id,
        participant_id=req.participant_id,
        participant_type=req.participant_type,
        content=req.content,
        role=req.role,
        reply_to=req.reply_to,
    )
    return msg.to_dict()


@router.get("/{workspace_id}/threads/{thread_id}/messages")
async def get_messages(workspace_id: str, thread_id: str):
    """Get all messages in a thread."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    messages = ws.get_thread_messages(thread_id)
    return [m.to_dict() for m in messages]


# ── Human-in-the-Loop Routes ──

@router.post("/{workspace_id}/threads/{thread_id}/interrupt")
async def interrupt_thread(workspace_id: str, thread_id: str, req: InterruptRequest):
    """Interrupt a running thread."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    await ws.interrupt(thread_id, req.reason)
    return {"status": "interrupted", "thread_id": thread_id}


@router.post("/{workspace_id}/threads/{thread_id}/modify")
async def modify_task(workspace_id: str, thread_id: str, req: ModifyRequest):
    """Modify a task in a thread."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    await ws.modify_task(thread_id, req.modification)
    return {"status": "modification_queued", "thread_id": thread_id}


@router.post("/{workspace_id}/threads/{thread_id}/respond")
async def human_respond(workspace_id: str, thread_id: str, req: RespondRequest):
    """Provide human response to a waiting thread."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    ok = await ws.provide_human_input(req.response)
    if not ok:
        raise HTTPException(status_code=400, detail="No pending human input for this workspace")
    
    return {"status": "response_recorded", "thread_id": thread_id}


# ── Timeline & Memory ──

@router.get("/{workspace_id}/timeline")
async def get_timeline(workspace_id: str):
    """Get full workspace timeline."""
    from backend.services.workspace import get_workspace_manager
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    return ws.get_timeline()


@router.get("/{workspace_id}/memory")
async def get_memory(workspace_id: str, type: str = None, thread_id: str = None):
    """Get workspace memory entries."""
    from backend.services.workspace_memory import get_memory_manager
    mem_mgr = get_memory_manager()
    memory = mem_mgr.get_or_create(workspace_id)
    
    if thread_id:
        entries = memory.get_by_thread(thread_id)
    elif type:
        entries = memory.get_by_type(type)
    else:
        entries = memory.get_all()
    
    return [e.to_dict() for e in entries]


@router.get("/{workspace_id}/context")
async def get_context(workspace_id: str):
    """Get workspace context state."""
    from backend.services.collaboration import get_context_store
    store = get_context_store()
    ctx = store.get(workspace_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Workspace context not found")
    
    return {
        "current_state": ctx.read_all(),
        "timeline": ctx.get_timeline(),
        "entry_count": ctx.entry_count,
    }


@router.get("/{workspace_id}/stats")
async def workspace_stats(workspace_id: str):
    """Get workspace statistics."""
    from backend.services.workspace import get_workspace_manager
    from backend.services.workspace_memory import get_memory_manager
    
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    mem_mgr = get_memory_manager()
    memory = mem_mgr.get_or_create(workspace_id)
    
    return {
        "workspace": ws.to_dict(),
        "memory": memory.stats(),
        "threads": {
            "total": len(ws.threads),
            "active": len(ws.active_threads),
        },
    }
