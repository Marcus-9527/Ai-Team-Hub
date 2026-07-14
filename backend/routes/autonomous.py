"""routes/autonomous.py — Phase 13 Autonomous Collaboration API routes

Endpoints:
  GET/POST /api/autonomous/states       — Teammate runtime state
  POST   /api/autonomous/cede           — Cede Protocol decision
  GET    /api/autonomous/proposals      — Brain proposal approval (retain-only)
  POST   /api/autonomous/proposals/approve
  POST   /api/autonomous/proposals/reject

Phase 24: removed dead claim/event/proposal CRUD endpoints.
TaskClaim is now internal (used by TaskOrchestrator, not via HTTP).
EventWakeup handlers that were never triggered have been removed."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from backend.middleware.auth import require_admin
from pydantic import BaseModel

from backend.services.autonomous.teammate_state import (
    get_state_manager,
    TeammateState,
)
from backend.services.autonomous.cede_protocol import (
    get_cede_protocol,
    CedeDecision,
)
from backend.services.autonomous.brain_proposal import get_proposal_manager

logger = logging.getLogger("routes.autonomous")
router = APIRouter(prefix="/api/autonomous", tags=["autonomous"])


# ═══════════════════════════════════════════════════
#  Pydantic Models
# ═══════════════════════════════════════════════════

class SetStateRequest(BaseModel):
    teammate_id: str
    state: str  # active | idle | working | offline
    task_id: str = ""


class CedeDecideRequest(BaseModel):
    teammate_id: str
    teammate_name: str = ""
    message: str
    channel_id: str = ""
    message_id: str = ""
    history_texts: list[str] = []


class ApproveProposalRequest(BaseModel):
    proposal_id: str
    resolved_by: str = "user"


class RejectProposalRequest(BaseModel):
    proposal_id: str
    resolved_by: str = "user"


# ═══════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════

# ── Teammate Runtime State ──

@router.get("/states")
async def list_states(filter_state: str = ""):
    """List all teammate runtime states."""
    manager = get_state_manager()
    states = await manager.list_all_states(filter_state=filter_state)
    return {"states": states, "count": len(states)}


@router.get("/states/{teammate_id}")
async def get_state(teammate_id: str):
    """Get a single teammate's runtime state."""
    manager = get_state_manager()
    st = await manager.get(teammate_id)
    if not st:
        raise HTTPException(status_code=404, detail="Teammate not found")
    st.touch()
    return st.to_dict()


@router.post("/states", dependencies=[Depends(require_admin)])
async def set_state(req: SetStateRequest):
    """Set a teammate's runtime state."""
    try:
        state = TeammateState(req.state)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state: {req.state}. Must be one of: "
                   f"{[e.value for e in TeammateState]}",
        )
    manager = get_state_manager()
    record = await manager.set_state(req.teammate_id, state, task_id=req.task_id)
    return {"status": "ok", "transition": record}


# ── Cede Protocol ──

@router.post("/cede/decide", dependencies=[Depends(require_admin)])
async def cede_decide(req: CedeDecideRequest):
    """Decide whether a teammate should respond/cede/ignore a message."""
    teammate = {"id": req.teammate_id, "name": req.teammate_name}
    if req.teammate_id:
        try:
            from backend.database import async_session
            from sqlalchemy import select
            from backend.models import Teammate
            async with async_session() as db:
                res = await db.execute(
                    select(Teammate).where(Teammate.id == req.teammate_id)
                )
                obj = res.scalar_one_or_none()
                if obj:
                    teammate = obj.to_dict()
        except Exception as e:
            logger.warning("[Cede] teammate load failed: %s", e)

    cede = get_cede_protocol()
    decision = await cede.decide(
        teammate=teammate,
        message=req.message,
        channel_id=req.channel_id,
        message_id=req.message_id or "",
        history_texts=req.history_texts or [],
    )

    record_id = await cede.record_decision(
        teammate=teammate,
        message_id=req.message_id or "",
        decision=decision,
        channel_id=req.channel_id,
    )

    return {
        "decision": decision.value,
        "record_id": record_id,
        "message_id": req.message_id,
    }


# ── Brain Proposal Approval (retain-only) ──

@router.get("/proposals")
async def list_proposals(status: str = "", teammate_id: str = "", limit: int = 50):
    """List all brain proposals."""
    manager = get_proposal_manager()
    proposals = await manager.list(
        status=status,
        teammate_id=teammate_id,
        limit=limit,
    )
    return {
        "proposals": [p.to_dict() for p in proposals],
        "count": len(proposals),
        "pending": await manager.count_pending(),
    }


@router.get("/proposals/pending")
async def list_pending_proposals():
    """List only pending proposals (shortcut)."""
    manager = get_proposal_manager()
    proposals = await manager.list_pending()
    return {
        "proposals": [p.to_dict() for p in proposals],
        "count": len(proposals),
    }


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str):
    """Get a single proposal."""
    manager = get_proposal_manager()
    proposal = await manager.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal.to_dict()


@router.post("/proposals/approve", dependencies=[Depends(require_admin)])
async def approve_proposal(req: ApproveProposalRequest):
    """Approve a brain proposal (applies the change)."""
    manager = get_proposal_manager()
    ok, msg = await manager.approve(
        proposal_id=req.proposal_id,
        resolved_by=req.resolved_by,
    )
    return {"success": ok, "message": msg}


@router.post("/proposals/reject", dependencies=[Depends(require_admin)])
async def reject_proposal(req: RejectProposalRequest):
    """Reject a brain proposal (no change)."""
    manager = get_proposal_manager()
    ok, msg = await manager.reject(
        proposal_id=req.proposal_id,
        resolved_by=req.resolved_by,
    )
    return {"success": ok, "message": msg}
