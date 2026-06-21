"""
Teammate CRUD routes with caching.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Teammate
from backend.cache import teammate_cache
from backend.services.cache_warmup_service import invalidate_warmup

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


@router.post("")
async def create_teammate(data: dict, db: AsyncSession = Depends(get_db)):
    teammate = Teammate(
        name=data["name"],
        role=data.get("role", "assistant"),
        avatar_emoji=data.get("avatar_emoji", "🤖"),
        system_prompt=data.get("system_prompt", "You are a helpful AI assistant."),
        model_provider=data["model_provider"],
        model_name=data["model_name"],
        api_key_ref=data.get("api_key_ref"),
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


@router.patch("/{teammate_id}")
async def update_teammate(teammate_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Teammate not found")

    for field in ("name", "role", "avatar_emoji", "system_prompt", "model_provider", "model_name", "api_key_ref"):
        if field in data:
            setattr(t, field, data[field])
    await db.commit()

    # Invalidate caches
    teammate_cache.invalidate(teammate_id)
    teammate_cache.invalidate(LIST_KEY)

    # If system_prompt changed, invalidate all warming + memory for this teammate
    if "system_prompt" in data:
        from backend.cache import _deepseek_warmed, _deepseek_warmed_lock, _memory_summaries, _memory_summaries_lock
        with _deepseek_warmed_lock:
            keys_to_remove = [k for k in _deepseek_warmed if k.startswith(f"{teammate_id}:")]
            for k in keys_to_remove:
                del _deepseek_warmed[k]
        with _memory_summaries_lock:
            keys_to_remove = [k for k in _memory_summaries if k.startswith(f"{teammate_id}:")]
            for k in keys_to_remove:
                del _memory_summaries[k]

    return {"ok": True}


@router.delete("/{teammate_id}")
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
