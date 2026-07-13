"""
memory_event_handler.py — V3.1 Phase A Memory Event Handler

Converts task lifecycle events into persistent MemoryItems.

Each handler method creates one or more MemoryItem records
via the MemoryService singleton. Events are fired through
the TaskHookRegistry (see services/task/task_hooks.py).

v3.1 Optimization: Buffered batch writes to avoid N transactions for N events.
MemoryTaskHook now buffers items and flushes to DB in batches via store_batch().

Event → Memory mapping:
  TASK_CREATED        → MemoryType.TASK   (task goal)
  TASK_COMPLETED      → MemoryType.TASK   (outcome summary)
  TASK_FAILED         → MemoryType.EVENT  (failure reason)
  STEP_COMPLETED      → MemoryType.EXECUTION (step result)
  EXECUTION_COMPLETED → MemoryType.EXECUTION (execution metrics)
  PLAN_APPROVED       → MemoryType.DECISION  (plan decision)

Constraints:
  ✅ No MAEOS modification
  ✅ No Planner core modification
  ✅ No Chat flow modification
  ✅ No TaskExecutor execution-logic change
  ✅ Memory enters only through this Service Hook
  ✅ Planner accesses Memory only through PlannerContext
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from backend.services.memory.memory_types import MemoryItem, MemoryType
from backend.services.memory.memory_service import get_memory_service
from backend.services.task.task_hooks import (
    TaskHook,
    TaskHookContext,
    TaskLifecycleEvent,
)

logger = logging.getLogger("memory.event_handler")


# ═══════════════════════════════════════════════════════════════
# MemoryBuffer — Batch write buffer
# ═══════════════════════════════════════════════════════════════

class MemoryBuffer:
    """
    Accumulates MemoryItems and flushes them to DB in batches.

    Two flush triggers:
      - Threshold: buffer reaches `max_size` items
      - Timeout: `flush_interval` seconds since first unflushed item

    Thread-safe via asyncio lock.
    """

    def __init__(
        self,
        max_size: int = 50,
        flush_interval: float = 2.0,
    ):
        self.max_size = max_size
        self.flush_interval = flush_interval
        self._items: list[MemoryItem] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._timer_handle: Optional[asyncio.TimerHandle] = None

    async def add(self, item: MemoryItem) -> None:
        """Add an item to the buffer. Triggers flush if threshold reached."""
        async with self._lock:
            self._items.append(item)
            if len(self._items) >= self.max_size:
                await self._flush_locked()
            elif len(self._items) == 1:
                # First item — schedule timeout flush
                self._schedule_timeout()

    async def flush(self) -> None:
        """Force-flush all buffered items. Called on graceful shutdown."""
        async with self._lock:
            if self._items:
                await self._flush_locked()

    def _schedule_timeout(self) -> None:
        """Schedule a delayed flush."""
        loop = asyncio.get_event_loop()
        self._timer_handle = loop.call_later(
            self.flush_interval,
            lambda: asyncio.ensure_future(self._timeout_flush()),
        )

    async def _timeout_flush(self) -> None:
        """Called by the timeout timer."""
        async with self._lock:
            if self._items:
                await self._flush_locked()

    async def _flush_locked(self) -> None:
        """
        Write all buffered items to DB via store_batch.
        Caller MUST hold self._lock.
        """
        batch = self._items
        self._items = []
        # Cancel any pending timer
        if self._timer_handle:
            self._timer_handle.cancel()
            self._timer_handle = None

        if not batch:
            return

        try:
            svc = get_memory_service()
            await svc.store_batch(batch)
            logger.debug(f"[MEMORY-BUFFER] Flushed {len(batch)} items")
        except Exception as e:
            logger.warning(
                f"[MEMORY-BUFFER] Batch flush failed ({len(batch)} items): {e}",
                exc_info=True,
            )
            # Re-queue items on failure (best-effort — drop if queue grows unbounded)
            # To avoid infinite re-queue loops, accept loss under severe pressure
            logger.warning(
                f"[MEMORY-BUFFER] Dropping {len(batch)} items after flush failure"
            )


# ═══════════════════════════════════════════════════════════════
# MemoryTaskHook
# ═══════════════════════════════════════════════════════════════


class MemoryTaskHook(TaskHook):
    """
    Converts task lifecycle events into MemoryItems and persists them.

    Each event type maps to a specific MemoryType to maintain semantic
    separation for downstream retrieval and ranking.

    Thread-safe via MemoryService's async engine.
    Buffered writes via MemoryBuffer — call flush() on shutdown for zero loss.
    """

    # Maximum content length per MemoryItem (preserve tokens for retrieval)
    MAX_CONTENT_CHARS = 2000

    def __init__(
        self,
        max_content_chars: int = MAX_CONTENT_CHARS,
        buffer_max_size: int = 50,
        buffer_flush_interval: float = 2.0,
    ):
        self.max_chars = max_content_chars
        self._buffer = MemoryBuffer(
            max_size=buffer_max_size,
            flush_interval=buffer_flush_interval,
        )

    @property
    def buffer(self) -> MemoryBuffer:
        """Expose buffer for test inspection / manual flush."""
        return self._buffer

    # ── TASK_CREATED ──────────────────────────────────────────────

    async def on_task_created(self, ctx: TaskHookContext) -> None:
        """
        Persist a TASK memory recording the goal and intent.

        This memory is retrievable during future planning as prior
        context for tasks with similar titles or descriptions.
        """
        content_parts = [f"Task: {ctx.task_title}"]
        if ctx.task_description:
            content_parts.append(ctx.task_description)

        content = "\n".join(content_parts)[: self.max_chars]

        item = MemoryItem(
            memory_type=MemoryType.TASK,
            content=content,
            source_id=ctx.task_id,
            relevance_score=0.9,
            metadata={
                "event": TaskLifecycleEvent.TASK_CREATED.value,
                "title": ctx.task_title,
                "channel_id": ctx.channel_id,
                "workspace_id": ctx.workspace_id,
            },
        )
        await self._store(item, "TASK_CREATED")

    # ── TASK_COMPLETED ────────────────────────────────────────────

    async def on_task_completed(self, ctx: TaskHookContext) -> None:
        """
        Persist a TASK memory recording the successful outcome.
        Also triggers insight generation (fire-and-forget).

        Relevant for future "what worked before" retrieval.
        """
        content = (
            f"Task completed: {ctx.task_title}\n"
            f"Status: {ctx.task_status}\n"
            f"Description: {ctx.task_description}"
        )[: self.max_chars]

        item = MemoryItem(
            memory_type=MemoryType.TASK,
            content=content,
            source_id=ctx.task_id,
            relevance_score=0.8,
            metadata={
                "event": TaskLifecycleEvent.TASK_COMPLETED.value,
                "title": ctx.task_title,
                "status": ctx.task_status,
                "channel_id": ctx.channel_id,
                "workspace_id": ctx.workspace_id,
            },
        )
        await self._store(item, "TASK_COMPLETED")

        # ── Phase 13: Summary memory ──
        summary = MemoryItem(
            memory_type=MemoryType.GLOBAL if ctx.workspace_id else MemoryType.TASK,
            content=(
                f"[Summary] Task \"{ctx.task_title}\" completed: "
                f"{ctx.task_status}. {ctx.task_description}"
            )[:self.max_chars],
            source_id=ctx.task_id,
            relevance_score=0.75,
            metadata={
                "event": "POST_TASK_SUMMARY",
                "title": ctx.task_title,
                "status": ctx.task_status,
                "channel_id": ctx.channel_id,
                "workspace_id": ctx.workspace_id,
                "scope": "workspace" if ctx.workspace_id else "private",
            },
        )
        await self._store(summary, "POST_TASK_SUMMARY")

        # ── V2.7 Phase C: Trigger insight generation (fire-and-forget) ──
        asyncio.ensure_future(self._trigger_intelligence(ctx.task_id))

    # ── TASK_FAILED ──────────────────────────────────────────────

    async def on_task_failed(self, ctx: TaskHookContext) -> None:
        """
        Persist an EVENT memory recording the failure.
        Also triggers insight generation (fire-and-forget).

        Retained for diagnostic retrieval — "what went wrong before".
        """
        parts = [f"Task failed: {ctx.task_title}"]
        if ctx.step_error:
            parts.append(f"Error: {ctx.step_error}")

        content = "\n".join(parts)[: self.max_chars]

        item = MemoryItem(
            memory_type=MemoryType.EVENT,
            content=content,
            source_id=ctx.task_id,
            relevance_score=0.7,
            metadata={
                "event": TaskLifecycleEvent.TASK_FAILED.value,
                "title": ctx.task_title,
                "step_error": ctx.step_error or "",
                "step_id": ctx.step_id or "",
                "channel_id": ctx.channel_id,
            },
        )
        await self._store(item, "TASK_FAILED")

        # ── V2.7 Phase C: Trigger insight generation (fire-and-forget) ──
        asyncio.ensure_future(self._trigger_intelligence(ctx.task_id))

    # ── STEP_COMPLETED ───────────────────────────────────────────

    async def on_step_completed(self, ctx: TaskHookContext) -> None:
        """
        Persist an EXECUTION memory per completed step.

        The step objective + output preview becomes searchable
        context for future steps in similar tasks.
        """
        output_preview = (ctx.step_output or "")[:500]
        content = (
            f"Step {ctx.step_order}: {ctx.step_objective}\n"
            f"Output: {output_preview}"
        )[: self.max_chars]

        item = MemoryItem(
            memory_type=MemoryType.EXECUTION,
            content=content,
            source_id=ctx.step_id or ctx.task_id,
            relevance_score=0.7,
            metadata={
                "event": TaskLifecycleEvent.STEP_COMPLETED.value,
                "task_id": ctx.task_id,
                "step_order": ctx.step_order,
                "step_id": ctx.step_id,
                "channel_id": ctx.channel_id,
            },
        )
        await self._store(item, "STEP_COMPLETED")

    # ── EXECUTION_COMPLETED ──────────────────────────────────────

    async def on_execution_completed(self, ctx: TaskHookContext) -> None:
        """
        Persist an EXECUTION memory with outcome and cost metrics.

        Used for performance analytics and cost-aware planning.
        """
        content = (
            f"Execution of step {ctx.step_order} ({ctx.step_objective}): "
            f"outcome={ctx.execution_outcome}, "
            f"duration={ctx.execution_duration_ms}ms, "
            f"tokens={ctx.execution_total_tokens}"
        )[: self.max_chars]

        item = MemoryItem(
            memory_type=MemoryType.EXECUTION,
            content=content,
            source_id=ctx.execution_id or ctx.task_id,
            relevance_score=0.6,
            metadata={
                "event": TaskLifecycleEvent.EXECUTION_COMPLETED.value,
                "task_id": ctx.task_id,
                "step_id": ctx.step_id,
                "step_order": ctx.step_order,
                "outcome": ctx.execution_outcome,
                "duration_ms": ctx.execution_duration_ms,
                "total_tokens": ctx.execution_total_tokens,
                "teammate_id": ctx.execution_teammate_id,
                "execution_id": ctx.execution_id,
            },
        )
        await self._store(item, "EXECUTION_COMPLETED")

        # ── Phase 13: Post-execution decision + experience memory ──
        await self._store_post_execution_memories(ctx)

    # ── Phase 13: Post-execution auto-generation ──

    async def _store_post_execution_memories(self, ctx: TaskHookContext) -> None:
        """Generate decision + experience memories after an execution completes."""
        # Decision memory: key takeaway from this execution
        decision = MemoryItem(
            memory_type=MemoryType.DECISION,
            content=(
                f"Step {ctx.step_order} ({ctx.step_objective}): "
                f"outcome={ctx.execution_outcome}, "
                f"duration={ctx.execution_duration_ms}ms"
            )[:self.max_chars],
            source_id=ctx.task_id,
            relevance_score=0.7,
            metadata={
                "event": "POST_EXECUTION_DECISION",
                "task_id": ctx.task_id,
                "step_id": ctx.step_id,
                "step_order": ctx.step_order,
                "outcome": ctx.execution_outcome,
                "teammate_id": ctx.execution_teammate_id,
                "scope": "private",
            },
        )
        await self._store(decision, "POST_EXEC_DECISION")

        # Experience memory: performance signal for future similar tasks
        experience = MemoryItem(
            memory_type=MemoryType.EXECUTION,
            content=(
                f"Experience: {ctx.step_objective} → {ctx.execution_outcome} "
                f"({ctx.execution_duration_ms}ms, {ctx.execution_total_tokens}tok)"
            )[:self.max_chars],
            source_id=ctx.task_id,
            relevance_score=0.65,
            metadata={
                "event": "POST_EXECUTION_EXPERIENCE",
                "task_id": ctx.task_id,
                "step_id": ctx.step_id,
                "teammate_id": ctx.execution_teammate_id,
                "scope": "private",
                "outcome": ctx.execution_outcome,
                "duration_ms": ctx.execution_duration_ms,
            },
        )
        await self._store(experience, "POST_EXEC_EXPERIENCE")

    # ── PLAN_APPROVED ────────────────────────────────────────────

    async def on_plan_approved(self, ctx: TaskHookContext) -> None:
        """
        Persist a DECISION memory recording what plan was approved.

        Logs strategic decisions so future planning can reference
        "what approach was taken" for similar tasks.
        """
        content = (
            f"Plan approved for task: {ctx.task_title}\n"
            f"Plan summary: {ctx.plan_summary}"
        )[: self.max_chars]

        item = MemoryItem(
            memory_type=MemoryType.DECISION,
            content=content,
            source_id=ctx.plan_id or ctx.task_id,
            relevance_score=0.85,
            metadata={
                "event": TaskLifecycleEvent.PLAN_APPROVED.value,
                "task_id": ctx.task_id,
                "plan_id": ctx.plan_id,
                "plan_summary": ctx.plan_summary,
                "channel_id": ctx.channel_id,
                "workspace_id": ctx.workspace_id,
            },
        )
        await self._store(item, "PLAN_APPROVED")

    # ── Internal ─────────────────────────────────────────────────

    async def _store(self, item: MemoryItem, event_label: str) -> None:
        """
        Buffer a single MemoryItem for batch persistence.
        Auto-computes embedding vector for semantic search if not already set.
        Actual DB write happens on batch flush (threshold or timeout).
        """
        if not item.embedding and item.content:
            from backend.services.memory.memory_service import MemoryService
            item.embedding = MemoryService.compute_embedding(item.content)
        await self._buffer.add(item)
        logger.debug(f"[MEMORY-EVENT] {event_label} → buffered {item.id}")

    # ── V2.7 Phase C: Intelligence trigger ──

    async def _trigger_intelligence(self, task_id: str) -> None:
        """
        Fire-and-forget: analyze task execution results and generate insights.

        Runs in its own DB session so it never interferes with the
        request/event session that triggered the hook.
        """
        try:
            from backend.database import async_session
            from backend.services.memory.memory_intelligence import (
                get_intelligence_service,
            )

            async with async_session() as db:
                svc = get_intelligence_service()
                await svc.process_task_completion(db, task_id)
                await db.commit()
        except Exception as e:
            logger.debug(
                f"[MEMORY-EVENT] Intelligence trigger failed (non-fatal): {e}"
            )
