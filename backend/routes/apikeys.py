"""
API Key management routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import APIKey

router = APIRouter(prefix="/api/apikeys", tags=["apikeys"])


@router.get("")
async def list_apikeys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).order_by(APIKey.created_at))
    keys = result.scalars().all()
    return [
        {
            "id": k.id,
            "provider": k.provider,
            "label": k.label,
            "api_key": k.api_key[:8] + "***" if k.api_key else "",
            "base_url": k.base_url,
            "has_key": bool(k.api_key),
        }
        for k in keys
    ]


@router.post("")
async def create_apikey(data: dict, db: AsyncSession = Depends(get_db)):
    apikey = APIKey(
        provider=data["provider"],
        label=data["label"],
        api_key=data["api_key"],
        base_url=data.get("base_url"),
    )
    db.add(apikey)
    await db.commit()
    await db.refresh(apikey)
    return {
        "id": apikey.id,
        "provider": apikey.provider,
        "label": apikey.label,
        "has_key": bool(apikey.api_key),
    }


@router.delete("/{apikey_id}")
async def delete_apikey(apikey_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).where(APIKey.id == apikey_id))
    k = result.scalar_one_or_none()
    if not k:
        raise HTTPException(status_code=404, detail="API Key not found")
    await db.delete(k)
    await db.commit()
    return {"ok": True}
