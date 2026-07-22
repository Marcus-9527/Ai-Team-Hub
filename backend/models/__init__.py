"""SQLAlchemy models for AI Team Hub.

Re-exports from domain submodules. All existing ``from backend.models import X``
statements continue to work unchanged.
"""
# System
from backend.models.system import User, Workspace, WorkspaceMember, APIKey

# Chat
from backend.models.chat import Channel, Teammate, Message, TeammateTemplate

# Task engine
from backend.models.task import (
    # Status enums
    TaskStatus, TaskStepStatus, ApprovalStatus, RiskLevel,
    PlanReviewStatus, PlanStatus, PolicyEffect,
    ExecutionOutcome, ExecutionResultStatus,
    PlanMatchSeverity, FailureCategory, TaskRunStatus,
    # Task models
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskApprovalModel, TaskPolicyModel,
    TaskPlanModel, TaskPlanReviewModel,
    PolicyRuleModel, PolicyDecisionModel,
    # Execution
    ExecutionRecordModel, ExecutionEventModel,
    ExecutionResultModel,
    # Evaluation
    EvaluationRecordModel,
    # Artifact
    ArtifactModel,
    # DAG
    DAGDefinitionModel, DAGNodeModel,
    # Automation
    AutomationRuleModel, AutomationJobModel, AutomationRunModel,
    # Run
    TaskRunModel,
    # Board
    BoardTask,
)

# Knowledge / RAG
from backend.models.knowledge import FileUpload, FileChunk, AttachmentContextModel

# Session
from backend.models.session import SessionTrigger, SessionTurn, TriggerType, TurnAction

# Organization
from backend.models.organization_run import OrganizationRun
from backend.models.organization_state import OrganizationState
from backend.models.organization_capability import OrganizationCapability

# Helpers
from backend.models._helpers import gen_uuid, utcnow

__all__ = [
    # system
    "User", "Workspace", "WorkspaceMember", "APIKey",
    # chat
    "Channel", "Teammate", "Message", "TeammateTemplate",
    # task status
    "TaskStatus", "TaskStepStatus", "ApprovalStatus", "RiskLevel",
    "PlanReviewStatus", "PlanStatus", "PolicyEffect",
    "ExecutionOutcome", "ExecutionResultStatus",
    "PlanMatchSeverity", "FailureCategory", "TaskRunStatus",
    # task models
    "TaskModel", "TaskStepModel", "TaskExecutionModel",
    "TaskApprovalModel", "TaskPolicyModel",
    "TaskPlanModel", "TaskPlanReviewModel",
    "PolicyRuleModel", "PolicyDecisionModel",
    "ExecutionRecordModel", "ExecutionEventModel",
    "ExecutionResultModel", "EvaluationRecordModel",
    "ArtifactModel", "DAGDefinitionModel", "DAGNodeModel",
    "AutomationRuleModel", "AutomationJobModel", "AutomationRunModel",
    "TaskRunModel", "BoardTask",
    # knowledge
    "FileUpload", "FileChunk", "AttachmentContextModel",
    # session
    "SessionTrigger", "SessionTurn", "TriggerType", "TurnAction",
    # organization
    "OrganizationRun", "OrganizationState", "OrganizationCapability",
    # helpers
    "gen_uuid", "utcnow",
]
