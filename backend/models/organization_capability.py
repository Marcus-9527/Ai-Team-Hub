"""Organization capability model — role → capability → tools mapping."""

from sqlalchemy import Column, String, JSON, DateTime, UniqueConstraint

from backend.database import Base
from ._helpers import gen_uuid, utcnow


class OrganizationCapability(Base):
    __tablename__ = "organization_capabilities"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=True, index=True)
    role = Column(String, nullable=False, index=True)
    capability = Column(String, nullable=False)  # e.g. "code_execution", "file_edit"
    tools = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("workspace_id", "role", "capability", name="uq_org_cap_role_cap"),
    )
