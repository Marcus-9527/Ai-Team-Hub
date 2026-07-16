"""brain/task_hook.py — Brain Task Hook (Phase 12.3 + 12.5)

Wires ReflectionService + MemoryConsolidationService into the task lifecycle.
Registered alongside MemoryTaskHook in main.py.

Ponytail: thin adapter — delegates to services. No new engine/scheduler.
"""
from __future__ import annotations

import asyncio
import logging

from backend.services.task.task_hooks import (
    TaskHook,
    TaskHookContext,
    TaskLifecycleEvent,
)
from backend.services.brain.reflection import get_reflection_service, ReflectionService
from backend.services.brain.consolidation import get_consolidation_service

logger = logging.getLogger("brain.task_hook")


class BrainTaskHook(TaskHook):
    """Task lifecycle hook that triggers brain reflection + consolidation.

    - TASK_COMPLETED → lesson + memory consolidation
    - TASK_FAILED → lesson
    """

    def __init__(
        self,
        reflection_svc: ReflectionService | None = None,
    ):
        self._reflection = reflection_svc or get_reflection_service()
        self._consolidation = get_consolidation_service()

    async def on_task_completed(self, ctx: TaskHookContext) -> None:
        """Fire-and-forget reflection + consolidation on task completion."""
        ws_id = ctx.workspace_id
        if ctx.execution_teammate_id:
            asyncio.ensure_future(self._reflection.on_task_completed(ctx))
        # 频道摘要：每个频道维护一条最新摘要片段（最小版本，不用向量库）
        if ctx.channel_id:
            asyncio.ensure_future(self._reflection.on_channel_summary(
                ctx.channel_id, ctx.task_title, ctx.task_status, ws_id,
            ))
        asyncio.ensure_future(self._consolidation.consolidate(lookback_hours=24))

    async def on_task_failed(self, ctx: TaskHookContext) -> None:
        """Fire-and-forget reflection on task failure."""
        if ctx.execution_teammate_id:
            asyncio.ensure_future(self._reflection.on_task_failed(ctx))

    async def on_review_rejected(self, ctx: TaskHookContext) -> None:
        """Fire-and-forget reflection on review rejection."""
        teammate_id = ctx.extra.get("teammate_id", "")
        task_id = ctx.task_id
        comments = ctx.extra.get("comments", "")
        round_no = ctx.extra.get("round_no", 1)
        if teammate_id and task_id:
            asyncio.ensure_future(self._reflection.on_review_rejected(
                task_id, teammate_id, comments, round_no, ctx.workspace_id,
            ))
