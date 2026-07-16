"""brain/reflection.py — Reflection System (Phase 12.3)

任务完成后自动生成 lesson/skill update/behavior suggestion 写入 brain fragments。

触发点：
  - task completed → lesson (what worked)
  - review rejected → behavior suggestion (what to improve)
  - task failed → lesson (what went wrong, how to avoid)

Ponytail: 基于结构化上下文模板生成，不用 LLM（贵、不稳定）。
核心人格（identity/personality/principles）的修改走 pending proposal。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.services.brain.fragment_store import (
    BrainFragmentStore,
    get_brain_fragment_store,
    BrainFragment,
    BrainFragmentType,
)
from backend.services.task.task_hooks import TaskHookContext

logger = logging.getLogger("brain.reflection")

# ── Templates ──

_TEMPLATE_LESSON = """\
Task: {task_title}

Observation: {observation}

Root Cause: {root_cause}

Lesson: {lesson}

Action: {action}
"""

_TEMPLATE_BEHAVIOR = """\
Scenario: {scenario}

Current behavior: {current_behavior}

Suggested change: {suggested_change}

Reason: {reason}
"""


class ReflectionService:
    """Generate brain fragments from task lifecycle events.

    Reuses BrainFragmentStore for persistence.
    """

    def __init__(self, store: Optional[BrainFragmentStore] = None):
        self._store = store or get_brain_fragment_store()

    async def on_task_completed(self, ctx: TaskHookContext) -> None:
        """Task completed successfully → generate a 'what worked' lesson."""
        teammate_id = ctx.execution_teammate_id or ctx.extra.get("teammate_id", "")
        if not teammate_id:
            return
        content = _TEMPLATE_LESSON.format(
            task_title=ctx.task_title or "unknown",
            observation=f"Completed with status {ctx.task_status}",
            root_cause="N/A — task succeeded",
            lesson=f"The approach for \"{ctx.task_title[:60]}\" was effective.",
            action="Continue using similar patterns for comparable tasks.",
        )
        frag = BrainFragment(
            teammate_id=teammate_id,
            workspace_id=ctx.workspace_id,
            fragment_type=BrainFragmentType.LESSONS,
            content=content.strip(),
            confidence=0.6,
            source="reflection",
        )
        await self._store.store(frag)
        logger.info("[Reflection] lesson stored for task %s → teammate %s (ws %s)", ctx.task_id[:8], teammate_id[:8], ctx.workspace_id[:8] if ctx.workspace_id else "-")

    async def on_review_rejected(self, task_id: str, teammate_id: str, comments: str, round_no: int, workspace_id: str = "") -> None:
        """Review rejected → generate behavior suggestion."""
        if not teammate_id or not comments:
            return
        content = _TEMPLATE_BEHAVIOR.format(
            scenario=f"Review round {round_no} rejected task {task_id[:8]}",
            current_behavior="The delivery did not meet review standards.",
            suggested_change="Address the reviewer's feedback before delivering.",
            reason=f"Reviewer comments: {comments[:300]}",
        )
        frag = BrainFragment(
            teammate_id=teammate_id,
            workspace_id=workspace_id,
            fragment_type=BrainFragmentType.BEHAVIOR_SUGGESTION,
            content=content.strip(),
            confidence=0.5,
            source="reflection",
        )
        await self._store.store(frag)
        logger.info("[Reflection] behavior suggestion stored for teammate %s (round %d)", teammate_id[:8], round_no)

    async def on_task_failed(self, ctx: TaskHookContext) -> None:
        """Task failed → generate a 'what went wrong' lesson."""
        teammate_id = ctx.execution_teammate_id or ctx.extra.get("teammate_id", "")
        if not teammate_id:
            return
        error_info = ctx.step_error or ctx.task_status or "Unknown error"
        content = _TEMPLATE_LESSON.format(
            task_title=ctx.task_title or "unknown",
            observation=f"Failed with: {error_info}",
            root_cause=error_info[:200],
            lesson=f"Task \"{ctx.task_title[:60]}\" failed. Root cause identified.",
            action=f"Avoid repeating: {error_info[:200]}",
        )
        frag = BrainFragment(
            teammate_id=teammate_id,
            workspace_id=ctx.workspace_id,
            fragment_type=BrainFragmentType.LESSONS,
            content=content.strip(),
            confidence=0.7,
            source="reflection",
        )
        await self._store.store(frag)
        logger.info("[Reflection] failure lesson stored for task %s → teammate %s (ws %s)", ctx.task_id[:8], teammate_id[:8], ctx.workspace_id[:8] if ctx.workspace_id else "-")

    async def on_channel_summary(
        self, channel_id: str, task_title: str, task_status: str, workspace_id: str = "",
    ) -> None:
        """Append a task outcome to the channel's running summary fragment.

        Min version: no vector store, just keep a rolling text summary per
        (channel, workspace). Each completed/failed task appends one line.
        """
        if not channel_id:
            return
        store = self._store
        # teammate_id slot reused as channel_id for channel-scoped fragments
        frag_type = BrainFragmentType.CHANNEL_SUMMARY
        latest = await store.get_latest(channel_id, frag_type.value, workspace_id)
        existing_lines = (latest.content or "").strip().splitlines() if latest else []
        # keep last 20 lines
        existing_lines = existing_lines[-20:]
        new_line = f"- [{task_status}] {task_title or 'untitled'} @ {datetime.now(timezone.utc).strftime('%m-%d %H:%M')}"
        existing_lines.append(new_line)
        frag = BrainFragment(
            teammate_id=channel_id,  # slot reuse: channel-scoped
            workspace_id=workspace_id,
            fragment_type=frag_type,
            content="\n".join(existing_lines),
            confidence=0.9,
            source="channel_summary",
        )
        await store.store(frag)
        logger.info("[Reflection] channel summary updated for %s (ws %s)", channel_id[:8], workspace_id[:8] if workspace_id else "-")


# Singleton
_svc: Optional[ReflectionService] = None


def get_reflection_service() -> ReflectionService:
    global _svc
    if _svc is None:
        _svc = ReflectionService()
    return _svc
