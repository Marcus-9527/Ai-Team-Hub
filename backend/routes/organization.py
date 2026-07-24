"""Organization Monitor & Control API — read-only replay + lifecycle controls + product views.

Phase 8.0: adds /summary and /teammates/{id}/profile for the Organization Dashboard.
No new services, no new models, no execution chain changes.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.organization.inspector import OrganizationRunInspector
from backend.services.organization.control import OrganizationControl
from backend.services.organization.identity import TeammateIdentityService
from backend.services.organization.experience import OrganizationExperienceService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/organization", tags=["organization"])


# ── Existing run-level endpoints ──


@router.get("/runs/{run_id}/status")
async def get_run_status(run_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = OrganizationControl(db)
    return await ctrl.get_status(run_id)


@router.get("/runs/{run_id}/timeline")
async def get_run_timeline(run_id: str, db: AsyncSession = Depends(get_db)):
    return await OrganizationRunInspector(db).get_timeline(run_id)


@router.get("/runs/{run_id}/summary")
async def get_run_summary(run_id: str, db: AsyncSession = Depends(get_db)):
    return await OrganizationRunInspector(db).summarize_run(run_id)


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = OrganizationControl(db)
    run = await ctrl.pause_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return {"id": run.id, "status": run.status}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = OrganizationControl(db)
    run = await ctrl.resume_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return {"id": run.id, "status": run.status}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db)):
    ctrl = OrganizationControl(db)
    run = await ctrl.cancel_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return {"id": run.id, "status": run.status}


@router.get("/runs")
async def list_runs(limit: int = 20, offset: int = 0, db: AsyncSession = Depends(get_db)):
    """List all organization runs, most recent first."""
    from backend.models.organization_run import OrganizationRun

    rows = (await db.execute(
        select(OrganizationRun)
        .order_by(OrganizationRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    return [
        {
            "id": r.id,
            "run_type": r.run_type,
            "title": r.title,
            "status": r.status,
            "channel_id": r.channel_id,
            "workspace_id": r.workspace_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        }
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════
# Phase 8.0 — Organization Product Layer
# ═══════════════════════════════════════════════════════════════


@router.get("/summary")
async def organization_summary(db: AsyncSession = Depends(get_db)):
    """Product-level organization overview.

    Returns:
      members      — list of teammates with role/model
      active_runs  — runs that are active/running/paused
      completed_runs — runs that reached completed status
      success_rate — overall ratio of completed / completed+failed
      learned_experience — count of knowledge memory items
      capabilities — set of all registered capability labels
    """
    from backend.models import Teammate as TeammateModel
    from backend.models.organization_run import OrganizationRun
    from backend.services.memory.memory_types import MemoryType

    # 1. Members
    tm_rows = (await db.execute(
        select(TeammateModel).order_by(TeammateModel.created_at)
    )).scalars().all()
    members = [
        {
            "id": t.id,
            "name": t.name,
            "role": t.role or "assistant",
            "model": t.model_name or "",
            "provider": t.model_provider or "",
            "system_prompt": (t.system_prompt or "")[:100],
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tm_rows
    ]

    # 2. Run stats
    run_count_q = select(
        func.count().label("total"),
        func.sum(case((OrganizationRun.status == "active", 1), else_=0)).label("active"),
        func.sum(case((OrganizationRun.status == "completed", 1), else_=0)).label("completed"),
        func.sum(case((OrganizationRun.status == "failed", 1), else_=0)).label("failed"),
        func.sum(case((OrganizationRun.status == "paused", 1), else_=0)).label("paused"),
    )
    row = (await db.execute(run_count_q)).one()
    total = row.total or 0
    active = row.active or 0
    completed = row.completed or 0
    failed = row.failed or 0
    paused = row.paused or 0
    success_rate = round(completed / (completed + failed), 4) if (completed + failed) > 0 else 0.0

    # 3. Learned experience — count knowledge MemoryItems
    try:
        from backend.services.memory.memory_service import get_memory_service
        mem_svc = get_memory_service()
        exp_count = 0
        for mt in (MemoryType.PROJECT_KNOWLEDGE, MemoryType.MEMBER_KNOWLEDGE, MemoryType.TEAM_PATTERN):
            items = await mem_svc.query(memory_type=mt.value, limit=1000)
            exp_count += len(items)
    except Exception:
        exp_count = 0

    # 4. Capabilities — union of all registered role capabilities
    from backend.services.organization.registry import DEFAULT_ROLE_CAPABILITIES
    all_caps: set[str] = set()
    for caps in DEFAULT_ROLE_CAPABILITIES.values():
        all_caps.update(caps)

    return {
        "members": members,
        "member_count": len(members),
        "active_runs": {"count": active},
        "completed_runs": {"count": completed, "total": total},
        "success_rate": success_rate,
        "learned_experience": {"knowledge_items": exp_count},
        "capabilities": sorted(all_caps),
    }


@router.get("/teammates/{teammate_id}/profile")
async def teammate_profile(teammate_id: str, db: AsyncSession = Depends(get_db)):
    """Enhanced teammate profile for the Organization Dashboard.

    Returns:
      identity     — name, role, model, provider, system_prompt snippet
      capabilities — role-default capabilities
      skills       — BrainFragment skills + learned behaviors
      performance  — SessionTurn stats + success rate
      experience   — recent knowledge MemoryItems mentioning this teammate
    """
    # Identity via TeammateIdentityService
    id_svc = TeammateIdentityService(db)
    identity = await id_svc.get_identity(teammate_id)

    # Separate identity fields
    from backend.models.chat import Teammate
    tm = await db.get(Teammate, teammate_id)
    if tm is None:
        raise HTTPException(404, "Teammate not found")

    member_info = {
        "id": tm.id,
        "name": tm.name,
        "role": tm.role or "assistant",
        "model": tm.model_name or "",
        "provider": tm.model_provider or "",
        "system_prompt": (tm.system_prompt or "")[:200],
        "avatar_emoji": tm.avatar_emoji or "",
    }

    # Capabilities + skills from identity service
    capabilities = identity.get("capabilities", [])
    skills = identity.get("skills", [])
    performance = identity.get("performance", {
        "total_actions": 0, "completed": 0, "failed": 0, "recent_runs": 0,
    })
    perf_success_rate = round(
        performance["completed"] / performance["total_actions"], 4
    ) if performance["total_actions"] > 0 else 0.0
    performance["success_rate"] = perf_success_rate

    # Learned behaviors
    learned = identity.get("learned", [])

    # Experience — find knowledge items related to this teammate
    from backend.services.memory.memory_types import MemoryType
    from backend.services.memory.memory_service import get_memory_service
    mem_svc = get_memory_service()
    experience_items = []
    try:
        for mt in (MemoryType.PROJECT_KNOWLEDGE, MemoryType.MEMBER_KNOWLEDGE, MemoryType.TEAM_PATTERN):
            items = await mem_svc.query(memory_type=mt.value, limit=20)
            for item in items:
                if teammate_id in (item.source_id or "") or tm.name in (item.content or ""):
                    experience_items.append({
                        "content": (item.content or "")[:200],
                        "memory_type": str(getattr(item, "memory_type", mt.value)),
                        "scope": getattr(item, "scope", ""),
                        "created_at": item.created_at.isoformat() if hasattr(item, "created_at") and item.created_at else None,
                    })
                    if len(experience_items) >= 5:
                        break
            if len(experience_items) >= 5:
                break
    except Exception:
        pass

    return {
        "identity": member_info,
        "capabilities": capabilities,
        "skills": skills,
        "learned": learned[:10],
        "performance": performance,
        "experience": experience_items,
    }
