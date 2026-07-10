"""
task_execution_result.py — ExecutionResult Service (Phase A + Phase B)

Phase A:
  - create_result() — record a new execution result
  - get_result() — retrieve a single result by id
  - list_results() — query results by step, execution, or outcome

Phase B:
  - evaluate_result() — run quality evaluation and update result status

NOT in Phase A/B (deferred to Phase C–D):
  - Plan comparison
  - Failure classification
  - Replan triggering
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    ExecutionResultModel,
    ExecutionOutcome,
    ExecutionResultStatus,
    gen_uuid,
    utcnow,
)
from backend.services.task.evaluation import (
    RuleBasedEvaluator,
    EvaluationResult,
)

logger = logging.getLogger("task.execution_result")


class ExecutionResultService:
    """
    Phase A+B: ExecutionResult CRUD + evaluation service.

    Provides basic persistence operations and quality evaluation
    for ExecutionResultModel.
    """

    def __init__(self):
        self._evaluator = RuleBasedEvaluator()

    # ── Create ──

    async def create_result(
        self,
        db: AsyncSession,
        *,
        task_step_id: str,
        task_execution_id: str,
        outcome: str = ExecutionOutcome.SUCCESS,
        completeness: float = 0.0,
        coherence: float = 0.0,
        accuracy: float = 0.0,
        overall_quality: float = 0.0,
        plan_matched: str = "NONE",
        plan_deviation_detail: str = "",
        failure_category: str = "",
        failure_subcategory: str = "",
        is_recoverable: str = "1",
        evaluator: str = "llm",
        evaluation_confidence: float = 0.0,
        status: str = ExecutionResultStatus.CREATED,
        replan_triggered: str = "0",
        replan_scope: str = "",
    ) -> ExecutionResultModel:
        """Create a new ExecutionResult record."""
        result = ExecutionResultModel(
            id=gen_uuid(),
            task_step_id=task_step_id,
            task_execution_id=task_execution_id,
            outcome=outcome,
            completeness=completeness,
            coherence=coherence,
            accuracy=accuracy,
            overall_quality=overall_quality,
            plan_matched=plan_matched,
            plan_deviation_detail=plan_deviation_detail,
            failure_category=failure_category,
            failure_subcategory=failure_subcategory,
            is_recoverable=is_recoverable,
            evaluator=evaluator,
            evaluation_confidence=evaluation_confidence,
            status=status,
            replan_triggered=replan_triggered,
            replan_scope=replan_scope,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(result)
        await db.flush()
        await db.refresh(result)
        logger.debug(
            f"[RESULT] created {result.id} for step {task_step_id} "
            f"(outcome={outcome})"
        )
        return result

    # ── Evaluate ──

    async def evaluate_result(
        self,
        db: AsyncSession,
        result: ExecutionResultModel,
        *,
        actual_output: str,
        expected_output: str = "",
        objective: str = "",
    ) -> ExecutionResultModel:
        """Run quality evaluation on an ExecutionResult and update its scores.

        Flow:
          1. Run RuleBasedEvaluator on the output
          2. Update result with completeness, coherence, overall_quality
          3. Set status = EVALUATED

        Only evaluates results with status == CREATED or EVALUATED (re-eval).
        SKIPPED or FAILED outcomes are evaluation-skipped (scores remain 0.0).
        """
        if result.status not in (ExecutionResultStatus.CREATED, ExecutionResultStatus.EVALUATED):
            logger.warning(
                f"[RESULT] skip evaluation for {result.id}: "
                f"status={result.status}"
            )
            return result

        if result.outcome in (ExecutionOutcome.SKIPPED, ExecutionOutcome.FAILURE):
            logger.debug(
                f"[RESULT] skip evaluation for {result.id}: "
                f"outcome={result.outcome} (scores remain 0.0)"
            )
            result = await self.update_result(
                db, result,
                status=ExecutionResultStatus.EVALUATED,
                evaluator="rule",
            )
            return result

        # Run rule-based evaluation
        eval_result: EvaluationResult = await self._evaluator.evaluate(
            actual_output=actual_output,
            expected_output=expected_output,
            objective=objective,
        )

        # Persist scores and advance status
        result = await self.update_result(
            db, result,
            completeness=eval_result.completeness,
            coherence=eval_result.coherence,
            accuracy=eval_result.accuracy,  # None → no change
            overall_quality=eval_result.overall_quality,
            evaluator=eval_result.evaluator,
            evaluation_confidence=eval_result.confidence,
            status=ExecutionResultStatus.EVALUATED,
        )

        logger.info(
            f"[RESULT] evaluated {result.id}: "
            f"completeness={eval_result.completeness:.3f}, "
            f"coherence={eval_result.coherence:.3f}, "
            f"quality={eval_result.overall_quality:.3f}"
        )
        return result

    # ── Read ──

    async def get_result(
        self,
        db: AsyncSession,
        result_id: str,
    ) -> Optional[ExecutionResultModel]:
        """Get a single ExecutionResult by ID."""
        result = await db.execute(
            select(ExecutionResultModel).where(ExecutionResultModel.id == result_id)
        )
        return result.scalar_one_or_none()

    async def list_results(
        self,
        db: AsyncSession,
        *,
        task_step_id: Optional[str] = None,
        task_execution_id: Optional[str] = None,
        outcome: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionResultModel]:
        """List ExecutionResults with optional filters, ordered by created_at desc."""
        query = select(ExecutionResultModel)

        if task_step_id:
            query = query.where(ExecutionResultModel.task_step_id == task_step_id)
        if task_execution_id:
            query = query.where(
                ExecutionResultModel.task_execution_id == task_execution_id
            )
        if outcome:
            query = query.where(ExecutionResultModel.outcome == outcome)
        if status:
            query = query.where(ExecutionResultModel.status == status)

        query = query.order_by(desc(ExecutionResultModel.created_at))
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    # ── Update ──

    async def update_result(
        self,
        db: AsyncSession,
        result: ExecutionResultModel,
        *,
        outcome: Optional[str] = None,
        completeness: Optional[float] = None,
        coherence: Optional[float] = None,
        accuracy: Optional[float] = None,
        overall_quality: Optional[float] = None,
        plan_matched: Optional[str] = None,
        plan_deviation_detail: Optional[str] = None,
        failure_category: Optional[str] = None,
        failure_subcategory: Optional[str] = None,
        is_recoverable: Optional[str] = None,
        evaluator: Optional[str] = None,
        evaluation_confidence: Optional[float] = None,
        status: Optional[str] = None,
        replan_triggered: Optional[str] = None,
        replan_scope: Optional[str] = None,
    ) -> ExecutionResultModel:
        """Update an existing ExecutionResult record.

        Only provided fields are updated; None fields are left unchanged.
        """
        if outcome is not None:
            result.outcome = outcome
        if completeness is not None:
            result.completeness = completeness
        if coherence is not None:
            result.coherence = coherence
        if accuracy is not None:
            result.accuracy = accuracy
        if overall_quality is not None:
            result.overall_quality = overall_quality
        if plan_matched is not None:
            result.plan_matched = plan_matched
        if plan_deviation_detail is not None:
            result.plan_deviation_detail = plan_deviation_detail
        if failure_category is not None:
            result.failure_category = failure_category
        if failure_subcategory is not None:
            result.failure_subcategory = failure_subcategory
        if is_recoverable is not None:
            result.is_recoverable = is_recoverable
        if evaluator is not None:
            result.evaluator = evaluator
        if evaluation_confidence is not None:
            result.evaluation_confidence = evaluation_confidence
        if status is not None:
            result.status = status
        if replan_triggered is not None:
            result.replan_triggered = replan_triggered
        if replan_scope is not None:
            result.replan_scope = replan_scope

        result.updated_at = utcnow()
        await db.flush()
        await db.refresh(result)
        logger.debug(f"[RESULT] updated {result.id}")
        return result

    # ── Count ──

    async def count_results(
        self,
        db: AsyncSession,
        *,
        task_step_id: Optional[str] = None,
        outcome: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count ExecutionResults with optional filters."""
        query = select(func.count(ExecutionResultModel.id))

        if task_step_id:
            query = query.where(ExecutionResultModel.task_step_id == task_step_id)
        if outcome:
            query = query.where(ExecutionResultModel.outcome == outcome)
        if status:
            query = query.where(ExecutionResultModel.status == status)

        result = await db.execute(query)
        return result.scalar() or 0
