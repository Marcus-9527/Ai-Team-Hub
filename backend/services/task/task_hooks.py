"""
task_hooks.py — Task Lifecycle Hook Registry

Provides a lightweight hook system for task lifecycle events.
Hooks are called AFTER state transitions — they are observers, not guards.

This is the **only** extension point for side-effect logic (memory, notifications, analytics)
that needs to react to task lifecycle changes without modifying core execution.

Usage:
    registry = get_task_hook_registry()
    registry.register(MemoryTaskHook())
    # Later, dispatch events:
    await registry.dispatch(TaskLifecycleEvent.TASK_CREATED, TaskHookContext(...))

Constraints:
  ✅ Does not modify MAEOS, Planner, Chat, or TaskExecutor logic
  ✅ Memory enters through this path only
  ✅ Planner accesses Memory only through PlannerContext
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("task.hooks")


# ═══════════════════════════════════════════════════════════════
# Event types
# ═══════════════════════════════════════════════════════════════


class TaskLifecycleEvent(str, Enum):
    """Task lifecycle events that hooks can observe."""

    TASK_CREATED = "TASK_CREATED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    STEP_COMPLETED = "STEP_COMPLETED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    PLAN_APPROVED = "PLAN_APPROVED"
    # Future events can be added here without breaking existing hooks


# ═══════════════════════════════════════════════════════════════
# Hook Context — data passed to each hook handler
# ═══════════════════════════════════════════════════════════════


@dataclass
class TaskHookContext:
    """
    Context data for a task lifecycle event.

    Fields are optional — each event type populates a relevant subset.
    """

    task_id: str = ""
    task_title: str = ""
    task_description: str = ""
    task_status: str = ""
    channel_id: str = ""
    workspace_id: str = ""

    # Step / execution fields
    step_id: str = ""
    step_order: int = 0
    step_objective: str = ""
    step_output: str = ""
    step_error: str = ""

    # Execution fields
    execution_id: str = ""
    execution_outcome: str = ""
    execution_duration_ms: int = 0
    execution_total_tokens: int = 0
    execution_teammate_id: str = ""

    # Plan fields
    plan_id: str = ""
    plan_summary: str = ""

    # Generic metadata
    extra: dict = field(default_factory=dict)

    # Timestamp
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
# Hook interface
# ═══════════════════════════════════════════════════════════════


class TaskHook(ABC):
    """Abstract base for a task lifecycle hook.

    Implement one or more ``on_*`` methods. All methods are optional —
    the base class provides no-op defaults so you only override what you need.
    """

    @property
    def name(self) -> str:
        """Human-readable hook name (used for logging). Defaults to class name."""
        return type(self).__name__

    async def on_task_created(self, ctx: TaskHookContext) -> None:
        """Hook: task was created."""

    async def on_task_completed(self, ctx: TaskHookContext) -> None:
        """Hook: task transitioned to COMPLETED."""

    async def on_task_failed(self, ctx: TaskHookContext) -> None:
        """Hook: task transitioned to FAILED."""

    async def on_step_completed(self, ctx: TaskHookContext) -> None:
        """Hook: a step completed successfully."""

    async def on_execution_completed(self, ctx: TaskHookContext) -> None:
        """Hook: a MAEOS execution completed (includes outcome + cost)."""

    async def on_plan_approved(self, ctx: TaskHookContext) -> None:
        """Hook: a plan review was approved."""

    async def on_event(self, event: TaskLifecycleEvent, ctx: TaskHookContext) -> None:
        """
        Catch-all: called for every event, including those without a dedicated method.
        Default implementation dispatches to dedicated methods.
        Override to intercept all events in one place.
        """
        if event == TaskLifecycleEvent.TASK_CREATED:
            await self.on_task_created(ctx)
        elif event == TaskLifecycleEvent.TASK_COMPLETED:
            await self.on_task_completed(ctx)
        elif event == TaskLifecycleEvent.TASK_FAILED:
            await self.on_task_failed(ctx)
        elif event == TaskLifecycleEvent.STEP_COMPLETED:
            await self.on_step_completed(ctx)
        elif event == TaskLifecycleEvent.EXECUTION_COMPLETED:
            await self.on_execution_completed(ctx)
        elif event == TaskLifecycleEvent.PLAN_APPROVED:
            await self.on_plan_approved(ctx)


# ═══════════════════════════════════════════════════════════════
# Hook Registry
# ═══════════════════════════════════════════════════════════════


class TaskHookRegistry:
    """
    Thread-safe registry that dispatches lifecycle events to all registered hooks.

    Hooks are called concurrently (fire-and-forget within gather).
    Failures are logged but do not propagate — a failing hook never blocks
    the caller or other hooks.

    Usage:
        registry = get_task_hook_registry()
        registry.register(my_hook)
        await registry.dispatch(TaskLifecycleEvent.TASK_CREATED, ctx)
    """

    def __init__(self):
        self._hooks: list[TaskHook] = []

    def register(self, hook: TaskHook) -> None:
        """Register a hook. Idempotent (same instance is not added twice)."""
        if hook not in self._hooks:
            self._hooks.append(hook)
            logger.info(f"[HOOKS] Registered hook: {hook.name}")

    def unregister(self, hook: TaskHook) -> None:
        """Remove a previously registered hook."""
        if hook in self._hooks:
            self._hooks.remove(hook)
            logger.info(f"[HOOKS] Unregistered hook: {hook.name}")

    async def dispatch(self, event: TaskLifecycleEvent, ctx: TaskHookContext) -> None:
        """
        Dispatch an event to all registered hooks.

        Hooks run concurrently. Individual failures are logged and swallowed
        so a broken hook never blocks other hooks or the caller.
        """
        if not self._hooks:
            return

        import asyncio

        results = await asyncio.gather(
            *[hook.on_event(event, ctx) for hook in self._hooks],
            return_exceptions=True,
        )

        for hook, result in zip(self._hooks, results):
            if isinstance(result, Exception):
                logger.error(
                    f"[HOOKS] Hook {hook.name} failed on {event.value}: {result}",
                    exc_info=result,
                )

    @property
    def hook_count(self) -> int:
        return len(self._hooks)


# ── Singleton ──

_registry: Optional[TaskHookRegistry] = None


def get_task_hook_registry() -> TaskHookRegistry:
    """Get the singleton TaskHookRegistry instance."""
    global _registry
    if _registry is None:
        _registry = TaskHookRegistry()
    return _registry


def reset_task_hook_registry() -> None:
    """Reset the singleton (useful for tests)."""
    global _registry
    _registry = None
