"""Auth routes: register, login, me."""
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User, Workspace, WorkspaceMember
from backend.services.auth_service import (
    hash_password,
    verify_password,
    create_token,
    decode_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterReq(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class LoginReq(BaseModel):
    email: str
    password: str


async def _first_workspace_id(db: AsyncSession, user_id: str) -> str:
    res = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    )
    row = res.first()
    return row[0] if row else ""


@router.post("/register")
async def register(body: RegisterReq, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    if not email or len(body.password) < 6:
        raise HTTPException(status_code=400, detail="email and password(>=6) required")
    existing = (await db.execute(select(User).where(User.email == email))).first()
    if existing:
        raise HTTPException(status_code=409, detail="email already registered")

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or email.split("@")[0],
    )
    db.add(user)
    await db.flush()

    ws = Workspace(name=f"{user.display_name} 的工作区", owner_id=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    await db.commit()

    token = create_token(user.id, ws.id)
    return {
        "access_token": token,
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "workspace_id": ws.id,
    }


@router.post("/login")
async def login(body: LoginReq, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    ws_id = await _first_workspace_id(db, user.id)
    return {
        "access_token": create_token(user.id, ws_id),
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "workspace_id": ws_id,
    }


@router.get("/me")
async def me(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    claims = decode_token(authorization[7:].strip())
    if not claims:
        raise HTTPException(status_code=401, detail="invalid token")
    user = (await db.execute(select(User).where(User.id == claims["sub"]))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    ws_id = await _first_workspace_id(db, user.id)
    return {
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "workspace_id": ws_id,
    }
