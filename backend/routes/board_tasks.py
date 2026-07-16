"""
routes/board_tasks.py — Lightweight claim board (Phase 28)

Distinct from the heavy execution-engine `tasks` routes. Board tasks are
plain to-dos scoped to a workspace:

  POST   /api/board-tasks                      — create (workspace from token)
  GET    /api/channels/{id}/tasks              — list a channel's board (ws-scoped)
  PATCH  /api/board-tasks/{id}                 — update title/desc/status/priority
  PATCH  /api/board-tasks/{id}/claim           — optimistic-lock claim → 409 on loss

Concurrency: claim issues `UPDATE board_tasks SET assignee_id=:me
WHERE id=:id AND assignee_id IS NULL`. rowcount==0 means someone else already
claimed it → 409. No app-level lock, no read-then-write race.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth import ws_id_of
from backend.models import BoardTask, Channel

logger = logging.getLogger("routes.board_tasks")

router = APIRouter(prefix="/api", tags=["board_tasks"])


# ── Schemas ──

class CreateBoardTaskRequest(BaseModel):
    title: str
    description: str = ""
    channel_id: Optional[str] = None
    source_message_id: Optional[str] = None
    priority: int = 2
    created_by: str = "system"


class UpdateBoardTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None


class ClaimBoardTaskRequest(BaseModel):
    assignee_id: str
    assignee_name: Optional[str] = None


# ── Helpers ──

def _board_ws(request) -> str:
    """Current caller workspace; 400 if unauthenticated (no token scope)."""
    ws = ws_id_of(request)
    if not ws:
        # ponytail: master-key / legacy paths have no workspace → reject rather
        # than silently scope to None (which would break the NOT-NULL column).
        raise HTTPException(status_code=400, detail="workspace scope required")
    return ws


async def _assert_channel_in_ws(db: AsyncSession, channel_id: str, ws: str) -> None:
    """Reject if the channel does not belong to the caller's workspace.

    Cross-workspace task attachment is a scope escape — caller must never be
    able to hang a task on another tenant's channel by guessing an id.
    """
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if ch is None:
        raise HTTPException(status_code=404, detail="channel not found")
    if ch.workspace_id != ws:
        raise HTTPException(status_code=400, detail="channel does not belong to your workspace")


# ── Routes ──

@router.post("/board-tasks", status_code=201)
async def create_board_task(
    req: CreateBoardTaskRequest,
    request: "object" = None,
    db: AsyncSession = Depends(get_db),
):
    ws = _board_ws(request)
    if req.channel_id:
        await _assert_channel_in_ws(db, req.channel_id, ws)

    task = BoardTask(
        workspace_id=ws,
        channel_id=req.channel_id,
        source_message_id=req.source_message_id,
        title=req.title,
        description=req.description,
        priority=req.priority,
        created_by=req.created_by,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task.to_dict()


@router.get("/channels/{channel_id}/tasks")
async def list_channel_tasks(channel_id: str, request: "object" = None, db: AsyncSession = Depends(get_db)):
    ws = _board_ws(request)
    # channel existence + ws ownership checked implicitly: filter by ws AND channel
    rows = (
        await db.execute(
            select(BoardTask)
            .where(BoardTask.workspace_id == ws, BoardTask.channel_id == channel_id)
            .order_by(BoardTask.created_at.desc())
        )
    ).scalars().all()
    return [t.to_dict() for t in rows]


@router.patch("/board-tasks/{task_id}")
async def update_board_task(
    task_id: str,
    req: UpdateBoardTaskRequest,
    request: "object" = None,
    db: AsyncSession = Depends(get_db),
):
    ws = _board_ws(request)
    task = (
        await db.execute(select(BoardTask).where(BoardTask.id == task_id, BoardTask.workspace_id == ws))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    for field in ("title", "description", "status", "priority"):
        val = getattr(req, field)
        if val is not None:
            setattr(task, field, val)
    if req.status == "done" and task.completed_at is None:
        task.completed_at = datetime.now(timezone.utc)
    elif req.status != "done":
        task.completed_at = None

    await db.commit()
    await db.refresh(task)
    return task.to_dict()


@router.patch("/board-tasks/{task_id}/claim")
async def claim_board_task(
    task_id: str,
    req: ClaimBoardTaskRequest,
    request: "object" = None,
    db: AsyncSession = Depends(get_db),
):
    ws = _board_ws(request)
    # Optimistic lock: only claim if still unclaimed (assignee_id IS NULL).
    # Single atomic UPDATE — no read-then-write, no app lock.
    result = await db.execute(
        update(BoardTask)
        .where(BoardTask.id == task_id, BoardTask.workspace_id == ws, BoardTask.assignee_id.is_(None))
        .values(assignee_id=req.assignee_id, assignee_name=req.assignee_name, status="in_progress")
    )
    if result.rowcount == 0:
        # Lost the race, or task doesn't exist in this workspace.
        existing = (
            await db.execute(select(BoardTask).where(BoardTask.id == task_id, BoardTask.workspace_id == ws))
        ).scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=404, detail="task not found")
        raise HTTPException(status_code=409, detail="task already claimed")
    await db.commit()
    refreshed = (
        await db.execute(select(BoardTask).where(BoardTask.id == task_id))
    ).scalar_one_or_none()
    return refreshed.to_dict()
