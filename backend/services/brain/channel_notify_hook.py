"""brain/channel_notify_hook.py — ChannelNotifyHook (Phase 20)

Publishes task completion/failure results to the task's channel as a
system message. Registered in HookRegistry alongside MemoryTaskHook
and BrainTaskHook.

Ponytail: fire-and-forget DB write, no new engine/scheduler/FSM.
If the task has no channel_id, the hook is a no-op.
"""

from __future__ import annotations

import json
import logging

from backend.services.task.task_hooks import (
    TaskHook,
    TaskHookContext,
    TaskLifecycleEvent,
)

logger = logging.getLogger("brain.channel_notify")


class ChannelNotifyHook(TaskHook):
    """Sends task status notifications to the channel.

    - TASK_COMPLETED → system message with summary
    - TASK_FAILED    → system message with error
    """

    async def on_task_completed(self, ctx: TaskHookContext) -> None:
        if not ctx.channel_id:
            return
        await self._post_system_message(
            channel_id=ctx.channel_id,
            content=(
                f"✅ **Task Completed**: {ctx.task_title}\n"
                f"Status: {ctx.task_status}"
            ),
        )

    async def on_task_failed(self, ctx: TaskHookContext) -> None:
        if not ctx.channel_id:
            return
        reason = ctx.step_error or ctx.extra.get("reason", ctx.task_status)
        await self._post_system_message(
            channel_id=ctx.channel_id,
            content=(
                f"❌ **Task Failed**: {ctx.task_title}\n"
                f"Reason: {reason}"
            ),
        )

    # ── Internal ──────────────────────────────────────────────

    async def _post_system_message(self, channel_id: str, content: str) -> None:
        """Write a system message to the channel (fire-and-forget, best-effort)."""
        try:
            from backend.database import async_session
            from backend.models import Message
            async with async_session() as db:
                msg = Message(
                    channel_id=channel_id,
                    role="system",
                    author_name="System",
                    content=content,
                )
                db.add(msg)
                await db.commit()
            logger.info("[ChannelNotify] system message sent to channel %s", channel_id[:8])
        except Exception as e:
            logger.debug("[ChannelNotify] failed to post to channel %s: %s", channel_id[:8], e)
