"""routes/policy.py — Policy Dashboard & Audit API.

GET  /api/policy/events        — recent ALLOW/DENY/APPROVAL_REQUIRED decisions
GET  /api/policy/events?effect=deny — filter by effect
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.task.task_policy import list_policy_events

router = APIRouter(prefix="/api/policy", tags=["policy"])


@router.get("/events")
async def get_policy_events(
    limit: int = Query(50, ge=1, le=500),
    effect: str = Query("", description="Filter: allow | deny | approval_required"),
    db: AsyncSession = Depends(get_db),
):
    decisions = await list_policy_events(db, limit=limit, effect=effect or None)
    return {
        "events": [d.to_dict() for d in decisions],
        "total": len(decisions),
    }
