"""
test_execution_evaluation.py — Phase B: Rule-Based Evaluation Tests

Coverage:
  1. Empty output → scores = 0.0
  2. Normal output with expected → completeness via keyword overlap
  3. Normal output without expected → length proxy
  4. Coherence calculation — well-structured output
  5. Coherence calculation — poor structure
  6. Overall quality — weighted combination
  7. Evaluate result → status becomes EVALUATED
  8. Evaluate result — skipped outcome skips evaluation
  9. Evaluate result — failed outcome skips evaluation
  10. Accuracy remains None
  11. Re-evaluate (EVALUATED → EVALUATED, scores update)
"""

import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskStatus, TaskStepStatus,
    ExecutionResultModel,
    ExecutionOutcome, ExecutionResultStatus,
)
from backend.services.task.task_execution_result import ExecutionResultService
from backend.services.task.evaluation import (
    RuleBasedEvaluator,
    ExecutionEvaluator,
    EvaluationResult,
)

pytestmark = pytest.mark.asyncio

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def make_task(**kwargs) -> TaskModel:
    defaults = dict(
        id="task-eval",
        title="Eval Test Task",
        description="Test task for evaluation",
        status=TaskStatus.EXECUTING,
        priority=2,
        intent="test",
        created_by="test",
    )
    defaults.update(kwargs)
    task = TaskModel(**defaults)
    task.steps = []
    return task


def make_step(task_id="task-eval", order=1, **kwargs) -> TaskStepModel:
    defaults = dict(
        id=f"step-eval-{order:03d}",
        task_id=task_id,
        order=order,
        objective=f"Step {order} objective",
        status=TaskStepStatus.PENDING,
    )
    defaults.update(kwargs)
    return TaskStepModel(**defaults)


def make_execution(step_id="step-eval-001", attempt=1, **kwargs) -> TaskExecutionModel:
    defaults = dict(
        id=f"exec-eval-{step_id}-{attempt}",
        task_step_id=step_id,
        attempt=attempt,
        maeos_task_id="maeos-eval-task",
    )
    defaults.update(kwargs)
    return TaskExecutionModel(**defaults)


svc = ExecutionResultService()
evaluator = RuleBasedEvaluator()


# ═══════════════════════════════════════════════════════════════
# 1. Empty output
# ═══════════════════════════════════════════════════════════════


async def test_empty_output_scores_zero():
    """Empty output should produce 0.0 for all scores."""
    result = await evaluator.evaluate(actual_output="")
    assert result.completeness == 0.0
    assert result.coherence == 0.0
    assert result.overall_quality == 0.0
    assert result.accuracy is None


async def test_whitespace_output_scores_zero():
    """Whitespace-only output should produce 0.0."""
    result = await evaluator.evaluate(actual_output="   \n  \n  ")
    assert result.completeness == 0.0
    assert result.coherence == 0.0
    assert result.overall_quality == 0.0


# ═══════════════════════════════════════════════════════════════
# 2. Completeness with expected output
# ═══════════════════════════════════════════════════════════════


async def test_completeness_with_expected():
    """Completeness should reflect keyword overlap with expected_output."""
    expected = (
        "The system architecture includes a database layer, "
        "an API gateway, a message queue, and a caching service."
    )
    actual = (
        "Our system uses a PostgreSQL database layer. "
        "The API gateway handles routing. "
        "We have a Redis caching service."
    )
    result = await evaluator.evaluate(
        actual_output=actual,
        expected_output=expected,
    )
    # Most keywords from expected should appear in actual
    assert result.completeness > 0.5
    assert result.completeness <= 1.0


async def test_completeness_no_overlap():
    """Completeness should be low when output has no keywords from expected."""
    expected = (
        "Database migration scripts for PostgreSQL schema updates"
    )
    actual = (
        "The weather today is sunny with a high of 25 degrees."
    )
    result = await evaluator.evaluate(
        actual_output=actual,
        expected_output=expected,
    )
    assert result.completeness < 0.3


# ═══════════════════════════════════════════════════════════════
# 3. Completeness without expected (length proxy)
# ═══════════════════════════════════════════════════════════════


async def test_completeness_length_proxy_short():
    """Short output without expected gets low completeness."""
    result = await evaluator.evaluate(actual_output="short output")
    assert result.completeness == 0.2  # < 50 chars


async def test_completeness_length_proxy_long():
    """Long well-structured output without expected gets higher completeness."""
    text = "Introduction\n\n" * 50  # 700 chars, has paragraphs, ≥ 500 chars
    result = await evaluator.evaluate(actual_output=text)
    assert result.completeness >= 0.7


# ═══════════════════════════════════════════════════════════════
# 4. Coherence — well-structured
# ═══════════════════════════════════════════════════════════════


async def test_coherence_well_structured():
    """Well-structured text with paragraphs and connectors gets high coherence."""
    text = (
        "First, we need to set up the database schema. "
        "Therefore, we should create migration scripts. "
        "Furthermore, we must validate all constraints. "
        "Finally, we can deploy the changes to production.\n\n"
        "The second phase involves testing. "
        "Specifically, we need to run integration tests. "
        "As a result, we can identify regressions early."
    )
    result = await evaluator.evaluate(actual_output=text)
    assert result.coherence >= 0.6
    assert result.coherence <= 1.0


# ═══════════════════════════════════════════════════════════════
# 5. Coherence — poor structure
# ═══════════════════════════════════════════════════════════════


async def test_coherence_poor_structure():
    """Single unformatted sentence without connectors gets low coherence."""
    text = "just one unformatted runon sentence without any structure or punctuation"
    result = await evaluator.evaluate(actual_output=text)
    assert result.coherence < 0.4


# ═══════════════════════════════════════════════════════════════
# 6. Overall quality — weighted combination
# ═══════════════════════════════════════════════════════════════


async def test_overall_quality_weighted():
    """Overall quality should be completeness*0.6 + coherence*0.4."""
    expected = "database API caching"
    actual = (
        "We use a database for storage. "
        "The API layer handles requests. "
        "Caching improves performance."
    )
    result = await evaluator.evaluate(
        actual_output=actual,
        expected_output=expected,
    )
    expected_overall = round(
        result.completeness * 0.6 + result.coherence * 0.4, 4
    )
    assert result.overall_quality == expected_overall


# ═══════════════════════════════════════════════════════════════
# 7. evaluate_result → status = EVALUATED
# ═══════════════════════════════════════════════════════════════


async def test_evaluate_result_updates_status(db_session: AsyncSession):
    """evaluate_result() should set status to EVALUATED and update scores."""
    task = make_task()
    db_session.add(task)
    step = make_step(task_id=task.id)
    db_session.add(step)
    exec_ = make_execution(step_id=step.id)
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
    )
    assert result.status == ExecutionResultStatus.CREATED

    updated = await svc.evaluate_result(
        db_session,
        result,
        actual_output="This is a well-structured output. It has multiple sentences. "
                       "Furthermore, it contains logical connectors. "
                       "Therefore, it should score reasonably well.\n\n"
                       "The second paragraph provides additional structure. "
                       "This improves coherence further.",
        expected_output="structured output sentences logical connectors coherence",
    )

    assert updated.status == ExecutionResultStatus.EVALUATED
    assert updated.completeness > 0.0
    assert updated.coherence > 0.0
    assert updated.overall_quality > 0.0
    assert updated.evaluator == "rule"
    assert updated.evaluation_confidence == 1.0


# ═══════════════════════════════════════════════════════════════
# 8. Skipped outcome → no evaluation
# ═══════════════════════════════════════════════════════════════


async def test_evaluate_skipped_outcome(db_session: AsyncSession):
    """SKIPPED outcome should skip evaluation, scores remain 0.0."""
    task = make_task(id="task-skip")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-skip")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-skip")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
        outcome=ExecutionOutcome.SKIPPED,
    )

    updated = await svc.evaluate_result(
        db_session,
        result,
        actual_output="should not matter",
    )

    assert updated.status == ExecutionResultStatus.EVALUATED
    assert updated.completeness == 0.0
    assert updated.coherence == 0.0
    assert updated.overall_quality == 0.0


# ═══════════════════════════════════════════════════════════════
# 9. Failed outcome → no evaluation
# ═══════════════════════════════════════════════════════════════


async def test_evaluate_failed_outcome(db_session: AsyncSession):
    """FAILED outcome should skip evaluation, scores remain 0.0."""
    task = make_task(id="task-fail-eval")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-fail-eval")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-fail-eval")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
        outcome=ExecutionOutcome.FAILURE,
    )

    updated = await svc.evaluate_result(
        db_session,
        result,
        actual_output="should not matter",
    )

    assert updated.status == ExecutionResultStatus.EVALUATED
    assert updated.completeness == 0.0
    assert updated.coherence == 0.0
    assert updated.overall_quality == 0.0


# ═══════════════════════════════════════════════════════════════
# 10. Accuracy remains None
# ═══════════════════════════════════════════════════════════════


async def test_accuracy_is_none():
    """RuleBasedEvaluator should always return accuracy=None."""
    result = await evaluator.evaluate(
        actual_output="Some output with reasonable content.",
        expected_output="output content",
    )
    assert result.accuracy is None


# ═══════════════════════════════════════════════════════════════
# 11. Re-evaluate updates scores
# ═══════════════════════════════════════════════════════════════


async def test_reevaluate_updates_scores(db_session: AsyncSession):
    """Calling evaluate_result on an EVALUATED result should update scores."""
    task = make_task(id="task-reeval")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-reeval")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-reeval")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
    )

    # First eval with short output
    updated = await svc.evaluate_result(
        db_session, result,
        actual_output="short",
    )
    first_completeness = updated.completeness

    # Re-evaluate with better output
    better_output = (
        "This is a comprehensive and well-structured output. "
        "First, it covers all the key points. "
        "Second, it provides detailed explanations. "
        "Furthermore, it includes examples.\n\n"
        "The second section delves deeper into implementation. "
        "Specifically, we discuss architecture decisions. "
        "As a result, readers gain a thorough understanding."
    )
    updated = await svc.evaluate_result(
        db_session, updated,
        actual_output=better_output,
        expected_output="comprehensive well-structured key points architecture",
    )

    assert updated.completeness > first_completeness
    assert updated.coherence > 0.5
    assert updated.overall_quality > 0.5
    assert updated.status == ExecutionResultStatus.EVALUATED


# ═══════════════════════════════════════════════════════════════
# 12. Interface compliance
# ═══════════════════════════════════════════════════════════════


async def test_evaluator_implements_interface():
    """RuleBasedEvaluator should satisfy the ExecutionEvaluator interface."""
    assert isinstance(evaluator, ExecutionEvaluator)
    assert hasattr(evaluator, "evaluate")

    # Should be callable and return EvaluationResult
    result = await evaluator.evaluate(actual_output="test")
    assert isinstance(result, EvaluationResult)
