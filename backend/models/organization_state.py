"""Organization state model — run-scoped key-value state store.

Each OrganizationRun can have multiple OrganizationState entries organized by
state_type + key, enabling rich state recovery from a single run_id:
  - current_action: what action is in progress
  - progress: task/step completion counts
  - member: teammate runtime state (persisted from in-memory cache)
  - blocker: current blocking issue
  - context: snapshot of execution context
"""

from sqlalchemy import Column, String, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.database import Base
from ._helpers import gen_uuid, utcnow


class OrganizationState(Base):
    __tablename__ = "organization_states"

    id = Column(String, primary_key=True, default=gen_uuid)
    run_id = Column(String, nullable=False, index=True)
    state_type = Column(String, nullable=False)  # progress | member | current_action | blocker | context
    key = Column(String, nullable=False)  # "main", teammate_id, step_id, etc.
    value = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "state_type", "key", name="uq_org_state_run_type_key"),
    )
