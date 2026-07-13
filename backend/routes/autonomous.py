"""routes/autonomous.py — Phase 13 Autonomous Collaboration API routes

Endpoints:
  GET/POST /api/autonomous/states       — Teammate runtime state
  POST   /api/autonomous/cede           — Cede Protocol decision
  POST   /api/autonomous/claim          — Task claim
  POST   /api/autonomous/event          — Fire wakeup event
  GET    /api/autonomous/events         — Event history
  GET/POST/PUT /api/autonomous/proposals — Brain proposal approval
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.autonomous.teammate_state import (
    get_state_manager,
    TeammateState,
)
from backend.services.autonomous.cede_protocol import (
    get_cede_protocol,
    CedeDecision,
)
from backend.services.autonomous.task_claim import get_claim_manager
from backend.services.autonomous.event_wakeup import (
    get_event_wakeup_bus,
    WakeupEvent,
    WakeupPayload,
)
from backend.services.autonomous.brain_proposal import (
    get_proposal_manager,
    Proposal,
)

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


class ClaimRequest(BaseModel):
    task_id: str
    teammate_id: str
    teammate_name: str = ""
    reason: str = ""


class FireEventRequest(BaseModel):
    event_type: str  # task_created | task_failed | review_rejected | brain_updated
    task_id: str = ""
    teammate_id: str = ""
    channel_id: str = ""
    reason: str = ""
    data: dict = {}


class CreateProposalRequest(BaseModel):
    teammate_id: str
    target_type: str
    target_label: str = ""
    proposed_content: str
    original_content: str = ""
    diff_summary: str = ""
    task_id: str = ""
    reason: str = ""


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


@router.post("/states")
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

@router.post("/cede/decide")
async def cede_decide(req: CedeDecideRequest):
    """Decide whether a teammate should respond/cede/ignore a message."""
    # Build teammate dict (minimal — enough for role detection)
    teammate = {"id": req.teammate_id, "name": req.teammate_name}
    # We need more context for decisions. In production, load from DB.
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


@router.get("/cede/decisions/{message_id}")
async def get_cede_decisions(message_id: str):
    """Get all cede decisions for a message."""
    cede = get_cede_protocol()
    decisions = await cede.get_message_decisions(message_id)
    return {
        "message_id": message_id,
        "decisions": [d.to_dict() for d in decisions],
        "responded": [d.to_dict() for d in await cede.who_responded(message_id)],
    }


# ── Task Claim ──

@router.post("/claim")
async def claim_task(req: ClaimRequest):
    """Attempt to claim a task."""
    manager = get_claim_manager()
    ok, msg = await manager.claim(
        task_id=req.task_id,
        teammate_id=req.teammate_id,
        teammate_name=req.teammate_name,
        reason=req.reason,
    )
    return {
        "success": ok,
        "message": msg,
        "owner": await manager.get_owner(req.task_id),
    }


@router.get("/claim/{task_id}")
async def get_task_claims(task_id: str):
    """Get all claim records for a task."""
    manager = get_claim_manager()
    claims = await manager.get_claims(task_id)
    owner = await manager.get_owner(task_id)
    return {
        "task_id": task_id,
        "owner": owner,
        "claim_count": len(claims),
        "claims": [c.to_dict() for c in claims],
    }


@router.delete("/claim/{task_id}")
async def clear_claims(task_id: str):
    """Clear claim data (task completed/failed)."""
    manager = get_claim_manager()
    await manager.clear(task_id)
    return {"status": "cleared", "task_id": task_id}


# ── Event Wakeup ──

@router.post("/event")
async def fire_event(req: FireEventRequest):
    """Fire a wakeup event → all subscribers notified."""
    try:
        event = WakeupEvent(req.event_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type: {req.event_type}. "
                   f"Must be: {[e.value for e in WakeupEvent]}",
        )

    bus = get_event_wakeup_bus()
    payload = WakeupPayload(
        event_type=event.value,
        task_id=req.task_id,
        teammate_id=req.teammate_id,
        channel_id=req.channel_id,
        reason=req.reason,
        data=req.data,
    )
    bus.fire(event, payload)

    subscriber_count = bus.count_subscribers(event)
    return {
        "status": "fired",
        "event_type": req.event_type,
        "subscribers": subscriber_count,
    }


@router.get("/events")
async def get_events(event_type: str = "", limit: int = 20):
    """Get recent wakeup event history."""
    if event_type:
        try:
            WakeupEvent(event_type)  # validate
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event_type: {event_type}",
            )
    bus = get_event_wakeup_bus()
    history = bus.get_history(event_type=event_type or None, limit=limit)
    return {
        "events": history,
        "count": len(history),
        "subscriber_totals": {
            e.value: bus.count_subscribers(e)
            for e in WakeupEvent
        },
    }


# ── Brain Proposal Approval ──

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


@router.post("/proposals")
async def create_proposal(req: CreateProposalRequest):
    """Create a new brain proposal."""
    manager = get_proposal_manager()
    proposal = await manager.create(
        teammate_id=req.teammate_id,
        target_type=req.target_type,
        target_label=req.target_label or req.target_type,
        proposed_content=req.proposed_content,
        original_content=req.original_content,
        diff_summary=req.diff_summary,
        task_id=req.task_id,
        reason=req.reason,
    )
    return {"status": "created", "proposal": proposal.to_dict()}


@router.post("/proposals/approve")
async def approve_proposal(req: ApproveProposalRequest):
    """Approve a brain proposal (applies the change)."""
    manager = get_proposal_manager()
    ok, msg = await manager.approve(
        proposal_id=req.proposal_id,
        resolved_by=req.resolved_by,
    )
    return {"success": ok, "message": msg}


@router.post("/proposals/reject")
async def reject_proposal(req: RejectProposalRequest):
    """Reject a brain proposal (no change)."""
    manager = get_proposal_manager()
    ok, msg = await manager.reject(
        proposal_id=req.proposal_id,
        resolved_by=req.resolved_by,
    )
    return {"success": ok, "message": msg}


@router.post("/proposals/expire")
async def expire_proposals():
    """Expire all overdue proposals."""
    manager = get_proposal_manager()
    count = await manager.expire()
    return {"status": "expired", "count": count}
