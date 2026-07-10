"""Task Execution Layer (v2.5) + Planner Core (v2.6) — service package."""

from backend.services.task.task_state import TaskStateManager
from backend.services.task.task_context import TaskContextBuilder
from backend.services.task.task_result import TaskResultHandler
from backend.services.task.task_executor import TaskExecutor

# v2.6 Planner Core
from backend.services.task.task_planner_schema import TaskPlan, TaskStepProposal
from backend.services.task.task_planner_parser import (
    parse_plan,
    PlannerParseError,
    PlannerJSONError,
    PlannerSchemaError,
    PlannerEmptyPlanError,
    PlannerOrderError,
    PlannerDependencyError,
)
from backend.services.task.task_planner_driver import generate_plan, validate_plan, PlanningError
from backend.services.task.task_planner_context import (
    PlannerContextBuilder,
    PlannerContext,
    build_planner_context,
    MAX_CONTEXT_TOKENS,
)
from backend.services.task.task_plan_service import TaskPlanService, NoActivePlanError, \
    PlanConversionError, EmptyPlanError, PolicyBlockedError

# v2.7 Phase A: ExecutionResult Foundation
from backend.services.task.task_execution_result import ExecutionResultService

# v2.7 Phase B: Execution Evaluation
from backend.services.task.evaluation import (
    ExecutionEvaluator,
    EvaluationResult,
    RuleBasedEvaluator,
)

__all__ = [
    "TaskStateManager",
    "TaskContextBuilder",
    "TaskResultHandler",
    "TaskExecutor",
    # v2.6 Planner Core
    "TaskPlan",
    "TaskStepProposal",
    "parse_plan",
    "PlannerParseError",
    "PlannerJSONError",
    "PlannerSchemaError",
    "PlannerEmptyPlanError",
    "PlannerOrderError",
    "PlannerDependencyError",
    "generate_plan",
    "validate_plan",
    "PlanningError",
    # v2.6 Phase B Planner Context
    "PlannerContextBuilder",
    "PlannerContext",
    "build_planner_context",
    "MAX_CONTEXT_TOKENS",
    # v2.6 Phase C Planner-Task Integration
    "TaskPlanService",
    "NoActivePlanError",
    "PlanConversionError",
    "EmptyPlanError",
    "PolicyBlockedError",
    # v2.7 Phase A ExecutionResult
    "ExecutionResultService",
    # v2.7 Phase B Execution Evaluation
    "ExecutionEvaluator",
    "EvaluationResult",
    "RuleBasedEvaluator",
]