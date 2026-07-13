"""
Teammate CRUD routes with caching.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models import Teammate, TaskExecutionModel
from backend.cache import teammate_cache
from backend.services.cache_warmup_service import invalidate_warmup
from backend.middleware.auth import require_admin
from backend.services.memory.memory_service import get_memory_service
from backend.services.autonomous.teammate_state import get_state_manager
from backend.services.brain.fragment_store import get_brain_fragment_store

router = APIRouter(prefix="/api/teammates", tags=["teammates"])

LIST_KEY = "all"


def _serialize_teammate(t: Teammate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "role": t.role,
        "avatar_emoji": t.avatar_emoji,
        "system_prompt": t.system_prompt,
        "model_provider": t.model_provider,
        "model_name": t.model_name,
        "api_key_ref": t.api_key_ref,
        "skills": t.skills or [],
        "capabilities": t.capabilities or [],
        "success_rate": t.success_rate or 0.0,
        "average_score": t.average_score or 0.0,
        "execution_count": t.execution_count or 0,
    }


@router.get("")
async def list_teammates(db: AsyncSession = Depends(get_db)):
    # Try cache first
    cached = teammate_cache.get(LIST_KEY)
    if cached is not None:
        return cached

    result = await db.execute(select(Teammate).order_by(Teammate.created_at))
    teammates = result.scalars().all()
    data = [_serialize_teammate(t) for t in teammates]

    # Populate both list cache and individual caches
    teammate_cache.set(LIST_KEY, data)
    for item in data:
        teammate_cache.set(item["id"], item)

    return data


@router.post("", dependencies=[Depends(require_admin)])
async def create_teammate(data: dict, db: AsyncSession = Depends(get_db)):
    teammate = Teammate(
        name=data["name"],
        role=data.get("role", "assistant"),
        avatar_emoji=data.get("avatar_emoji", "🤖"),
        system_prompt=data.get("system_prompt", "You are a helpful AI assistant."),
        model_provider=data["model_provider"],
        model_name=data["model_name"],
        api_key_ref=data.get("api_key_ref"),
        skills=data.get("skills", []),
        capabilities=data.get("capabilities", []),
    )
    db.add(teammate)
    await db.commit()
    await db.refresh(teammate)

    # Invalidate list cache; cache the new item
    teammate_cache.invalidate(LIST_KEY)
    item = _serialize_teammate(teammate)
    teammate_cache.set(teammate.id, item)

    return {"id": teammate.id, "name": teammate.name}


@router.get("/{teammate_id}")
async def get_teammate(teammate_id: str, db: AsyncSession = Depends(get_db)):
    # Try cache first
    cached = teammate_cache.get(teammate_id)
    if cached is not None:
        return cached

    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")

    data = _serialize_teammate(t)
    teammate_cache.set(teammate_id, data)
    # Also invalidate list since it may be stale
    teammate_cache.invalidate(LIST_KEY)
    return data


@router.patch("/{teammate_id}", dependencies=[Depends(require_admin)])
async def update_teammate(teammate_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")

    for field in ("name", "role", "avatar_emoji", "system_prompt", "model_provider", "model_name", "api_key_ref", "skills", "capabilities"):
        if field in data:
            setattr(t, field, data[field])
    await db.commit()

    # Invalidate caches
    teammate_cache.invalidate(teammate_id)
    teammate_cache.invalidate(LIST_KEY)

    # If system_prompt changed, invalidate all warming + memory for this teammate
    if "system_prompt" in data:
        from backend.services.cache_warmup_service import invalidate_warmup
        invalidate_warmup(teammate_id)

    return {"ok": True}


@router.delete("/{teammate_id}", dependencies=[Depends(require_admin)])
async def delete_teammate(teammate_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")
    await db.delete(t)
    await db.commit()

    # Invalidate caches
    teammate_cache.invalidate(teammate_id)
    teammate_cache.invalidate(LIST_KEY)

    return {"ok": True}


# ── Phase 7: Teammate Intelligence ──


@router.get("/recommend")
async def recommend_teammate(task_type: str = "general", top_n: int = 3, db: AsyncSession = Depends(get_db)):
    """Recommend teammates for a given task type based on skills + success rate."""
    from backend.services.teammate_intelligence import TeammateSelector
    profiles = await TeammateSelector.recommend(task_type, top_n=top_n, db=db)
    return {"task_type": task_type, "recommendations": [p.to_dict() for p in profiles]}


# ── Phase 14: Teammate Evolution Memory ──


@router.get("/{teammate_id}/memory")
async def get_teammate_memory(teammate_id: str, db: AsyncSession = Depends(get_db)):
    """Return the evolution memory for a teammate."""
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")
    return {
        "teammate_id": t.id,
        "name": t.name,
        "strengths": t.strengths or [],
        "weaknesses": t.weaknesses or [],
        "learned_patterns": t.learned_patterns or [],
        "failed_patterns": t.failed_patterns or [],
        "preferred_tools": t.preferred_tools or [],
    }


# ── Phase 22: Teammate Profile Aggregator ──


@router.get("/{teammate_id}/profile")
async def get_teammate_profile(teammate_id: str, db: AsyncSession = Depends(get_db)):
    """Aggregate teammate profile: stats, brain, memory, task history, state."""
    # 1. Teammate record
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")

    profile = _serialize_teammate(t)

    # 2. Brain fragments → version / fragment count
    try:
        frags = await get_brain_fragment_store().get_all_by_teammate(teammate_id)
        profile["brain_fragments_count"] = len(frags)
        latest_ver = max((f.version for f in frags), default=0)
        profile["brain_version"] = latest_ver
    except Exception:
        profile["brain_fragments_count"] = 0
        profile["brain_version"] = 0

    # 3. Memory count (source_id = teammate_id)
    try:
        mem_svc = get_memory_service()
        mem_items = await mem_svc.query(source_id=teammate_id)
        profile["memory_count"] = len(mem_items)
    except Exception:
        profile["memory_count"] = 0

    # 4. Task execution stats (from TaskExecutionModel)
    try:
        count_q = (
            select(func.count(TaskExecutionModel.id))
            .where(TaskExecutionModel.teammate_id == teammate_id)
        )
        success_q = (
            select(func.count(TaskExecutionModel.id))
            .where(TaskExecutionModel.teammate_id == teammate_id, TaskExecutionModel.error == "")
        )
        total = (await db.execute(count_q)).scalar() or 0
        success = (await db.execute(success_q)).scalar() or 0
        profile["task_executions"] = {
            "total": total,
            "success": success,
            "failed": total - success,
            "success_rate": round(success / total, 4) if total > 0 else 0.0,
        }
    except Exception:
        profile["task_executions"] = {"total": 0, "success": 0, "failed": 0, "success_rate": 0.0}

    # 5. Current autonomous state
    try:
        mgr = get_state_manager()
        state = mgr.get_state(teammate_id)
        profile["current_state"] = state.state if state else "unknown"
    except Exception:
        profile["current_state"] = "unknown"

    return profile
