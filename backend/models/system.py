"""System/Auth models — users, workspaces, API keys."""
from sqlalchemy import Column, String, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.database import Base
from ._helpers import gen_uuid, utcnow


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    avatar_color = Column(String, default="#4a154b")
    created_at = Column(DateTime, default=utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    owner_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    role = Column(String, default="owner")  # "owner" | "member"
    joined_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)


class APIKey(Base):
    __tablename__ = "apikeys"

    id = Column(String, primary_key=True, default=gen_uuid)
    provider = Column(String, nullable=False, index=True)
    label = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    key_hash = Column(String, nullable=True)
    base_url = Column(String, nullable=True)
    is_active = Column("is_active", String, default="1")
    workspace_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
