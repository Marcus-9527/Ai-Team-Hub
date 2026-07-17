"""
task_manager.py — TaskManager

Business logic for Task lifecycle orchestration.
Wraps TaskStateManager with higher-level operations like
create_task_with_steps, pause, resume, cancel etc.
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskModel, TaskStatus
from backend.services.task.task_state import TaskStateManager

logger = logging.getLogger("task.manager")


class TaskManager:
    """
    High-level Task lifecycle operations.

    Uses TaskStateManager for DB persistence and state transitions.
    """

    def __init__(self):
        self.state = TaskStateManager()

    # ── Create ──

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
        """Create a new task."""
        return await self.state.create_task(
            db,
            title=title,
            description=description,
            channel_id=channel_id,
            workspace_id=workspace_id,
            priority=priority,
            intent=intent,
            created_by=created_by,
        )

    # ── Read ──

    async def get_task(self, db: AsyncSession, task_id: str) -> Optional[TaskModel]:
        """Get task by ID."""
        return await self.state.get_task(db, task_id)

    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        workspace_id: str,
        channel_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskModel]:
        """List tasks scoped to a workspace with optional filters."""
        return await self.state.list_tasks(
            db,
            workspace_id=workspace_id,
            channel_id=channel_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def count_tasks(
        self,
        db: AsyncSession,
        *,
        channel_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count tasks with optional filters."""
        return await self.state.count_tasks(
            db,
            channel_id=channel_id,
            status=status,
        )

    # ── Update ──

    async def update_task(
        self,
        db: AsyncSession,
        task_id: str,
        **kwargs,
    ) -> TaskModel:
        """Update task metadata (title, description, priority, etc.).

        Status updates MUST go through transition_task_status.
        """
        task = await self.state.get_task(db, task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # Prevent status updates via this path
        if "status" in kwargs:
            raise ValueError("Use transition_task_status to change task status")

        return await self.state.update_task(db, task, **kwargs)

    # ── Delete ──

    async def delete_task(self, db: AsyncSession, task_id: str) -> None:
        """Delete a task by ID."""
        task = await self.state.get_task(db, task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        await self.state.delete_task(db, task)

    # ── Status Transitions ──

    async def transition_task_status(
        self,
        db: AsyncSession,
        task_id: str,
        new_status: str,
    ) -> TaskModel:
        """Transition task to a new status."""
        task = await self.state.get_task(db, task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        return await self.state.transition_task_status(db, task, new_status)

    # ── High-Level Lifecycle Operations ──

    async def start_planning(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Move task from PENDING/CREATED to PLANNING."""
        return await self.transition_task_status(db, task_id, TaskStatus.PLANNING)

    async def start_assigned(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Move task from PLANNING to ASSIGNED."""
        return await self.transition_task_status(db, task_id, TaskStatus.ASSIGNED)

    async def start_execution(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Move task from PLANNING/ASSIGNED to RUNNING."""
        return await self.transition_task_status(db, task_id, TaskStatus.RUNNING)

    async def pause(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Pause a running task (RUNNING → PAUSED)."""
        return await self.transition_task_status(db, task_id, TaskStatus.PAUSED)

    async def resume(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Resume a paused task (PAUSED → RUNNING)."""
        return await self.transition_task_status(db, task_id, TaskStatus.RUNNING)

    async def cancel(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Cancel a task (any active state → CANCELLED)."""
        return await self.transition_task_status(db, task_id, TaskStatus.CANCELLED)

    async def complete(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Mark task as completed (EXECUTING → COMPLETED)."""
        return await self.transition_task_status(db, task_id, TaskStatus.COMPLETED)

    async def fail(self, db: AsyncSession, task_id: str) -> TaskModel:
        """Mark task as failed (EXECUTING/PLANNING → FAILED)."""
        return await self.transition_task_status(db, task_id, TaskStatus.FAILED)
