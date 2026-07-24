"""Task execution models — task engine, DAG, policy, automation, board, evaluation."""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Float, Integer as SAInteger
from sqlalchemy.orm import relationship, backref

from backend.database import Base
from ._helpers import gen_uuid, utcnow


# ── Status Enums ──


class TaskStatus:
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CREATED = "CREATED"
    EXECUTING = "EXECUTING"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"

    CHOICES = [
        PENDING, PLANNING, ASSIGNED, RUNNING,
        COMPLETED, FAILED,
        CREATED, EXECUTING, PAUSED, CANCELLED,
    ]

    TRANSITIONS = {
        PENDING: [PLANNING, FAILED, CANCELLED],
        PLANNING: [ASSIGNED, RUNNING, EXECUTING, FAILED, CANCELLED],
        ASSIGNED: [RUNNING, CANCELLED],
        RUNNING: [COMPLETED, FAILED, CANCELLED, PAUSED],
        COMPLETED: [],
        FAILED: [PLANNING],
        CANCELLED: [],
        CREATED: [PLANNING, CANCELLED, EXECUTING],
        EXECUTING: [COMPLETED, FAILED, PAUSED, CANCELLED],
        PAUSED: [RUNNING, EXECUTING, CANCELLED],
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, [])


class TaskStepStatus:
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

    CHOICES = [PENDING, SCHEDULED, RUNNING, COMPLETED, FAILED, SKIPPED]

    TRANSITIONS = {
        PENDING: [SCHEDULED, SKIPPED, RUNNING, FAILED],
        SCHEDULED: [RUNNING, SKIPPED],
        RUNNING: [COMPLETED, FAILED],
        COMPLETED: [],
        FAILED: [PENDING],
        SKIPPED: [],
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, [])


class ApprovalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CHOICES = [PENDING, APPROVED, REJECTED, EXPIRED]


class RiskLevel:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CHOICES = [LOW, MEDIUM, HIGH]


class PlanReviewStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHOICES = [PENDING, APPROVED, REJECTED]


class PlanStatus:
    ACTIVE = "ACTIVE"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"
    CHOICES = [ACTIVE, APPLIED, SUPERSEDED, DISCARDED]


class PolicyEffect:
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"
    CHOICES = [ALLOW, DENY, APPROVAL_REQUIRED]


class ExecutionOutcome:
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"
    CHOICES = [SUCCESS, FAILURE, PARTIAL, SKIPPED]


class ExecutionResultStatus:
    CREATED = "CREATED"
    EVALUATED = "EVALUATED"
    COMPARED = "COMPARED"
    CLOSED = "CLOSED"
    REPLAN_TRIGGERED = "REPLAN_TRIGGERED"
    CHOICES = [CREATED, EVALUATED, COMPARED, CLOSED, REPLAN_TRIGGERED]


class PlanMatchSeverity:
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"
    CHOICES = [NONE, MINOR, MAJOR, CRITICAL]


class FailureCategory:
    SYSTEM = "SYSTEM"
    LOGIC = "LOGIC"
    QUALITY = "QUALITY"
    POLICY = "POLICY"
    UNKNOWN = "UNKNOWN"
    CHOICES = [SYSTEM, LOGIC, QUALITY, POLICY, UNKNOWN]


class TaskRunStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CHOICES = [PENDING, RUNNING, COMPLETED, FAILED]


# ── Task Execution Models ──


class TaskModel(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=gen_uuid)
    channel_id = Column(String, ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True)
    workspace_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    status = Column(String, nullable=False, default=TaskStatus.PENDING, index=True)
    priority = Column(SAInteger, default=2)
    intent = Column(String, default="")
    review_status = Column(String, nullable=False, default="pending", index=True)
    git_commit = Column(String, nullable=True)
    files_changed = Column(JSON, default=list)
    commands_run = Column(JSON, default=list)
    test_result = Column(Text, default="")
    review_comments = Column(Text, default="")
    review_rounds = Column(SAInteger, default=0)
    techlead_decision = Column(JSON, nullable=True)
    techlead_summary = Column(Text, default="")
    replan_decisions = Column(JSON, default=list)
    replan_count = Column(SAInteger, default=0)
    current_run_id = Column(String, nullable=True, index=True)
    run_id = Column(String, nullable=True, index=True)
    parent_task_id = Column(String, ForeignKey("tasks.id"), nullable=True, index=True)
    child_task_ids = Column(JSON, default=list)
    dependency = Column(JSON, default=list)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)

    steps = relationship("TaskStepModel", back_populates="task", cascade="all, delete-orphan",
                         order_by="TaskStepModel.order")
    policy = relationship("TaskPolicyModel", back_populates="task", cascade="all, delete-orphan", uselist=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "channel_id": self.channel_id, "workspace_id": self.workspace_id,
            "title": self.title, "description": self.description, "status": self.status,
            "priority": self.priority, "intent": self.intent, "review_status": self.review_status,
            "git_commit": self.git_commit,
            "files_changed": self.files_changed or [], "commands_run": self.commands_run or [],
            "test_result": self.test_result or "", "review_comments": self.review_comments or "",
            "review_rounds": self.review_rounds or 0, "current_run_id": self.current_run_id,
            "techlead_decision": self.techlead_decision, "techlead_summary": self.techlead_summary or "",
            "replan_decisions": self.replan_decisions or [], "replan_count": self.replan_count or 0,
            "parent_task_id": self.parent_task_id, "child_task_ids": self.child_task_ids or [],
            "dependency": self.dependency or [], "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "steps_count": len(self.steps) if self.steps else 0,
        }

    def to_dict_detail(self) -> dict:
        return {**self.to_dict(), "steps": [s.to_dict() for s in (self.steps or [])]}


class TaskStepModel(Base):
    __tablename__ = "task_steps"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    teammate_id = Column(String, nullable=True)
    order = Column(SAInteger, nullable=False)
    deps = Column(JSON, default=list)
    objective = Column(Text, default="")
    input_context = Column(Text, default="")
    output = Column(Text, default="")
    status = Column(String, nullable=False, default=TaskStepStatus.PENDING)
    maeos_task_id = Column(String, nullable=True)
    error = Column(Text, default="")
    retry_count = Column(SAInteger, default=0)
    requires_approval = Column(String, default="0")
    source = Column(String, default="MANUAL")
    run_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    task = relationship("TaskModel", back_populates="steps")
    executions = relationship("TaskExecutionModel", back_populates="step", cascade="all, delete-orphan",
                              order_by="TaskExecutionModel.attempt")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_id": self.task_id, "teammate_id": self.teammate_id,
            "order": self.order, "deps": self.deps or [],
            "objective": self.objective, "input_context": self.input_context, "output": self.output,
            "status": self.status, "maeos_task_id": self.maeos_task_id, "error": self.error,
            "retry_count": self.retry_count, "source": self.source, "run_id": self.run_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TaskExecutionModel(Base):
    __tablename__ = "task_executions"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_step_id = Column(String, ForeignKey("task_steps.id", ondelete="CASCADE"), nullable=False, index=True)
    maeos_task_id = Column(String, nullable=True)
    trace_id = Column(String, nullable=True)
    attempt = Column(SAInteger, default=1)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    teammate_id = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    execution_time_ms = Column(SAInteger, default=0)
    input_tokens = Column(SAInteger, default=0)
    output_tokens = Column(SAInteger, default=0)
    total_tokens = Column(SAInteger, default=0)
    estimated_cost = Column(SAInteger, default=0)
    token_usage = Column(SAInteger, default=0)
    cost = Column(SAInteger, default=0)
    output_snapshot = Column(Text, default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    step = relationship("TaskStepModel", back_populates="executions")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_step_id": self.task_step_id,
            "maeos_task_id": self.maeos_task_id, "trace_id": self.trace_id, "attempt": self.attempt,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "teammate_id": self.teammate_id, "model_name": self.model_name,
            "execution_time_ms": self.execution_time_ms,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens, "estimated_cost": self.estimated_cost,
            "token_usage": self.token_usage, "cost": self.cost,
            "output_snapshot": self.output_snapshot, "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TaskApprovalModel(Base):
    __tablename__ = "task_approvals"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String, ForeignKey("task_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String, nullable=False, default=ApprovalStatus.PENDING, index=True)
    reason = Column(Text, default="")
    requested_at = Column(DateTime, default=utcnow)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_id": self.task_id, "step_id": self.step_id,
            "status": self.status, "reason": self.reason,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": self.approved_by,
        }


class TaskPolicyModel(Base):
    __tablename__ = "task_policies"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    approval_required = Column(String, default="1")
    max_retry = Column(SAInteger, default=2)
    max_cost = Column(SAInteger, default=0)
    risk_level = Column(String, default=RiskLevel.LOW)
    allowed_teammates = Column(Text, default="[]")
    created_at = Column(DateTime, default=utcnow)

    task = relationship("TaskModel", back_populates="policy")

    def get_allowed_teammates(self) -> list[str]:
        import json
        try:
            return json.loads(self.allowed_teammates or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_id": self.task_id,
            "approval_required": self.approval_required, "max_retry": self.max_retry,
            "max_cost": self.max_cost, "risk_level": self.risk_level,
            "allowed_teammates": self.get_allowed_teammates(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TaskPlanModel(Base):
    __tablename__ = "task_plans"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    confidence = Column(String, default="0.0")
    rationale = Column(Text, default="")
    risk_level = Column(String, default="LOW")
    estimated_cost = Column(String, default="0")
    status = Column(String, default=PlanStatus.ACTIVE, index=True)
    steps_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_id": self.task_id, "title": self.title,
            "description": self.description, "confidence": self.confidence,
            "rationale": self.rationale, "risk_level": self.risk_level,
            "estimated_cost": self.estimated_cost, "status": self.status,
            "steps_count": self._steps_count(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def _steps_count(self) -> int:
        import json
        try:
            return len(json.loads(self.steps_json or "[]"))
        except (json.JSONDecodeError, TypeError):
            return 0


class TaskPlanReviewModel(Base):
    __tablename__ = "task_plan_reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    plan_id = Column(String, ForeignKey("task_plans.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default=PlanReviewStatus.PENDING, index=True)
    reviewer = Column(String, default="")
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "plan_id": self.plan_id, "status": self.status,
            "reviewer": self.reviewer, "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PolicyRuleModel(Base):
    __tablename__ = "policy_rules"

    id = Column(String, primary_key=True, default=gen_uuid)
    subject = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    resource = Column(String, default="*", index=True)
    effect = Column(String, nullable=False, default=PolicyEffect.ALLOW)
    reason = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "subject": self.subject, "action": self.action,
            "resource": self.resource, "effect": self.effect, "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def _resource_matches(self, target: str) -> bool:
        if self.resource == "*":
            return True
        if self.resource.startswith("*") and self.resource.endswith("*"):
            return self.resource[1:-1] in target
        if self.resource.endswith("*"):
            return target.startswith(self.resource[:-1])
        return target == self.resource


class ExecutionRecordModel(Base):
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

    events = relationship("ExecutionEventModel", back_populates="execution",
                          cascade="all, delete-orphan", order_by="ExecutionEventModel.timestamp")


class ExecutionEventModel(Base):
    __tablename__ = "execution_events"

    id = Column(SAInteger, primary_key=True, autoincrement=True)
    execution_id = Column(String, ForeignKey("execution_records.execution_id", ondelete="CASCADE"),
                          nullable=False, index=True)
    event_type = Column(String, nullable=False)
    timestamp = Column(Float, default=0.0)
    payload = Column(JSON, default=dict)

    execution = relationship("ExecutionRecordModel", back_populates="events")


class ExecutionResultModel(Base):
    __tablename__ = "execution_results"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_step_id = Column(String, ForeignKey("task_steps.id", ondelete="CASCADE"), nullable=False, index=True)
    task_execution_id = Column(String, ForeignKey("task_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    outcome = Column(String, nullable=False, default=ExecutionOutcome.SUCCESS, index=True)
    completeness = Column(Float, default=0.0)
    coherence = Column(Float, default=0.0)
    accuracy = Column(Float, default=0.0)
    overall_quality = Column(Float, default=0.0)
    plan_matched = Column(String, default=PlanMatchSeverity.NONE)
    plan_deviation_detail = Column(Text, default="")
    failure_category = Column(String, default="")
    failure_subcategory = Column(String, default="")
    is_recoverable = Column(String, default="1")
    evaluator = Column(String, default="llm")
    evaluation_confidence = Column(Float, default=0.0)
    status = Column(String, nullable=False, default=ExecutionResultStatus.CREATED, index=True)
    replan_triggered = Column(String, default="0")
    replan_scope = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_step_id": self.task_step_id,
            "task_execution_id": self.task_execution_id,
            "outcome": self.outcome,
            "completeness": self.completeness, "coherence": self.coherence, "accuracy": self.accuracy,
            "overall_quality": self.overall_quality,
            "plan_matched": self.plan_matched, "plan_deviation_detail": self.plan_deviation_detail,
            "failure_category": self.failure_category, "failure_subcategory": self.failure_subcategory,
            "is_recoverable": self.is_recoverable,
            "evaluator": self.evaluator, "evaluation_confidence": self.evaluation_confidence,
            "status": self.status,
            "replan_triggered": self.replan_triggered, "replan_scope": self.replan_scope,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EvaluationRecordModel(Base):
    __tablename__ = "evaluation_records"

    id = Column(String, primary_key=True, default=gen_uuid)
    execution_id = Column(String, ForeignKey("execution_records.execution_id", ondelete="CASCADE"),
                          nullable=False, unique=True, index=True)
    score = Column(Float, default=0.0)
    status = Column(String, default="PENDING", index=True)
    latency_score = Column(Float, default=0.0)
    cost_score = Column(Float, default=0.0)
    artifact_score = Column(Float, default=0.0)
    error_score = Column(Float, default=1.0)
    feedback = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "execution_id": self.execution_id, "score": self.score,
            "status": self.status,
            "latency_score": self.latency_score, "cost_score": self.cost_score,
            "artifact_score": self.artifact_score, "error_score": self.error_score,
            "feedback": self.feedback,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ArtifactModel(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    execution_id = Column(String, nullable=True, index=True)
    type = Column(String, nullable=False, default="file", index=True)
    name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    content_hash = Column(String, default="")
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_id": self.task_id, "execution_id": self.execution_id,
            "type": self.type, "name": self.name, "path": self.path,
            "content_hash": self.content_hash, "metadata": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DAGDefinitionModel(Base):
    __tablename__ = "dag_definitions"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, default="")
    status = Column(String, default="CREATED")
    task_id = Column(String, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    nodes = relationship("DAGNodeModel", back_populates="dag", cascade="all, delete-orphan",
                         order_by="DAGNodeModel.created_at")

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DAGNodeModel(Base):
    __tablename__ = "dag_nodes"

    id = Column(String, primary_key=True, default=gen_uuid)
    dag_id = Column(String, ForeignKey("dag_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(Text, default="")
    teammate = Column(String, default="")
    deps = Column(JSON, default=list)
    status = Column(String, default="PENDING", index=True)
    max_retry = Column(SAInteger, default=0)
    retry_count = Column(SAInteger, default=0)
    strategy = Column(String, default="linear")
    require_approval = Column(String, default="0")
    result = Column(Text, default="")
    error = Column(Text, default="")
    execution_id = Column(String, default="")
    required_skills = Column(JSON, default=list)
    selected_teammate_id = Column(String, default="")
    assigned_at = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)

    dag = relationship("DAGDefinitionModel", back_populates="nodes")

    def to_dict(self):
        return {
            "id": self.id, "dag_id": self.dag_id, "description": self.description,
            "teammate": self.teammate, "deps": self.deps, "status": self.status,
            "max_retry": self.max_retry, "retry_count": self.retry_count,
            "strategy": self.strategy, "require_approval": self.require_approval,
            "result": self.result, "error": self.error,
            "execution_id": self.execution_id,
            "required_skills": self.required_skills,
            "selected_teammate_id": self.selected_teammate_id,
            "assigned_at": self.assigned_at,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AutomationRuleModel(Base):
    __tablename__ = "automation_rules"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    schedule_interval_sec = Column(SAInteger, default=300)
    task_title = Column(String, nullable=False)
    task_intent = Column(Text, default="")
    channel_id = Column(String, default="")
    team_ids = Column(JSON, default=list)
    is_active = Column(String, default="1")
    trigger_event = Column(String, nullable=True)
    last_triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AutomationJobModel(Base):
    __tablename__ = "automation_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, default="")
    teammate_id = Column(String, default="", index=True)
    name = Column(String, nullable=False)
    trigger_type = Column(String, default="manual")
    schedule_expression = Column(String, default="")
    goal = Column(Text, default="")
    sop_definition = Column(JSON, default=dict)
    status = Column(String, default="active")
    is_active = Column(String, default="1")
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AutomationRunModel(Base):
    __tablename__ = "automation_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    job_id = Column(String, ForeignKey("automation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    trigger = Column(String, default="manual")
    actions = Column(JSON, default=list)
    result = Column(Text, default="")
    artifact = Column(JSON, default=dict)
    created_tasks = Column(JSON, default=list)
    status = Column(String, default="pending")
    error = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class PolicyDecisionModel(Base):
    __tablename__ = "policy_decisions"

    id = Column(String, primary_key=True, default=gen_uuid)
    teammate_id = Column(String, default="", index=True)
    action = Column(String, nullable=False, index=True)
    resource = Column(String, default="*")
    effect = Column(String, nullable=False, index=True)
    reason = Column(String, default="")
    task_id = Column(String, default="", index=True)
    workspace_id = Column(String, default="")
    channel_id = Column(String, default="")
    context_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "teammate_id": self.teammate_id, "action": self.action,
            "resource": self.resource, "effect": self.effect, "reason": self.reason,
            "task_id": self.task_id, "workspace_id": self.workspace_id, "channel_id": self.channel_id,
            "context": self.context_json if isinstance(self.context_json, dict) else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TaskRunModel(Base):
    __tablename__ = "task_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    run_number = Column(SAInteger, default=1)
    status = Column(String, default=TaskRunStatus.PENDING, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, default="")
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "task_id": self.task_id, "run_number": self.run_number,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error, "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BoardTask(Base):
    __tablename__ = "board_tasks"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=False, index=True)
    channel_id = Column(String, ForeignKey("channels.id", ondelete="CASCADE"), nullable=True, index=True)
    source_message_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, nullable=False, default="open", index=True)
    priority = Column(SAInteger, default=2)
    assignee_id = Column(String, nullable=True, index=True)
    assignee_name = Column(String, nullable=True)
    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "workspace_id": self.workspace_id, "channel_id": self.channel_id,
            "source_message_id": self.source_message_id, "title": self.title,
            "description": self.description or "", "status": self.status,
            "priority": self.priority,
            "assignee_id": self.assignee_id, "assignee_name": self.assignee_name,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
