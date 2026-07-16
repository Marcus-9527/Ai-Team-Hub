"""
SQLAlchemy models for AI Team Hub.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Float, Integer, UniqueConstraint
from sqlalchemy.orm import relationship, backref

from backend.database import Base


def gen_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


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
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="owner")  # "owner" | "member"
    joined_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    workspace_id = Column(String, nullable=True, index=True)  # ponytail: single-ws MVP
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Many-to-many: teammates in this channel
    teammate_ids = Column(JSON, default=list)   # list of teammate UUID strings

    messages = relationship("Message", back_populates="channel", cascade="all, delete-orphan",
                            order_by="Message.created_at")


class Teammate(Base):
    __tablename__ = "teammates"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    role = Column(String, default="assistant")
    avatar_emoji = Column(String, default="🤖")
    system_prompt = Column(Text, default="You are a helpful AI assistant.")
    model_provider = Column(String, nullable=False)   # e.g. "openai", "deepseek", "anthropic"
    model_name = Column(String, nullable=False)        # e.g. "gpt-4o", "deepseek-chat"
    api_key_ref = Column(String, nullable=True)        # reference to an APIKey id
    workspace_id = Column(String, nullable=True, index=True)  # ponytail: single-ws MVP
    # Phase 7: Teammate intelligence fields
    skills = Column(JSON, default=list)                # ["python", "architecture", ...]
    capabilities = Column(JSON, default=list)          # ["coding", "code_review", "writing", ...]
    success_rate = Column(Float, default=0.0)          # ratio of successful executions
    average_score = Column(Float, default=0.0)         # avg overall_quality score
    execution_count = Column(Integer, default=0)       # total executions recorded
    # Phase 14: Teammate evolution memory
    strengths = Column(JSON, default=list)
    weaknesses = Column(JSON, default=list)
    learned_patterns = Column(JSON, default=list)
    failed_patterns = Column(JSON, default=list)
    preferred_tools = Column(JSON, default=list)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "avatar_emoji": self.avatar_emoji,
            "system_prompt": self.system_prompt,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "api_key_ref": self.api_key_ref,
            "skills": self.skills or [],
            "capabilities": self.capabilities or [],
            "success_rate": self.success_rate or 0.0,
            "average_score": self.average_score or 0.0,
            "execution_count": self.execution_count or 0,
            "strengths": self.strengths or [],
            "weaknesses": self.weaknesses or [],
            "learned_patterns": self.learned_patterns or [],
            "failed_patterns": self.failed_patterns or [],
            "preferred_tools": self.preferred_tools or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class APIKey(Base):
    __tablename__ = "apikeys"

    id = Column(String, primary_key=True, default=gen_uuid)
    provider = Column(String, nullable=False, index=True)  # "openai", "deepseek", "anthropic"
    label = Column(String, nullable=False)                  # user-defined name
    api_key = Column(String, nullable=False)                # encrypted (Fernet) value
    key_hash = Column(String, nullable=True)                # SHA-256[:16] for validation
    base_url = Column(String, nullable=True)                # custom endpoint
    is_active = Column("is_active", String, default="1")    # "1" = active, "0" = revoked
    workspace_id = Column(String, nullable=True, index=True)  # keys scoped to a workspace
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    channel_id = Column(String, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)         # "user" | "ai" | "system"
    author_name = Column(String, nullable=False)   # display name
    author_id = Column(String, nullable=True)      # LEGACY — kept for existing DB rows; new code writes teammate_id only
    teammate_id = Column(String, nullable=True)    # NEW: unified teammate_id (equals role)
    message_id = Column(String, nullable=True)     # NEW: per-teammate uuid (group key)
    avatar_emoji = Column(String, default="🤖")    # display avatar
    status = Column(String, default="unread")       # unread | processing | replied | read | error
    content = Column(Text, default="")
    attachments = Column(JSON, nullable=True)       # list of file metadata
    created_at = Column(DateTime, default=utcnow)

    channel = relationship("Channel", back_populates="messages")


# ═══════════════════════════════════════════════════════════
# RAG System Models
# ═══════════════════════════════════════════════════════════


class FileUpload(Base):
    __tablename__ = "file_uploads"

    id = Column(String, primary_key=True, default=gen_uuid)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)       # pdf | docx | txt | md
    size = Column(String, default="0")               # bytes as string for SQLite compatibility
    user_id = Column(String, nullable=False, index=True)
    status = Column(String, default="pending")       # pending | processing | ready | error
    error_message = Column(Text, default="")
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    chunks = relationship("FileChunk", back_populates="file", cascade="all, delete-orphan",
                           order_by="FileChunk.index")


class FileChunk(Base):
    __tablename__ = "file_chunks"

    id = Column(String, primary_key=True, default=gen_uuid)
    file_id = Column(String, ForeignKey("file_uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    index = Column("index", String, default="0")      # chunk index as string for SQLite (quoted for reserved word)
    embedding = Column(Text, nullable=True)          # JSON-serialized embedding vector
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    file = relationship("FileUpload", back_populates="chunks")


# ═══════════════════════════════════════════════════════════
# Attachment Context (immutable, versioned, shared)
# ═══════════════════════════════════════════════════════════


class AttachmentContextModel(Base):
    """
    Persistent cache for parsed AttachmentContext.

    Keyed by (file_id, content_hash) — same file + same hash = same row.
    Immutable: never UPDATE, only INSERT.
    """
    __tablename__ = "attachment_contexts"

    id = Column(String, primary_key=True, default=gen_uuid)
    file_id = Column(String, nullable=False, index=True)
    content_hash = Column(String, nullable=False, index=True)
    type = Column(String, default="text")
    summary = Column(Text, default="")
    chunks_json = Column(Text, default="[]")     # JSON-serialized list[str]
    entities_json = Column(Text, default="[]")   # JSON-serialized list[str]
    metadata_json = Column(Text, default="{}")   # JSON-serialized dict
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        # Unique constraint: one context per (file_id, content_hash)
        {"sqlite_autoincrement": True},
    )


# ═══════════════════════════════════════════════════════════════
# v2.5 Task Execution Layer Models
# ═══════════════════════════════════════════════════════════════

from sqlalchemy import Integer


class TaskStatus:
    """Task lifecycle states (stored as string in DB)."""
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CREATED = "CREATED"      # alias for PENDING — legacy compat
    EXECUTING = "EXECUTING"  # alias for RUNNING — legacy compat
    PAUSED = "PAUSED"        # legacy compat, not in new pipeline
    CANCELLED = "CANCELLED"  # legacy compat

    CHOICES = [
        PENDING, PLANNING, ASSIGNED, RUNNING,
        COMPLETED, FAILED,
        # legacy compat
        CREATED, EXECUTING, PAUSED, CANCELLED,
    ]

    TRANSITIONS = {
        PENDING: [PLANNING, FAILED, CANCELLED],
        PLANNING: [ASSIGNED, RUNNING, EXECUTING, FAILED, CANCELLED],
        ASSIGNED: [RUNNING, CANCELLED],
        RUNNING: [COMPLETED, FAILED, CANCELLED, PAUSED],
        COMPLETED: [],        # terminal
        FAILED: [PLANNING],    # allow re-plan
        CANCELLED: [],         # terminal
        # legacy compat
        CREATED: [PLANNING, CANCELLED, EXECUTING],
        EXECUTING: [COMPLETED, FAILED, PAUSED, CANCELLED],
        PAUSED: [RUNNING, EXECUTING, CANCELLED],
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, [])


class TaskStepStatus:
    """Step lifecycle states."""
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

    CHOICES = [
        PENDING, SCHEDULED, RUNNING, COMPLETED, FAILED, SKIPPED,
    ]

    TRANSITIONS = {
        PENDING: [SCHEDULED, SKIPPED, RUNNING, FAILED],
        SCHEDULED: [RUNNING, SKIPPED],
        RUNNING: [COMPLETED, FAILED],
        COMPLETED: [],
        FAILED: [PENDING],    # allow retry
        SKIPPED: [],
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, [])


class TaskModel(Base):
    """A multi-step task within a channel/workspace."""
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=gen_uuid)
    channel_id = Column(
        String,
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False, index=True)
    description = Column(Text, default="")

    status = Column(String, nullable=False, default=TaskStatus.PENDING, index=True)
    priority = Column(Integer, default=2)

    intent = Column(String, default="")
    review_status = Column(String, nullable=False, default="pending", index=True)  # pending | approved | rejected
    git_commit = Column(String, nullable=True)

    # ── Closure persistence (Engineer/Reviewer output written back here) ──
    files_changed = Column(JSON, default=list)
    commands_run = Column(JSON, default=list)
    test_result = Column(Text, default="")
    review_comments = Column(Text, default="")
    review_rounds = Column(Integer, default=0)

    # ── Phase 25: TechLead decision & synthesis ──
    techlead_decision = Column(JSON, nullable=True)   # review output: analysis, risk, recs
    techlead_summary = Column(Text, default="")       # human-readable post-exec synthesis

    # ── Phase 27: TechLead replan tracking ──
    replan_decisions = Column(JSON, default=list)     # list of replan records
    replan_count = Column(Integer, default=0)         # how many replans happened

    # ── Phase 27: Current active run ──
    current_run_id = Column(String, nullable=True, index=True)  # points to active TaskRunModel

    # ── DAG hierarchy: parent_task / child_task / dependency ──
    parent_task_id = Column(String, ForeignKey("tasks.id"), nullable=True, index=True)
    child_task_ids = Column(JSON, default=list)
    dependency = Column(JSON, default=list)

    created_by = Column(String, nullable=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)

    steps = relationship(
        "TaskStepModel",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStepModel.order",
    )

    policy = relationship(
        "TaskPolicyModel",
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "intent": self.intent,
            "review_status": self.review_status,
            "git_commit": self.git_commit,
            "files_changed": self.files_changed or [],
            "commands_run": self.commands_run or [],
            "test_result": self.test_result or "",
            "review_comments": self.review_comments or "",
            "review_rounds": self.review_rounds or 0,
            "current_run_id": self.current_run_id,
            "techlead_decision": self.techlead_decision,
            "techlead_summary": self.techlead_summary or "",
            "replan_decisions": self.replan_decisions or [],
            "replan_count": self.replan_count or 0,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": self.child_task_ids or [],
            "dependency": self.dependency or [],
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "steps_count": len(self.steps) if self.steps else 0,
        }

    def to_dict_detail(self) -> dict:
        return {**self.to_dict(), "steps": [s.to_dict() for s in (self.steps or [])]}


class TaskStepModel(Base):
    """A single step within a Task."""
    __tablename__ = "task_steps"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teammate_id = Column(String, nullable=True)
    order = Column(Integer, nullable=False)
    deps = Column(JSON, default=list)  # step ids this step depends on (DAG edges)

    objective = Column(Text, default="")
    input_context = Column(Text, default="")
    output = Column(Text, default="")

    status = Column(String, nullable=False, default=TaskStepStatus.PENDING)
    maeos_task_id = Column(String, nullable=True)
    error = Column(Text, default="")
    retry_count = Column(Integer, default=0)

    # v2.5 Phase C1: Human Approval
    requires_approval = Column(String, default="0")  # "0" = no, "1" = yes (SQLite lacks BOOL)

    # v2.6 Phase C: Step origin tracking
    source = Column(String, default="MANUAL")  # MANUAL | PLANNER | SYSTEM

    # Phase 27: Run grouping
    run_id = Column(String, nullable=True, index=True)  # task_runs.id

    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    task = relationship("TaskModel", back_populates="steps")
    executions = relationship(
        "TaskExecutionModel",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="TaskExecutionModel.attempt",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "teammate_id": self.teammate_id,
            "order": self.order,
            "deps": self.deps or [],
            "objective": self.objective,
            "input_context": self.input_context,
            "output": self.output,
            "status": self.status,
            "maeos_task_id": self.maeos_task_id,
            "error": self.error,
            "retry_count": self.retry_count,
            "source": self.source,
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TaskExecutionModel(Base):
    """Execution record for a single TaskStep attempt."""
    __tablename__ = "task_executions"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_step_id = Column(
        String,
        ForeignKey("task_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    maeos_task_id = Column(String, nullable=True)
    trace_id = Column(String, nullable=True)
    attempt = Column(Integer, default=1)

    # Trace fields
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    teammate_id = Column(String, nullable=True)
    model_name = Column(String, nullable=True)

    # Performance
    execution_time_ms = Column(Integer, default=0)

    # Token / Cost tracking
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated_cost = Column(Integer, default=0)  # micro-dollars (µ$) for precision
    token_usage = Column(Integer, default=0)     # LEGACY — kept for compatibility
    cost = Column(Integer, default=0)            # LEGACY — kept for compatibility

    output_snapshot = Column(Text, default="")
    error = Column(Text, default="")

    created_at = Column(DateTime, default=utcnow)

    step = relationship("TaskStepModel", back_populates="executions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_step_id": self.task_step_id,
            "maeos_task_id": self.maeos_task_id,
            "trace_id": self.trace_id,
            "attempt": self.attempt,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "teammate_id": self.teammate_id,
            "model_name": self.model_name,
            "execution_time_ms": self.execution_time_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost": self.estimated_cost,
            "token_usage": self.token_usage,
            "cost": self.cost,
            "output_snapshot": self.output_snapshot,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════
# v2.5 Phase C1: Human Approval Layer
# ═══════════════════════════════════════════════════════════════


class ApprovalStatus:
    """Approval lifecycle states."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    CHOICES = [PENDING, APPROVED, REJECTED, EXPIRED]


class TaskApprovalModel(Base):
    """A human approval request linked to a task/step."""
    __tablename__ = "task_approvals"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id = Column(
        String,
        ForeignKey("task_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(String, nullable=False, default=ApprovalStatus.PENDING, index=True)
    reason = Column(Text, default="")  # user's reason for approval/rejection

    requested_at = Column(DateTime, default=utcnow)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String, nullable=True)  # user identifier

    task = relationship("TaskModel", backref="approvals")
    step = relationship("TaskStepModel", backref="approvals")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "status": self.status,
            "reason": self.reason,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": self.approved_by,
        }


# ═══════════════════════════════════════════════════════════════
# v2.5 Phase C2: Task Policy Layer
# ═══════════════════════════════════════════════════════════════


class RiskLevel:
    """Risk levels for task execution policies."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CHOICES = [LOW, MEDIUM, HIGH]


class TaskPolicyModel(Base):
    """Configurable execution policy for a Task.

    Replaces hardcoded step-level flags with a per-task policy
    evaluated at runtime by the Policy Service.
    """
    __tablename__ = "task_policies"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one policy per task
        index=True,
    )

    approval_required = Column(String, default="1")      # "0"|"1"
    max_retry = Column(Integer, default=2)                # max retry per step
    max_cost = Column(Integer, default=0)                 # max cost in cents (0=unlimited)
    risk_level = Column(String, default=RiskLevel.LOW)    # LOW|MEDIUM|HIGH

    # JSON array of teammate IDs allowed to execute steps
    allowed_teammates = Column(Text, default="[]")

    created_at = Column(DateTime, default=utcnow)

    task = relationship("TaskModel", back_populates="policy")

    def get_allowed_teammates(self) -> list[str]:
        """Parse allowed_teammates JSON."""
        import json
        try:
            return json.loads(self.allowed_teammates or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "approval_required": self.approval_required,
            "max_retry": self.max_retry,
            "max_cost": self.max_cost,
            "risk_level": self.risk_level,
            "allowed_teammates": self.get_allowed_teammates(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════

class PolicyEffect:
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"
    CHOICES = [ALLOW, DENY, APPROVAL_REQUIRED]


class PolicyRuleModel(Base):
    """A policy rule: who (subject) can/cannot do what (action) on what (resource)."""
    __tablename__ = "policy_rules"

    id = Column(String, primary_key=True, default=gen_uuid)
    subject = Column(String, nullable=False, index=True)    # role/teammate-id
    action = Column(String, nullable=False, index=True)      # file_write | git.merge | …
    resource = Column(String, default="*", index=True)       # glob pattern or "*"
    effect = Column(String, nullable=False, default=PolicyEffect.ALLOW)
    reason = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "action": self.action,
            "resource": self.resource,
            "effect": self.effect,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def _resource_matches(self, target: str) -> bool:
        """Simple glob match: '*' matches everything, prefix/suffix wildcards work."""
        if self.resource == "*":
            return True
        if self.resource.startswith("*") and self.resource.endswith("*"):
            return self.resource[1:-1] in target
        if self.resource.endswith("*"):
            return target.startswith(self.resource[:-1])
        return target == self.resource


# ═══════════════════════════════════════════════════════════════
# v3.2 Phase A: Execution Persistence Models
# ═══════════════════════════════════════════════════════════════

from sqlalchemy import Float, Integer as SAInteger


class ExecutionRecordModel(Base):
    """Persistent execution record — one per runtime execution."""
    __tablename__ = "execution_records"

    execution_id = Column(String, primary_key=True)
    task_id = Column(String, default="", index=True)
    teammate = Column(String, default="")
    model = Column(String, default="")
    status = Column(String, default="PENDING", index=True)
    start_time = Column(Float, default=0.0)
    end_time = Column(Float, default=0.0)
    duration_ms = Column(SAInteger, default=0)
    prompt_tokens = Column(SAInteger, default=0)
    completion_tokens = Column(SAInteger, default=0)
    total_tokens = Column(SAInteger, default=0)
    cost_micro_usd = Column(SAInteger, default=0)
    error = Column(Text, default="")
    dag_id = Column(String, default="", index=True)
    dag_node_id = Column(String, default="", index=True)
    created_at = Column(DateTime, default=utcnow)

    events = relationship(
        "ExecutionEventModel",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="ExecutionEventModel.timestamp",
    )


class ExecutionEventModel(Base):
    """One event in an execution's timeline."""
    __tablename__ = "execution_events"

    id = Column(SAInteger, primary_key=True, autoincrement=True)
    execution_id = Column(
        String,
        ForeignKey("execution_records.execution_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String, nullable=False)
    timestamp = Column(Float, default=0.0)
    payload = Column(JSON, default=dict)

    execution = relationship("ExecutionRecordModel", back_populates="events")


# ═══════════════════════════════════════════════════════════════
# v2.6 Phase D: Planner Review Layer
# ═══════════════════════════════════════════════════════════════


class PlanReviewStatus:
    """Plan review lifecycle states."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    CHOICES = [PENDING, APPROVED, REJECTED]


class TaskPlanReviewModel(Base):
    """A review / approval gate for a TaskPlan before it can be applied.

    One review per plan. Status determines whether the plan
    can be converted to TaskStep records.
    """
    __tablename__ = "task_plan_reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    plan_id = Column(
        String,
        ForeignKey("task_plans.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status = Column(String, nullable=False, default=PlanReviewStatus.PENDING, index=True)
    reviewer = Column(String, default="")       # reviewer identifier
    comment = Column(Text, default="")           # review comment / rejection reason
    created_at = Column(DateTime, default=utcnow)

    plan = relationship("TaskPlanModel", backref="review", uselist=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "status": self.status,
            "reviewer": self.reviewer,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════
# v2.6 Phase C: Planner Task Plan Model
# ═══════════════════════════════════════════════════════════════


class PlanStatus:
    """Plan lifecycle states (stored as string in DB)."""
    ACTIVE = "ACTIVE"         # Generated, not yet applied
    APPLIED = "APPLIED"       # Converted to steps
    SUPERSEDED = "SUPERSEDED" # Replaced by a newer plan
    DISCARDED = "DISCARDED"   # Rejected / abandoned

    CHOICES = [ACTIVE, APPLIED, SUPERSEDED, DISCARDED]


class TaskPlanModel(Base):
    """Persistent storage for a Planner-generated TaskPlan.

    One task may have multiple plans historically; status tracks
    which plan is active/applied vs. superseded.
    """
    __tablename__ = "task_plans"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String, nullable=False)
    description = Column(Text, default="")
    confidence = Column(String, default="0.0")       # text for precision
    rationale = Column(Text, default="")
    risk_level = Column(String, default="LOW")        # LOW | MEDIUM | HIGH
    estimated_cost = Column(String, default="0")      # micro-dollars as text
    status = Column(String, default=PlanStatus.ACTIVE, index=True)

    # Serialized step proposals (JSON list)
    steps_json = Column(Text, default="[]")

    created_at = Column(DateTime, default=utcnow)

    task = relationship("TaskModel", backref="plans")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "risk_level": self.risk_level,
            "estimated_cost": self.estimated_cost,
            "status": self.status,
            "steps_count": self._steps_count(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def _steps_count(self) -> int:
        import json
        try:
            return len(json.loads(self.steps_json or "[]"))
        except (json.JSONDecodeError, TypeError):
            return 0


# ═══════════════════════════════════════════════════════════════
# v2.7 Phase A: ExecutionResult Foundation
# ═══════════════════════════════════════════════════════════════


class ExecutionOutcome:
    """Execution result outcome states."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"

    CHOICES = [SUCCESS, FAILURE, PARTIAL, SKIPPED]


class ExecutionResultStatus:
    """ExecutionResult lifecycle states."""
    CREATED = "CREATED"
    EVALUATED = "EVALUATED"
    COMPARED = "COMPARED"
    CLOSED = "CLOSED"
    REPLAN_TRIGGERED = "REPLAN_TRIGGERED"

    CHOICES = [CREATED, EVALUATED, COMPARED, CLOSED, REPLAN_TRIGGERED]


class PlanMatchSeverity:
    """Severity of plan deviation."""
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"

    CHOICES = [NONE, MINOR, MAJOR, CRITICAL]


class FailureCategory:
    """Primary failure classification categories."""
    SYSTEM = "SYSTEM"
    LOGIC = "LOGIC"
    QUALITY = "QUALITY"
    POLICY = "POLICY"
    UNKNOWN = "UNKNOWN"

    CHOICES = [SYSTEM, LOGIC, QUALITY, POLICY, UNKNOWN]


class ExecutionResultModel(Base):
    """
    ExecutionResult — 单步执行的结构化反馈记录.

    Phase A: 基础数据层. 记录 step 执行的结构化结果元数据,
    包括 outcome、质量评分、计划偏差、失败分类等.

    后续 Phase B-D 将在此基础上实现评估、分类和重规划逻辑.
    """
    __tablename__ = "execution_results"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_step_id = Column(
        String,
        ForeignKey("task_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_execution_id = Column(
        String,
        ForeignKey("task_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Outcome ──
    outcome = Column(String, nullable=False, default=ExecutionOutcome.SUCCESS, index=True)

    # ── Quality Score ──
    completeness = Column(Float, default=0.0)
    coherence = Column(Float, default=0.0)
    accuracy = Column(Float, default=0.0)
    overall_quality = Column(Float, default=0.0)

    # ── Plan Deviation ──
    plan_matched = Column(String, default=PlanMatchSeverity.NONE)
    plan_deviation_detail = Column(Text, default="")

    # ── Failure Classification ──
    failure_category = Column(String, default="")
    failure_subcategory = Column(String, default="")
    is_recoverable = Column(String, default="1")  # "0" | "1"

    # ── Evaluation Metadata ──
    evaluator = Column(String, default="llm")
    evaluation_confidence = Column(Float, default=0.0)

    # ── Lifecycle ──
    status = Column(String, nullable=False, default=ExecutionResultStatus.CREATED, index=True)
    replan_triggered = Column(String, default="0")  # "0" | "1"
    replan_scope = Column(String, default="")       # "" | STEP | TASK | CONTEXT

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # ── Relationships ──
    step = relationship(
        "TaskStepModel",
        backref=backref("execution_results", cascade="all, delete-orphan"),
    )
    execution = relationship(
        "TaskExecutionModel",
        backref=backref("execution_results", cascade="all, delete-orphan"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_step_id": self.task_step_id,
            "task_execution_id": self.task_execution_id,
            "outcome": self.outcome,
            "completeness": self.completeness,
            "coherence": self.coherence,
            "accuracy": self.accuracy,
            "overall_quality": self.overall_quality,
            "plan_matched": self.plan_matched,
            "plan_deviation_detail": self.plan_deviation_detail,
            "failure_category": self.failure_category,
            "failure_subcategory": self.failure_subcategory,
            "is_recoverable": self.is_recoverable,
            "evaluator": self.evaluator,
            "evaluation_confidence": self.evaluation_confidence,
            "status": self.status,
            "replan_triggered": self.replan_triggered,
            "replan_scope": self.replan_scope,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ═══════════════════════════════════════════════════════════════
# Phase 6: Evaluation System (v1.0)
# ═══════════════════════════════════════════════════════════════


class EvaluationRecordModel(Base):
    """Execution-level evaluation record — one per execution_id.

    Rule-based scores (0.0–1.0) for latency, cost, artifact presence,
    and error status.  Overall score is a weighted combination.
    """
    __tablename__ = "evaluation_records"

    id = Column(String, primary_key=True, default=gen_uuid)
    execution_id = Column(
        String,
        ForeignKey("execution_records.execution_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    score = Column(Float, default=0.0)            # overall 0–1
    status = Column(String, default="PENDING", index=True)  # PENDING | EVALUATED
    latency_score = Column(Float, default=0.0)     # 0–1 (faster → higher)
    cost_score = Column(Float, default=0.0)         # 0–1 (cheaper → higher)
    artifact_score = Column(Float, default=0.0)     # 0–1 (more/better artifacts → higher)
    error_score = Column(Float, default=1.0)        # 0–1 (no error → 1.0)
    feedback = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    execution = relationship("ExecutionRecordModel", backref="evaluation", uselist=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "score": self.score,
            "status": self.status,
            "latency_score": self.latency_score,
            "cost_score": self.cost_score,
            "artifact_score": self.artifact_score,
            "error_score": self.error_score,
            "feedback": self.feedback,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════
# Phase 5: Artifact System (v1.0)
# ═══════════════════════════════════════════════════════════════


class ArtifactModel(Base):
    """An AI-generated artifact (file, image, code, etc.) produced by an execution."""
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    execution_id = Column(String, nullable=True, index=True)
    type = Column(String, nullable=False, default="file", index=True)   # "file" | "image" | "code" | "text" | ...
    name = Column(String, nullable=False)
    path = Column(String, nullable=False)          # filesystem path of stored content
    content_hash = Column(String, default="")       # SHA-256[:16] quick dedup
    meta = Column(JSON, default=dict)               # arbitrary key-value (not named 'metadata' — reserved in SA)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "type": self.type,
            "name": self.name,
            "path": self.path,
            "content_hash": self.content_hash,
            "metadata": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════
# Phase 9: DAG Persistence Models
# ═══════════════════════════════════════════════════════════════


class DAGDefinitionModel(Base):
    """Persistent DAG definition."""
    __tablename__ = "dag_definitions"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, default="")
    status = Column(String, default="CREATED")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    nodes = relationship("DAGNodeModel", back_populates="dag",
                         cascade="all, delete-orphan",
                         order_by="DAGNodeModel.created_at")


class DAGNodeModel(Base):
    """Persistent DAG node — one task in a DAG."""
    __tablename__ = "dag_nodes"

    id = Column(String, primary_key=True, default=gen_uuid)
    dag_id = Column(String, ForeignKey("dag_definitions.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    description = Column(Text, default="")
    teammate = Column(String, default="")
    deps = Column(JSON, default=list)
    status = Column(String, default="PENDING", index=True)
    max_retry = Column(SAInteger, default=0)
    retry_count = Column(SAInteger, default=0)
    strategy = Column(String, default="linear")
    require_approval = Column(String, default="0")  # "0" | "1" — SQLite lacks BOOL
    result = Column(Text, default="")
    error = Column(Text, default="")
    execution_id = Column(String, default="")
    required_skills = Column(JSON, default=list)
    selected_teammate_id = Column(String, default="")
    assigned_at = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)

    dag = relationship("DAGDefinitionModel", back_populates="nodes")


# ═══════════════════════════════════════════════════════════════
# Phase 7: Automation Rule
# ═══════════════════════════════════════════════════════════════


class AutomationRuleModel(Base):
    """Scheduled task automation rule — triggers task creation on interval."""
    __tablename__ = "automation_rules"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    schedule_interval_sec = Column(SAInteger, default=300)  # 5 min default
    task_title = Column(String, nullable=False)
    task_intent = Column(Text, default="")
    channel_id = Column(String, default="")
    team_ids = Column(JSON, default=list)  # list of teammate IDs to include
    is_active = Column(String, default="1")
    trigger_event = Column(String, nullable=True)  # Phase 19: event-triggered (e.g. "task_created", "message_event")
    last_triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ═══════════════════════════════════════════════════════════════
# Phase 30: Automation Job — Teammate Autonomous Automation Engine v2
# ═══════════════════════════════════════════════════════════════


class AutomationJobModel(Base):
    """Recurring/event-driven automation job tied to a specific teammate identity."""
    __tablename__ = "automation_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, default="")
    teammate_id = Column(String, default="", index=True)
    name = Column(String, nullable=False)
    trigger_type = Column(String, default="manual")  # cron | event | webhook | manual
    schedule_expression = Column(String, default="")  # cron expression or ISO interval
    goal = Column(Text, default="")
    sop_definition = Column(JSON, default=dict)  # structured SOP steps
    status = Column(String, default="active")  # active | paused | archived
    is_active = Column(String, default="1")
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AutomationRunModel(Base):
    """Execution record of an automation job."""
    __tablename__ = "automation_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    job_id = Column(
        String,
        ForeignKey("automation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger = Column(String, default="manual")
    actions = Column(JSON, default=list)
    result = Column(Text, default="")
    artifact = Column(JSON, default=dict)
    created_tasks = Column(JSON, default=list)  # task IDs created during this run
    status = Column(String, default="pending")  # pending | running | completed | failed
    error = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ═══════════════════════════════════════════════════════════════
# Phase 17: Policy Audit Decision Model
# ═══════════════════════════════════════════════════════════════


class PolicyDecisionModel(Base):
    """Every policy ALLOW/DENY/APPROVAL_REQUIRED → one row."""
    __tablename__ = "policy_decisions"

    id = Column(String, primary_key=True, default=gen_uuid)
    teammate_id = Column(String, default="", index=True)
    action = Column(String, nullable=False, index=True)
    resource = Column(String, default="*")
    effect = Column(String, nullable=False, index=True)  # ALLOW | DENY | APPROVAL_REQUIRED
    reason = Column(String, default="")
    task_id = Column(String, default="", index=True)
    workspace_id = Column(String, default="")
    channel_id = Column(String, default="")
    context_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "teammate_id": self.teammate_id,
            "action": self.action,
            "resource": self.resource,
            "effect": self.effect,
            "reason": self.reason,
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "channel_id": self.channel_id,
            "context": self.context_json if isinstance(self.context_json, dict) else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════
# Phase 27: TaskRun — groups one execution cycle of a Task
# ═══════════════════════════════════════════════════════════════


class TaskRunStatus:
    """TaskRun lifecycle states."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    CHOICES = [PENDING, RUNNING, COMPLETED, FAILED]


class TaskRunModel(Base):
    """
    One execution run of a Task.

    A task can be executed multiple times (replan, retry). Each
    invocation creates a TaskRun that groups all steps and execution
    records produced during that cycle.
    """
    __tablename__ = "task_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_number = Column(SAInteger, default=1)    # auto-increment per task
    status = Column(String, default=TaskRunStatus.PENDING, index=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, default="")
    summary = Column(Text, default="")

    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "run_number": self.run_number,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════
# Teammate Blueprint Template
# ═══════════════════════════════════════════════════════════


class TeammateTemplate(Base):
    """Pre-built teammate blueprint for one-click creation."""
    __tablename__ = "teammate_templates"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    identity = Column(String, default="")
    system_prompt = Column(Text, default="")
    skills = Column(JSON, default=list)
    tools = Column(JSON, default=list)
    memory_schema = Column(JSON, default=dict)
    automation_defaults = Column(JSON, default=dict)
    avatar_emoji = Column(String, default="🤖")
    model_provider = Column(String, default="openrouter")
    model_name = Column(String, default="openrouter/auto")
    created_at = Column(DateTime, default=utcnow)


# ═══════════════════════════════════════════════════════════
# Board Task — lightweight claim board (Phase 28)
#   Distinct from the heavy `tasks` execution-engine table: no DAG / steps /
#   TechLead / replan. This is a plain to-do board scoped to a workspace, with
#   a single optimistically-locked assignee for concurrency-safe claiming.
# ═══════════════════════════════════════════════════════════

class BoardTask(Base):
    """A lightweight, claimable task on a channel's board.

    Severely trimmed vs the execution-engine `tasks` table — no steps, DAG,
    replan, or review. One assignee, optimistic-lock claim (WHERE assignee_id
    IS NULL → rowcount==0 means lost the race → 409).
    """
    __tablename__ = "board_tasks"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=False, index=True)  # ponytail: scope is mandatory
    channel_id = Column(
        String,
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    source_message_id = Column(String, nullable=True, index=True)  # trace back to originating message
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, nullable=False, default="open", index=True)  # open | in_progress | done
    priority = Column(Integer, default=2)  # 1 high … 3 low
    assignee_id = Column(String, nullable=True, index=True)  # NULL = unclaimed; claim sets this
    assignee_name = Column(String, nullable=True)
    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "channel_id": self.channel_id,
            "source_message_id": self.source_message_id,
            "title": self.title,
            "description": self.description or "",
            "status": self.status,
            "priority": self.priority,
            "assignee_id": self.assignee_id,
            "assignee_name": self.assignee_name,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
