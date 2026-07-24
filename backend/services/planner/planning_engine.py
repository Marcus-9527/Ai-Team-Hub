"""PlanningEngine — orchestrates the LLM planning pipeline.

Flow:
  User goal → TaskAnalyzer → LLM call (via MAEOS/reuse generate_plan)
  → DAGBuilder → DAGValidator → DAGDefinition

The engine does NOT execute the DAG; it produces a validated DAGDefinition
for downstream approval/policy → execution.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.services.dag.core import DAGDefinition
from backend.services.planner.task_analyzer import TaskAnalyzer, TaskAnalysis
from backend.services.dag.builder import DAGBuilder
from backend.services.planner.dag_validator import DAGValidator, ValidationResult
from backend.services.task.task_planner_schema import TaskPlan

logger = logging.getLogger("planner.engine")


class PlanningError(Exception):
    """Raised when planning fails (analysis, LLM, build, or validation)."""
    pass


class PlanningEngine:
    """Orchestrate natural language → validated DAGDefinition."""

    def __init__(self, task_analyzer: TaskAnalyzer | None = None,
                 dag_builder: DAGBuilder | None = None,
                 dag_validator: DAGValidator | None = None):
        self._analyzer = task_analyzer or TaskAnalyzer()
        self._builder = dag_builder or DAGBuilder()
        self._validator = dag_validator or DAGValidator()
        # ponytail: no injectable LLM call; reuse existing generate_plan.
        # If planning needs a different LLM path, inject via plan() kwargs.
        self._plan_fn = None

    async def plan(self, goal: str,
                   context: dict | None = None,
                   task_id: str = "",
                   api_key: str = "",
                   provider: str = "openrouter") -> DAGDefinition:
        """Convert a natural language goal into a validated DAGDefinition.

        Args:
            goal: User's goal description.
            context: Optional context dict (e.g. from PlannerContextBuilder).
            task_id: Optional task ID for correlation.

        Returns:
            A validated DAGDefinition (not executed).

        Raises:
            PlanningError: If any stage fails.
        """
        # 1. Analyze
        analysis = self._analyzer.analyze(goal)
        logger.info("[PLAN] analysis: type=%s complexity=%s",
                     analysis.task_type, analysis.complexity)

        # 2. Call LLM → get TaskPlan
        plan = await self._call_llm(goal, context or {}, task_id, api_key, provider)

        # 3. Build DAG
        dag = self._builder.build(plan)
        logger.info("[PLAN] DAG built: %d nodes", len(dag.nodes))

        # 4. Validate
        result = self._validator.validate(dag)
        if not result.valid:
            raise PlanningError(
                f"DAG validation failed ({len(result.errors)} errors): "
                f"{'; '.join(result.errors)}"
            )

        logger.info("[PLAN] DAG validated OK: %s", dag.id)
        return dag

    async def _call_llm(self, goal: str, context: dict,
                        task_id: str, api_key: str = "", provider: str = "openrouter") -> TaskPlan:
        """Call the LLM to produce a TaskPlan.

        Default implementation uses the existing generate_plan (MAEOS).
        Subclasses or callers can inject a different plan function.
        """
        if self._plan_fn:
            return await self._plan_fn(goal, context, task_id)

        from backend.services.task.task_planner_driver import (
            generate_plan,
            PlanningError as DriverPlanningError,
        )
        from backend.routes.maeos import get_runtime
        runtime = get_runtime()
        try:
            plan = await generate_plan(
                maeos=runtime, goal=goal,
                task_id=task_id, context=context or {},
                api_key=api_key, provider=provider,
            )
        except DriverPlanningError as e:
            # driver defines its own PlanningError; re-raise as this module's
            # class so callers' except (PlanningError, ...) actually catches it.
            raise PlanningError(str(e)) from e
        return plan

    def set_plan_fn(self, fn):
        """Inject a plan function for testing (takes goal, context, task_id)."""
        self._plan_fn = fn
