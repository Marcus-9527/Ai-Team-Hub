"""
Channel CRUD routes with caching.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from backend.database import get_db
from backend.models import Channel, Teammate
from backend.cache import channel_cache, teammate_cache
from backend.middleware.auth import require_admin, ws_id_of
from fastapi import Depends, Request

router = APIRouter(prefix="/api/channels", tags=["channels"])

def _list_key(ws: str | None) -> str:
    return f"channels:{ws}" if ws else "channels:global"


def _serialize_channel(ch: Channel) -> dict:
    return {
        "id": ch.id,
        "name": ch.name,
        "description": ch.description,
        "workspace_id": ch.workspace_id,
        "teammate_ids": ch.teammate_ids or [],
        "created_at": ch.created_at.isoformat() if ch.created_at else None,
    }


@router.get("")
async def list_channels(request: Request, db: AsyncSession = Depends(get_db)):
    ws = ws_id_of(request)
    cached = channel_cache.get(_list_key(ws))
    if cached is not None:
        return cached
    q = select(Channel).order_by(Channel.created_at)
    if ws:
        q = q.where(Channel.workspace_id == ws)
    result = await db.execute(q)
    channels = result.scalars().all()
    data = [_serialize_channel(ch) for ch in channels]

    channel_cache.set(_list_key(ws), data)
    for item in data:
        channel_cache.set(item["id"], item)

    return data


@router.post("", dependencies=[Depends(require_admin)])
async def create_channel(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    ws = ws_id_of(request)
    channel = Channel(
        name=data["name"],
        description=data.get("description", ""),
        workspace_id=ws or data.get("workspace_id"),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)

    channel_cache.invalidate(_list_key(ws))
    item = _serialize_channel(channel)
    channel_cache.set(channel.id, item)

    return {"id": channel.id, "name": channel.name, "description": channel.description}


@router.get("/{channel_id}")
async def get_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    cached = channel_cache.get(channel_id)
    if cached is not None:
        return cached

    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    data = _serialize_channel(ch)
    channel_cache.set(channel_id, data)
    channel_cache.invalidate(_list_key(ch.workspace_id))
    return data


@router.patch("/{channel_id}", dependencies=[Depends(require_admin)])
async def update_channel(channel_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    if "name" in data:
        ch.name = data["name"]
    if "description" in data:
        ch.description = data["description"]
    await db.commit()

    channel_cache.invalidate(channel_id)
    channel_cache.invalidate(_list_key(ch.workspace_id))
    return {"ok": True}


@router.delete("/{channel_id}", dependencies=[Depends(require_admin)])
async def delete_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.delete(ch)
    await db.commit()

    channel_cache.invalidate(channel_id)
    channel_cache.invalidate(_list_key(ch.workspace_id))
    return {"ok": True}


@router.post("/{channel_id}/teammates/{teammate_id}", dependencies=[Depends(require_admin)])
async def add_teammate_to_channel(channel_id: str, teammate_id: str, db: AsyncSession = Depends(get_db)):
    """Add an AI teammate to a channel."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Validate teammate exists (use cache)
    cached_tm = teammate_cache.get(teammate_id)
    if cached_tm is None:
        tm_result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
        if not tm_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Teammate not found")

    ids = list(ch.teammate_ids or [])
    if teammate_id not in ids:
        ids.append(teammate_id)
    ch.teammate_ids = ids
    flag_modified(ch, "teammate_ids")
    await db.commit()

    channel_cache.invalidate(channel_id)
    channel_cache.invalidate(_list_key(ch.workspace_id))
    teammate_cache.invalidate(f"channel_teammates:{channel_id}")
    return {"ok": True, "teammate_ids": ids}


@router.delete("/{channel_id}/teammates/{teammate_id}", dependencies=[Depends(require_admin)])
async def remove_teammate_from_channel(channel_id: str, teammate_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    ids = list(ch.teammate_ids or [])
    if teammate_id in ids:
        ids.remove(teammate_id)
    ch.teammate_ids = ids
    flag_modified(ch, "teammate_ids")
    await db.commit()

    channel_cache.invalidate(channel_id)
    channel_cache.invalidate(_list_key(ch.workspace_id))
    return {"ok": True, "teammate_ids": ids}
