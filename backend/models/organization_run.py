"""Organization run model — unifies Chat and Task under one run context."""
from sqlalchemy import Column, String, DateTime

from backend.database import Base
from ._helpers import gen_uuid, utcnow


class OrganizationRun(Base):
    __tablename__ = "organization_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    run_type = Column(String, nullable=False)  # "chat" | "task"
    source_id = Column(String, nullable=True, index=True)  # trigger.id or task.id
    workspace_id = Column(String, nullable=True, index=True)
    channel_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    ended_at = Column(DateTime, nullable=True)
