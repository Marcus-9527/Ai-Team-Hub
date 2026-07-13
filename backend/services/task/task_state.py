"""
task_state.py — TaskStateManager

Manages Task / TaskStep / TaskExecution state transitions and DB persistence.
Provides the state machine logic that enforces valid transitions.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskExecutionModel,
    TaskPolicyModel,
    RiskLevel,
    TaskStatus,
    TaskStepStatus,
    gen_uuid,
    utcnow,
)

logger = logging.getLogger("task.state")


class TaskStateManager:
    """
    Handles state persistence and transitions for Tasks, Steps, and Executions.

    Each method is a stateless DB operation — the caller (TaskManager) owns
    orchestration logic.
    """

    # ── Task CRUD ──

    async def create_task(
        self,
        db: AsyncSession,
        *,
        title: str,
        description: str = "",
        channel_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        priority: int = 2,
        intent: str = "",
        created_by: str = "system",
    ) -> TaskModel:
        """Create a new Task with CREATED status."""
        task = TaskModel(
            title=title,
            description=description or title,
            channel_id=channel_id,
            workspace_id=workspace_id,
            priority=priority,
            intent=intent,
            created_by=created_by,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        await db.flush()

        # Create default execution policy (Phase C2)
        policy = TaskPolicyModel(
            task_id=task.id,
            approval_required="0",
            max_retry=2,
            max_cost=0,
            risk_level=RiskLevel.LOW,
            allowed_teammates="[]",
        )
        db.add(policy)
        await db.flush()

        logger.info(f"[TASK] created {task.id}: {title[:60]}")
        return task

    async def get_task(self, db: AsyncSession, task_id: str) -> Optional[TaskModel]:
        """Get a single task by ID (with steps eagerly loaded)."""
        result = await db.execute(
            select(TaskModel)
            .where(TaskModel.id == task_id)
            .options(selectinload(TaskModel.steps))
        )
        return result.scalar_one_or_none()

    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        channel_id: Optional[str] = None,
        status: Optional[str] = None,
        workspace_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskModel]:
        """List tasks with optional filters, ordered by created_at desc."""
        query = select(TaskModel).options(selectinload(TaskModel.steps))

        if channel_id:
            query = query.where(TaskModel.channel_id == channel_id)
        if status:
            query = query.where(TaskModel.status == status)
        if workspace_id:
            query = query.where(TaskModel.workspace_id == workspace_id)

        query = query.order_by(TaskModel.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    async def count_tasks(
        self,
        db: AsyncSession,
        *,
        channel_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count tasks with optional filters."""
        query = select(func.count(TaskModel.id))

        if channel_id:
            query = query.where(TaskModel.channel_id == channel_id)
        if status:
            query = query.where(TaskModel.status == status)

        result = await db.execute(query)
        return result.scalar() or 0

    async def update_task(
        self,
        db: AsyncSession,
        task: TaskModel,
        **kwargs,
    ) -> TaskModel:
        """Update task fields (except status — use transition_status for that)."""
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return task

    async def delete_task(self, db: AsyncSession, task: TaskModel) -> None:
        """Delete a task (cascades to steps and executions via DB FK)."""
        await db.delete(task)
        await db.flush()
        logger.info(f"[TASK] deleted {task.id}")

    # ── Task Status Transitions ──

    async def transition_task_status(
        self,
        db: AsyncSession,
        task: TaskModel,
        new_status: str,
    ) -> TaskModel:
        """
        Transition task to a new status with validation.

        Raises ValueError if transition is invalid.
        """
        old_status = task.status

        if old_status == new_status:
            return task  # no-op

        if not TaskStatus.can_transition(old_status, new_status):
            raise ValueError(
                f"Invalid task status transition: {old_status} → {new_status}"
            )

        task.status = new_status
        task.updated_at = datetime.now(timezone.utc)

        if new_status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(timezone.utc)

        await db.flush()
        logger.info(f"[TASK] {task.id} status: {old_status} → {new_status}")
        return task

    # ── TaskStep CRUD ──

    async def create_step(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        order: int,
        objective: str = "",
        teammate_id: Optional[str] = None,
        input_context: str = "",
        requires_approval: str = "0",
    ) -> TaskStepModel:
        """Create a new TaskStep with PENDING status."""
        step = TaskStepModel(
            task_id=task_id,
            order=order,
            objective=objective,
            teammate_id=teammate_id,
            input_context=input_context,
            requires_approval=requires_approval,
            status=TaskStepStatus.PENDING,
        )
        db.add(step)
        await db.flush()
        return step

    async def get_step(self, db: AsyncSession, step_id: str) -> Optional[TaskStepModel]:
        """Get a single step by ID."""
        result = await db.execute(
            select(TaskStepModel).where(TaskStepModel.id == step_id)
        )
        return result.scalar_one_or_none()

    async def list_steps(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> list[TaskStepModel]:
        """List all steps for a task, ordered by `order`."""
        result = await db.execute(
            select(TaskStepModel)
            .where(TaskStepModel.task_id == task_id)
            .order_by(TaskStepModel.order)
        )
        return list(result.scalars().all())

    async def transition_step_status(
        self,
        db: AsyncSession,
        step: TaskStepModel,
        new_status: str,
    ) -> TaskStepModel:
        """
        Transition a step to a new status with validation.

        Raises ValueError if transition is invalid.
        """
        old_status = step.status

        if old_status == new_status:
            return step

        if not TaskStepStatus.can_transition(old_status, new_status):
            raise ValueError(
                f"Invalid step status transition: {old_status} → {new_status}"
            )

        step.status = new_status
        now = datetime.now(timezone.utc)

        if new_status == TaskStepStatus.RUNNING:
            step.started_at = now
        elif new_status in (TaskStepStatus.COMPLETED, TaskStepStatus.FAILED):
            step.completed_at = now

        await db.flush()
        logger.debug(f"[TASK-STEP] {step.id} status: {old_status} → {new_status}")
        return step

    async def update_step(
        self,
        db: AsyncSession,
        step: TaskStepModel,
        **kwargs,
    ) -> TaskStepModel:
        """Update step fields."""
        for key, value in kwargs.items():
            if hasattr(step, key):
                setattr(step, key, value)
        await db.flush()
        return step

    # ── TaskExecution CRUD ──

    async def create_execution(
        self,
        db: AsyncSession,
        *,
        task_step_id: str,
        attempt: int = 1,
        maeos_task_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        teammate_id: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> TaskExecutionModel:
        """Create a new TaskExecution record (v2.5 with trace/cost fields)."""
        execution = TaskExecutionModel(
            task_step_id=task_step_id,
            attempt=attempt,
            maeos_task_id=maeos_task_id,
            trace_id=trace_id,
            start_time=start_time,
            teammate_id=teammate_id,
            model_name=model_name,
        )
        db.add(execution)
        await db.flush()
        return execution

    async def update_execution(
        self,
        db: AsyncSession,
        execution: TaskExecutionModel,
        **kwargs,
    ) -> TaskExecutionModel:
        """Update execution fields (duration, token_usage, cost, etc.)."""
        for key, value in kwargs.items():
            if hasattr(execution, key):
                setattr(execution, key, value)
        await db.flush()
        return execution

    async def list_executions(
        self,
        db: AsyncSession,
        task_step_id: str,
    ) -> list[TaskExecutionModel]:
        """List all executions for a step, ordered by attempt."""
        result = await db.execute(
            select(TaskExecutionModel)
            .where(TaskExecutionModel.task_step_id == task_step_id)
            .order_by(TaskExecutionModel.attempt)
        )
        return list(result.scalars().all())

    # ── V3.0 Phase B: Cross-step Execution Queries ──

    async def list_executions_by_task(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> list[dict]:
        """
        List all executions for a task (across all steps), joined with step info.

        Returns list of dicts with execution fields + step info.
        """
        from sqlalchemy import text
        query = text("""
            SELECT
                e.id,
                e.task_step_id,
                e.maeos_task_id,
                e.trace_id,
                e.attempt,
                e.start_time,
                e.end_time,
                e.teammate_id,
                e.model_name,
                e.execution_time_ms,
                e.input_tokens,
                e.output_tokens,
                e.total_tokens,
                e.estimated_cost,
                e.error,
                e.created_at,
                s."order" AS step_order,
                s.objective AS step_objective,
                s.status AS step_status
            FROM task_executions e
            JOIN task_steps s ON s.id = e.task_step_id
            WHERE s.task_id = :task_id
            ORDER BY e.created_at DESC
        """)
        result = await db.execute(query, {"task_id": task_id})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def list_results_by_task(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> list[dict]:
        """
        List all ExecutionResults for a task (across all steps), joined with step/execution info.

        Returns list of dicts with result fields + step order + execution cost.
        """
        from sqlalchemy import text
        query = text("""
            SELECT
                r.id,
                r.task_step_id,
                r.task_execution_id,
                r.outcome,
                r.completeness,
                r.coherence,
                r.accuracy,
                r.overall_quality,
                r.plan_matched,
                r.plan_deviation_detail,
                r.failure_category,
                r.failure_subcategory,
                r.is_recoverable,
                r.evaluator,
                r.evaluation_confidence,
                r.status,
                r.created_at,
                r.updated_at,
                s."order" AS step_order,
                s.objective AS step_objective,
                e.total_tokens,
                e.estimated_cost
            FROM execution_results r
            JOIN task_steps s ON s.id = r.task_step_id
            JOIN task_executions e ON e.id = r.task_execution_id
            WHERE s.task_id = :task_id
            ORDER BY r.created_at DESC
        """)
        result = await db.execute(query, {"task_id": task_id})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def get_task_analytics(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> dict:
        """
        Get aggregated analytics for a task.

        Returns execution count, success rate, avg quality, token/cost totals.
        """
        from sqlalchemy import text
        query = text("""
            SELECT
                COUNT(e.id) AS execution_count,
                SUM(CASE WHEN e.error = '' OR e.error IS NULL THEN 1 ELSE 0 END) AS success_count,
                COALESCE(AVG(r.overall_quality), 0.0) AS avg_quality,
                COALESCE(SUM(e.total_tokens), 0) AS total_tokens,
                COALESCE(SUM(e.estimated_cost), 0) AS total_cost_micro
            FROM task_executions e
            JOIN task_steps s ON s.id = e.task_step_id
            LEFT JOIN execution_results r ON r.task_execution_id = e.id
            WHERE s.task_id = :task_id
        """)
        result = await db.execute(query, {"task_id": task_id})
        row = result.fetchone()
        if not row:
            return {
                "execution_count": 0,
                "success_rate": 0.0,
                "avg_quality": 0.0,
                "total_tokens": 0,
                "total_cost_micro": 0,
            }

        data = dict(row._mapping)
        total = data.get("execution_count", 0) or 0
        success = data.get("success_count", 0) or 0
        data["success_rate"] = round(success / total, 4) if total > 0 else 0.0
        data["avg_quality"] = round(float(data.get("avg_quality", 0) or 0), 4)
        return data
