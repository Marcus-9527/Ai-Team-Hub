"""Approval API routes — manage DAG node approvals.

GET  /api/approvals          — list pending approvals
GET  /api/approvals?all=1    — list all approvals
POST /api/approvals/{id}/approve — approve a pending request
POST /api/approvals/{id}/reject  — reject a pending request
"""
from fastapi import APIRouter, HTTPException, Depends
from backend.middleware.auth import require_admin
from pydantic import BaseModel

from backend.services.approval import get_approval_service

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApproveRequest(BaseModel):
    by: str = ""


class RejectRequest(BaseModel):
    by: str = ""


@router.get("")
async def list_approvals(all: bool = False):
    svc = get_approval_service()
    if all:
        return {"approvals": svc.list_all()}
    return {"approvals": svc.list_pending()}


@router.post("/{approval_id}/approve", dependencies=[Depends(require_admin)])
async def approve_approval(approval_id: str, req: ApproveRequest):
    svc = get_approval_service()
    rec = svc.approve(approval_id, by=req.by)
    if not rec:
        raise HTTPException(404, "Approval not found")
    return {"approval": rec.to_dict()}


@router.post("/{approval_id}/reject", dependencies=[Depends(require_admin)])
async def reject_approval(approval_id: str, req: RejectRequest):
    svc = get_approval_service()
    rec = svc.reject(approval_id, by=req.by)
    if not rec:
        raise HTTPException(404, "Approval not found")
    return {"approval": rec.to_dict()}
