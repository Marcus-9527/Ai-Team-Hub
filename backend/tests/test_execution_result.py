"""
test_execution_result.py — Phase A: ExecutionResult Model + Service Tests

Coverage:
  1. Create result — success outcome with default fields
  2. Create result — failure outcome with classification fields
  3. Get result — by ID, returns None for missing
  4. List results — by step_id
  5. List results — by execution_id
  6. List results — by outcome filter
  7. List results — by status filter
  8. Update result — partial field update
  9. Update result — status lifecycle
  10. Cascade delete — delete step cascades to execution_results
  11. Cascade delete — delete execution cascades to execution_results
  12. Count results — with and without filters
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

pytestmark = pytest.mark.asyncio

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def make_task(**kwargs) -> TaskModel:
    defaults = dict(
        id="task-001",
        title="Execution Result Test Task",
        description="Test task for execution result foundation",
        status=TaskStatus.EXECUTING,
        priority=2,
        intent="test",
        created_by="test",
    )
    defaults.update(kwargs)
    task = TaskModel(**defaults)
    task.steps = []
    return task


def make_step(task_id="task-001", order=1, **kwargs) -> TaskStepModel:
    defaults = dict(
        id=f"step-{order:03d}",
        task_id=task_id,
        order=order,
        objective=f"Step {order} objective",
        status=TaskStepStatus.PENDING,
    )
    defaults.update(kwargs)
    return TaskStepModel(**defaults)


def make_execution(step_id="step-001", attempt=1, **kwargs) -> TaskExecutionModel:
    defaults = dict(
        id=f"exec-{step_id}-{attempt}",
        task_step_id=step_id,
        attempt=attempt,
        maeos_task_id="maeos-task-001",
    )
    defaults.update(kwargs)
    return TaskExecutionModel(**defaults)


svc = ExecutionResultService()


# ═══════════════════════════════════════════════════════════════
# 1. Create result — success outcome
# ═══════════════════════════════════════════════════════════════


async def test_create_success_result(db_session: AsyncSession):
    """Create an ExecutionResult with SUCCESS outcome and default values."""
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
        outcome=ExecutionOutcome.SUCCESS,
        completeness=0.95,
        coherence=0.90,
        accuracy=0.85,
        overall_quality=0.90,
    )

    assert result.id is not None
    assert result.task_step_id == step.id
    assert result.task_execution_id == exec_.id
    assert result.outcome == "SUCCESS"
    assert result.completeness == 0.95
    assert result.coherence == 0.90
    assert result.accuracy == 0.85
    assert result.overall_quality == 0.90
    assert result.plan_matched == "NONE"
    assert result.status == "CREATED"
    assert result.replan_triggered == "0"
    assert result.evaluator == "llm"
    assert result.created_at is not None
    assert result.updated_at is not None


# ═══════════════════════════════════════════════════════════════
# 2. Create result — failure outcome with classification
# ═══════════════════════════════════════════════════════════════


async def test_create_failure_result(db_session: AsyncSession):
    """Create an ExecutionResult with FAILURE outcome and classification data."""
    task = make_task(id="task-fail")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-fail")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-fail")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
        outcome=ExecutionOutcome.FAILURE,
        failure_category="SYSTEM",
        failure_subcategory="TIMEOUT",
        is_recoverable="0",
        plan_matched="MAJOR",
        plan_deviation_detail="MAEOS timed out after 120s",
        replan_triggered="1",
        replan_scope="TASK",
    )

    assert result.outcome == "FAILURE"
    assert result.failure_category == "SYSTEM"
    assert result.failure_subcategory == "TIMEOUT"
    assert result.is_recoverable == "0"
    assert result.plan_matched == "MAJOR"
    assert result.plan_deviation_detail == "MAEOS timed out after 120s"
    assert result.replan_triggered == "1"
    assert result.replan_scope == "TASK"


# ═══════════════════════════════════════════════════════════════
# 3. Get result — by ID
# ═══════════════════════════════════════════════════════════════


async def test_get_result_by_id(db_session: AsyncSession):
    """Retrieve a single ExecutionResult by its ID."""
    task = make_task(id="task-get")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-get")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-get")
    db_session.add(exec_)
    await db_session.flush()

    created = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
    )

    fetched = await svc.get_result(db_session, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.outcome == created.outcome

    missing = await svc.get_result(db_session, "nonexistent-id")
    assert missing is None


# ═══════════════════════════════════════════════════════════════
# 4. List results — by step_id
# ═══════════════════════════════════════════════════════════════


async def test_list_results_by_step(db_session: AsyncSession):
    """List ExecutionResults filtered by task_step_id."""
    task = make_task(id="task-list-step")
    db_session.add(task)
    step_a = make_step(task_id=task.id, id="step-list-a", order=1)
    step_b = make_step(task_id=task.id, id="step-list-b", order=2)
    db_session.add(step_a)
    db_session.add(step_b)
    exec_a = make_execution(step_id=step_a.id, id="exec-list-a")
    exec_b = make_execution(step_id=step_b.id, id="exec-list-b")
    db_session.add(exec_a)
    db_session.add(exec_b)
    await db_session.flush()

    await svc.create_result(db_session, task_step_id=step_a.id, task_execution_id=exec_a.id)
    await svc.create_result(db_session, task_step_id=step_a.id, task_execution_id=exec_a.id,
                            outcome=ExecutionOutcome.FAILURE)
    await svc.create_result(db_session, task_step_id=step_b.id, task_execution_id=exec_b.id)

    # List by step_a
    results_a = await svc.list_results(db_session, task_step_id=step_a.id)
    assert len(results_a) == 2
    assert all(r.task_step_id == step_a.id for r in results_a)

    # List by step_b
    results_b = await svc.list_results(db_session, task_step_id=step_b.id)
    assert len(results_b) == 1
    assert results_b[0].task_step_id == step_b.id


# ═══════════════════════════════════════════════════════════════
# 5. List results — by execution_id
# ═══════════════════════════════════════════════════════════════


async def test_list_results_by_execution(db_session: AsyncSession):
    """List ExecutionResults filtered by task_execution_id."""
    task = make_task(id="task-list-exec")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-list-exec")
    db_session.add(step)
    exec_1 = make_execution(step_id=step.id, id="exec-list-1", attempt=1)
    exec_2 = make_execution(step_id=step.id, id="exec-list-2", attempt=2)
    db_session.add(exec_1)
    db_session.add(exec_2)
    await db_session.flush()

    await svc.create_result(db_session, task_step_id=step.id, task_execution_id=exec_1.id)
    await svc.create_result(db_session, task_step_id=step.id, task_execution_id=exec_2.id)

    results_1 = await svc.list_results(db_session, task_execution_id=exec_1.id)
    assert len(results_1) == 1
    assert results_1[0].task_execution_id == exec_1.id

    results_2 = await svc.list_results(db_session, task_execution_id=exec_2.id)
    assert len(results_2) == 1


# ═══════════════════════════════════════════════════════════════
# 6. List results — by outcome filter
# ═══════════════════════════════════════════════════════════════


async def test_list_results_by_outcome(db_session: AsyncSession):
    """List ExecutionResults filtered by outcome."""
    task = make_task(id="task-outcome")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-outcome")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-outcome")
    db_session.add(exec_)
    await db_session.flush()

    await svc.create_result(db_session, task_step_id=step.id, task_execution_id=exec_.id,
                            outcome=ExecutionOutcome.SUCCESS)
    await svc.create_result(db_session, task_step_id=step.id, task_execution_id=exec_.id,
                            outcome=ExecutionOutcome.FAILURE)

    successes = await svc.list_results(db_session, outcome=ExecutionOutcome.SUCCESS)
    assert len(successes) >= 1
    assert all(r.outcome == "SUCCESS" for r in successes)


# ═══════════════════════════════════════════════════════════════
# 7. List results — by status filter
# ═══════════════════════════════════════════════════════════════


async def test_list_results_by_status(db_session: AsyncSession):
    """List ExecutionResults filtered by lifecycle status."""
    task = make_task(id="task-status")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-status")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-status")
    db_session.add(exec_)
    await db_session.flush()

    await svc.create_result(db_session, task_step_id=step.id, task_execution_id=exec_.id,
                            status=ExecutionResultStatus.CREATED)
    await svc.create_result(db_session, task_step_id=step.id, task_execution_id=exec_.id,
                            status=ExecutionResultStatus.CLOSED)

    created_list = await svc.list_results(db_session, status=ExecutionResultStatus.CREATED)
    assert all(r.status == "CREATED" for r in created_list)


# ═══════════════════════════════════════════════════════════════
# 8. Update result — partial field update
# ═══════════════════════════════════════════════════════════════


async def test_update_result_partial(db_session: AsyncSession):
    """Update specific fields of an ExecutionResult without affecting others."""
    task = make_task(id="task-upd")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-upd")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-upd")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
        completeness=0.5,
        coherence=0.5,
        accuracy=0.5,
    )

    # Partial update: only quality scores
    updated = await svc.update_result(
        db_session,
        result,
        completeness=0.95,
        coherence=0.92,
        accuracy=0.88,
        overall_quality=0.92,
    )

    assert updated.completeness == 0.95
    assert updated.coherence == 0.92
    assert updated.accuracy == 0.88
    assert updated.overall_quality == 0.92
    # Fields not updated should remain
    assert updated.outcome == "SUCCESS"
    assert updated.status == "CREATED"


# ═══════════════════════════════════════════════════════════════
# 9. Update result — status lifecycle
# ═══════════════════════════════════════════════════════════════


async def test_update_result_status_lifecycle(db_session: AsyncSession):
    """Progress an ExecutionResult through its lifecycle states."""
    task = make_task(id="task-life")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-life")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-life")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
    )
    assert result.status == "CREATED"

    # CREATED → EVALUATED
    result = await svc.update_result(db_session, result, status=ExecutionResultStatus.EVALUATED)
    assert result.status == "EVALUATED"

    # EVALUATED → COMPARED
    result = await svc.update_result(db_session, result, status=ExecutionResultStatus.COMPARED)
    assert result.status == "COMPARED"

    # COMPARED → REPLAN_TRIGGERED
    result = await svc.update_result(
        db_session, result,
        status=ExecutionResultStatus.REPLAN_TRIGGERED,
        replan_triggered="1",
        replan_scope="TASK",
    )
    assert result.status == "REPLAN_TRIGGERED"
    assert result.replan_triggered == "1"
    assert result.replan_scope == "TASK"

    # REPLAN_TRIGGERED → CLOSED
    result = await svc.update_result(db_session, result, status=ExecutionResultStatus.CLOSED)
    assert result.status == "CLOSED"


# ═══════════════════════════════════════════════════════════════
# 10. Cascade delete — delete step deletes execution_results
# ═══════════════════════════════════════════════════════════════


async def test_cascade_delete_step(db_session: AsyncSession):
    """Deleting a TaskStep cascades to its ExecutionResults."""
    task = make_task(id="task-del-step")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-del-cascade")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-del-cascade")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
    )
    result_id = result.id

    # Verify it exists
    all_before = await svc.list_results(db_session)
    assert len(all_before) >= 1

    # Delete the step via ORM — triggers relationship cascade
    # (TaskStepModel.executions → delete-orphan → deletes executions,
    #  then ExecutionResultModel.step cascade → deletes results)
    step_obj = await db_session.get(TaskStepModel, step.id)
    assert step_obj is not None
    await db_session.delete(step_obj)
    await db_session.flush()

    # The result should be gone (via ORM cascade)
    fetched = await svc.get_result(db_session, result_id)
    assert fetched is None


# ═══════════════════════════════════════════════════════════════
# 11. Cascade delete — delete execution deletes result
# ═══════════════════════════════════════════════════════════════


async def test_cascade_delete_execution(db_session: AsyncSession):
    """Deleting a TaskExecution cascades to its ExecutionResults."""
    task = make_task(id="task-del-exec")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-del-exec")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-del-cascade-2")
    db_session.add(exec_)
    await db_session.flush()

    result = await svc.create_result(
        db_session,
        task_step_id=step.id,
        task_execution_id=exec_.id,
    )
    result_id = result.id

    # Delete the execution via ORM — triggers ExecutionResultModel cascade
    exec_obj = await db_session.get(TaskExecutionModel, exec_.id)
    assert exec_obj is not None
    await db_session.delete(exec_obj)
    await db_session.flush()

    # The result should be gone (via ORM cascade)
    fetched = await svc.get_result(db_session, result_id)
    assert fetched is None


# ═══════════════════════════════════════════════════════════════
# 12. Count results — with and without filters
# ═══════════════════════════════════════════════════════════════


async def test_count_results(db_session: AsyncSession):
    """Count ExecutionResults with and without filters."""
    task = make_task(id="task-cnt")
    db_session.add(task)
    step = make_step(task_id=task.id, id="step-cnt")
    db_session.add(step)
    exec_ = make_execution(step_id=step.id, id="exec-cnt")
    db_session.add(exec_)
    await db_session.flush()

    # Multiple results for same step
    for i in range(3):
        await svc.create_result(
            db_session,
            task_step_id=step.id,
            task_execution_id=exec_.id,
            outcome=ExecutionOutcome.SUCCESS if i < 2 else ExecutionOutcome.FAILURE,
        )

    # Total count (may include results from other tests if shared session,
    # but each test gets a fresh DB — so this should be exactly 3)
    total = await svc.count_results(db_session)
    assert total == 3

    # Filter by outcome
    success_count = await svc.count_results(db_session, outcome=ExecutionOutcome.SUCCESS)
    assert success_count == 2

    failure_count = await svc.count_results(db_session, outcome=ExecutionOutcome.FAILURE)
    assert failure_count == 1

    # Filter by step
    step_count = await svc.count_results(db_session, task_step_id=step.id)
    assert step_count == 3
