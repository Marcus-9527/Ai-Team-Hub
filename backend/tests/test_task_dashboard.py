"""
test_task_dashboard.py — V3.0 Phase B: Task Intelligence Dashboard Tests

Covers:
  - list_executions_by_task() — cross-step execution queries
  - list_results_by_task() — cross-step result queries with join data
  - get_task_analytics() — aggregation: count, success rate, avg quality, tokens, cost
"""

import pytest
from datetime import datetime, timezone

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskExecutionModel,
    ExecutionResultModel,
    ExecutionOutcome,
    ExecutionResultStatus,
    TaskStatus,
    TaskStepStatus,
    gen_uuid,
    utcnow,
)
from backend.services.task.task_state import TaskStateManager


@pytest.fixture
def state_mgr():
    return TaskStateManager()


async def _create_task_with_step_and_execution(db, state_mgr, title="dashboard-test"):
    """Helper: create a task with one step and one execution, return all IDs."""
    task = await state_mgr.create_task(
        db, title=title, description="dashboard test", created_by="test"
    )
    step = await state_mgr.create_step(
        db, task_id=task.id, order=1, objective="test step"
    )
    execution = await state_mgr.create_execution(
        db,
        task_step_id=step.id,
        attempt=1,
        teammate_id="engineer",
        model_name="test-model",
        start_time=datetime.now(timezone.utc),
    )
    # Update execution with performance data
    await state_mgr.update_execution(
        db,
        execution,
        end_time=datetime.now(timezone.utc),
        execution_time_ms=1500,
        input_tokens=500,
        output_tokens=300,
        total_tokens=800,
        estimated_cost=500,
    )
    await db.commit()
    await db.refresh(task)
    await db.refresh(step)
    await db.refresh(execution)
    return task, step, execution


# ═══════════════════════════════════════════════════════════════
# 1. list_executions_by_task()
# ═══════════════════════════════════════════════════════════════


class TestListExecutionsByTask:
    """list_executions_by_task — cross-step execution query."""

    pytestmark = pytest.mark.asyncio

    async def test_returns_all_executions_for_task(self, db_session, state_mgr):
        """Creates task with step+execution, verifies the query returns it."""
        task, step, execution = await _create_task_with_step_and_execution(db_session, state_mgr)
        results = await state_mgr.list_executions_by_task(db_session, task.id)
        assert len(results) == 1
        assert results[0]["id"] == execution.id
        assert results[0]["task_step_id"] == step.id
        assert results[0]["step_order"] == 1
        assert results[0]["step_objective"] == "test step"
        assert results[0]["teammate_id"] == "engineer"
        assert results[0]["model_name"] == "test-model"
        assert results[0]["execution_time_ms"] == 1500
        assert results[0]["total_tokens"] == 800
        assert results[0]["estimated_cost"] == 500

    async def test_returns_empty_for_task_without_executions(self, db_session, state_mgr):
        """Task with no executions returns empty list."""
        task = await state_mgr.create_task(db_session, title="no-exec", created_by="test")
        await db_session.commit()
        results = await state_mgr.list_executions_by_task(db_session, task.id)
        assert results == []

    async def test_returns_executions_across_multiple_steps(self, db_session, state_mgr):
        """Creates 2 steps with 2 executions, verifies both are returned."""
        task = await state_mgr.create_task(db_session, title="multi-step", created_by="test")
        await db_session.commit()

        step1 = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="step1")
        step2 = await state_mgr.create_step(db_session, task_id=task.id, order=2, objective="step2")

        ex1 = await state_mgr.create_execution(db_session, task_step_id=step1.id, attempt=1)
        ex2 = await state_mgr.create_execution(db_session, task_step_id=step2.id, attempt=1)
        await db_session.commit()

        results = await state_mgr.list_executions_by_task(db_session, task.id)
        assert len(results) == 2
        ids = [r["id"] for r in results]
        assert ex1.id in ids
        assert ex2.id in ids

    async def test_does_not_include_other_tasks_executions(self, db_session, state_mgr):
        """Executions from other tasks are not included."""
        task1, _, _ = await _create_task_with_step_and_execution(db_session, state_mgr, "task-a")
        # Create a separate task with its own execution
        await _create_task_with_step_and_execution(db_session, state_mgr, "task-b")

        results = await state_mgr.list_executions_by_task(db_session, task1.id)
        assert len(results) == 1
        assert results[0]["step_order"] == 1  # Only task-a's execution


# ═══════════════════════════════════════════════════════════════
# 2. list_results_by_task()
# ═══════════════════════════════════════════════════════════════


class TestListResultsByTask:
    """list_results_by_task — cross-step result query."""

    pytestmark = pytest.mark.asyncio

    async def test_returns_results_with_join_data(self, db_session, state_mgr):
        """Creates result, verifies step + execution data in output."""
        task, step, execution = await _create_task_with_step_and_execution(db_session, state_mgr)

        # Create execution result
        result = ExecutionResultModel(
            id=gen_uuid(),
            task_step_id=step.id,
            task_execution_id=execution.id,
            outcome=ExecutionOutcome.SUCCESS,
            completeness=0.85,
            coherence=0.75,
            accuracy=0.0,
            overall_quality=0.81,
            plan_matched="NONE",
            evaluator="rule",
            status=ExecutionResultStatus.EVALUATED,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(result)
        await db_session.commit()
        await db_session.refresh(result)

        results = await state_mgr.list_results_by_task(db_session, task.id)
        assert len(results) == 1
        assert results[0]["id"] == result.id
        assert results[0]["step_order"] == 1
        assert results[0]["step_objective"] == "test step"
        assert results[0]["outcome"] == ExecutionOutcome.SUCCESS
        assert results[0]["completeness"] == 0.85
        assert results[0]["coherence"] == 0.75
        assert results[0]["overall_quality"] == 0.81
        assert results[0]["evaluator"] == "rule"
        assert results[0]["total_tokens"] == 800
        assert results[0]["estimated_cost"] == 500

    async def test_returns_multiple_results_per_task(self, db_session, state_mgr):
        """Multiple results across steps are all returned."""
        task = await state_mgr.create_task(db_session, title="multi-result", created_by="test")
        await db_session.commit()

        step1 = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="r1")
        step2 = await state_mgr.create_step(db_session, task_id=task.id, order=2, objective="r2")

        ex1 = await state_mgr.create_execution(db_session, task_step_id=step1.id, attempt=1)
        ex2 = await state_mgr.create_execution(db_session, task_step_id=step2.id, attempt=1)
        await db_session.commit()

        for step, ex in [(step1, ex1), (step2, ex2)]:
            r = ExecutionResultModel(
                id=gen_uuid(),
                task_step_id=step.id,
                task_execution_id=ex.id,
                outcome=ExecutionOutcome.SUCCESS,
                completeness=0.9,
                coherence=0.8,
                accuracy=0.0,
                overall_quality=0.86,
                plan_matched="NONE",
                evaluator="rule",
                status=ExecutionResultStatus.EVALUATED,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db_session.add(r)
        await db_session.commit()

        results = await state_mgr.list_results_by_task(db_session, task.id)
        assert len(results) == 2

    async def test_no_results_returns_empty(self, db_session, state_mgr):
        """No results returns empty list."""
        task, _, _ = await _create_task_with_step_and_execution(db_session, state_mgr)
        results = await state_mgr.list_results_by_task(db_session, task.id)
        assert results == []


# ═══════════════════════════════════════════════════════════════
# 3. get_task_analytics()
# ═══════════════════════════════════════════════════════════════


class TestGetTaskAnalytics:
    """get_task_analytics — aggregation queries."""

    pytestmark = pytest.mark.asyncio

    async def test_returns_zero_analytics_for_no_executions(self, db_session, state_mgr):
        """Task with no executions returns zeroed analytics."""
        task = await state_mgr.create_task(db_session, title="empty-analytics", created_by="test")
        await db_session.commit()
        analytics = await state_mgr.get_task_analytics(db_session, task.id)
        assert analytics["execution_count"] == 0
        assert analytics["success_rate"] == 0.0
        assert analytics["avg_quality"] == 0.0
        assert analytics["total_tokens"] == 0
        assert analytics["total_cost_micro"] == 0

    async def test_counts_executions_correctly(self, db_session, state_mgr):
        """Task with 2 executions returns count=2."""
        task = await state_mgr.create_task(db_session, title="count-test", created_by="test")
        await db_session.commit()

        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="s1")
        await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)
        await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=2)
        await db_session.commit()

        analytics = await state_mgr.get_task_analytics(db_session, task.id)
        assert analytics["execution_count"] == 2

    async def test_calculates_success_rate(self, db_session, state_mgr):
        """1 success, 1 failure → 0.5 success rate."""
        task = await state_mgr.create_task(db_session, title="success-rate", created_by="test")
        await db_session.commit()

        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="s1")

        # Success: execution with error=""
        ex1 = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)
        await state_mgr.update_execution(db_session, ex1, total_tokens=100, estimated_cost=100)

        # Failure: execution with error message
        ex2 = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=2)
        await state_mgr.update_execution(db_session, ex2, error="something failed", total_tokens=50, estimated_cost=50)

        await db_session.commit()

        analytics = await state_mgr.get_task_analytics(db_session, task.id)
        assert analytics["execution_count"] == 2
        assert analytics["success_rate"] == 0.5

    async def test_summarizes_tokens_and_cost(self, db_session, state_mgr):
        """Total tokens and cost are aggregated correctly."""
        task = await state_mgr.create_task(db_session, title="sum-test", created_by="test")
        await db_session.commit()

        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="s1")

        for attempt in range(1, 4):
            ex = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=attempt)
            await state_mgr.update_execution(db_session, ex, total_tokens=100, estimated_cost=50)

        await db_session.commit()

        analytics = await state_mgr.get_task_analytics(db_session, task.id)
        assert analytics["execution_count"] == 3
        assert analytics["total_tokens"] == 300
        assert analytics["total_cost_micro"] == 150  # 3 × 50

    async def test_calculates_average_quality_with_results(self, db_session, state_mgr):
        """Avg quality from execution results is computed correctly."""
        task = await state_mgr.create_task(db_session, title="avg-quality", created_by="test")
        await db_session.commit()

        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="s1")
        ex = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)
        await db_session.commit()

        for quality in [0.8, 1.0]:
            r = ExecutionResultModel(
                id=gen_uuid(),
                task_step_id=step.id,
                task_execution_id=ex.id,
                outcome=ExecutionOutcome.SUCCESS,
                completeness=quality,
                coherence=quality,
                accuracy=0.0,
                overall_quality=quality,
                plan_matched="NONE",
                evaluator="rule",
                status=ExecutionResultStatus.EVALUATED,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db_session.add(r)
        await db_session.commit()

        analytics = await state_mgr.get_task_analytics(db_session, task.id)
        assert analytics["avg_quality"] == pytest.approx(0.9, abs=0.01)

    async def test_does_not_count_other_tasks(self, db_session, state_mgr):
        """Analytics for task A does not include task B data."""
        await _create_task_with_step_and_execution(db_session, state_mgr, "task-a")
        await _create_task_with_step_and_execution(db_session, state_mgr, "task-b")

        # Get analytics for the second task by listing tasks and picking it
        from sqlalchemy import select
        result = await db_session.execute(
            select(TaskModel).where(TaskModel.title == "task-b")
        )
        task_b = result.scalar_one()

        analytics = await state_mgr.get_task_analytics(db_session, task_b.id)
        assert analytics["execution_count"] == 1

    async def test_success_rate_all_fail(self, db_session, state_mgr):
        """All failed executions → 0 success rate."""
        task = await state_mgr.create_task(db_session, title="all-fail", created_by="test")
        await db_session.commit()
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="s1")

        for i in range(3):
            ex = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=i+1)
            await state_mgr.update_execution(db_session, ex, error=f"fail-{i}")
        await db_session.commit()

        analytics = await state_mgr.get_task_analytics(db_session, task.id)
        assert analytics["execution_count"] == 3
        assert analytics["success_rate"] == 0.0

    async def test_avg_quality_no_results(self, db_session, state_mgr):
        """Executions with no results → avg_quality = 0.0."""
        task = await state_mgr.create_task(db_session, title="no-qual", created_by="test")
        await db_session.commit()
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="s1")
        ex = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)
        await state_mgr.update_execution(db_session, ex, total_tokens=100, estimated_cost=50)
        await db_session.commit()

        analytics = await state_mgr.get_task_analytics(db_session, task.id)
        assert analytics["execution_count"] == 1
        assert analytics["avg_quality"] == 0.0
        assert analytics["total_tokens"] == 100

    async def test_results_ordered_by_created_at_desc(self, db_session, state_mgr):
        """list_results_by_task returns results ordered newest-first."""
        task = await state_mgr.create_task(db_session, title="order-test", created_by="test")
        await db_session.commit()
        step = await state_mgr.create_step(db_session, task_id=task.id, order=1, objective="s1")
        ex = await state_mgr.create_execution(db_session, task_step_id=step.id, attempt=1)
        await db_session.commit()

        from backend.models import utcnow
        results_added = []
        for i, quality in enumerate([0.5, 0.8, 1.0]):
            r = ExecutionResultModel(
                id=gen_uuid(),
                task_step_id=step.id,
                task_execution_id=ex.id,
                outcome=ExecutionOutcome.SUCCESS,
                completeness=quality,
                coherence=quality,
                accuracy=0.0,
                overall_quality=quality,
                plan_matched="NONE",
                evaluator="rule",
                status=ExecutionResultStatus.EVALUATED,
                created_at=utcnow(),  # same timestamp in fast sequence
                updated_at=utcnow(),
            )
            db_session.add(r)
            results_added.append(r)
        await db_session.commit()

        results = await state_mgr.list_results_by_task(db_session, task.id)
        assert len(results) == 3
        # Should be newest first
        qualities = [r["overall_quality"] for r in results]
        assert qualities == [1.0, 0.8, 0.5]
