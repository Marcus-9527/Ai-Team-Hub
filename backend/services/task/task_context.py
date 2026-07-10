"""
task_context.py — Task Context Builder

Builds the input context for each TaskStep, providing:
  - Task goal / description
  - Previous step outputs (if any)
  - Channel context summary (optional)

This context is injected into the MAEOS task description for each step.
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TaskModel, TaskStepModel
from backend.services.task.task_state import TaskStateManager

logger = logging.getLogger("task.context")


class TaskContextBuilder:
    """Builds per-step execution context from task + prior steps."""

    def __init__(self):
        self.state = TaskStateManager()

    async def build_step_context(
        self,
        db: AsyncSession,
        task: TaskModel,
        step: TaskStepModel,
    ) -> str:
        """
        Build the context string for a single step.

        Includes:
          1. Task goal (description)
          2. Previous step outputs (in reverse chronological order)
          3. The current step's objective

        Returns a plain-text context blob to inject into the MAEOS description.
        """
        parts: list[str] = []

        # 1. Task goal
        parts.append(f"[TASK GOAL]\n{task.description}")

        # 2. Previous step outputs (completed steps only, sorted by order)
        prior_steps = await self._get_prior_completed_steps(
            db, task.id, step.order
        )
        if prior_steps:
            prior_lines = []
            for ps in prior_steps:
                tag = f"[STEP {ps.order}: {ps.objective[:80]}]"
                output = (ps.output or "")[:2000]
                prior_lines.append(f"{tag}\n{output}")
            parts.append("[PRIOR STEPS]\n" + "\n---\n".join(prior_lines))

        # 3. Current step objective
        parts.append(f"[CURRENT STEP]\n{step.objective}")

        context = "\n\n---\n\n".join(parts)
        logger.debug(
            f"Built context for step {step.id} "
            f"(order={step.order}, {len(context)} chars)"
        )
        return context

    async def _get_prior_completed_steps(
        self,
        db: AsyncSession,
        task_id: str,
        current_order: int,
    ) -> list[TaskStepModel]:
        """Get all completed steps with order < current_order."""
        all_steps = await self.state.list_steps(db, task_id)
        return [
            s for s in all_steps
            if s.order < current_order and s.status == "COMPLETED"
        ]

    async def build_maeos_description(
        self,
        db: AsyncSession,
        task: TaskModel,
        step: TaskStepModel,
    ) -> str:
        """
        Build the full description string to submit to MAEOS.

        This is the concatenation of context + step objective,
        used as the `description` parameter in MAEOS.submit().
        """
        context = await self.build_step_context(db, task, step)
        return context
