"""task/artifact_hook.py — Save task output as artifact on completion."""
import logging

from backend.services.task.task_hooks import TaskHook, TaskHookContext
from backend.services.artifact import get_artifact_service

logger = logging.getLogger("task.artifact_hook")


class ArtifactTaskHook(TaskHook):
    """Best-effort artifact on task completion. Follows Memory/Brain/ChannelNotify pattern."""

    async def on_task_completed(self, ctx: TaskHookContext) -> None:
        svc = get_artifact_service()
        try:
            content = (
                f"[Task Completed] {ctx.task_title}\n\n"
                f"Description: {ctx.task_description}\n"
                f"Task ID: {ctx.task_id}\n"
                f"Channel: {ctx.channel_id}\n"
                f"Workspace: {ctx.workspace_id}"
            )
            svc.create_artifact(
                content=content,
                name=f"task-{ctx.task_id[:12]}.txt",
                type="text",
                task_id=ctx.task_id,
                metadata={"source": "artifact_hook"},
            )
        except Exception:
            logger.warning("ArtifactTaskHook failed for task %s", ctx.task_id[:8], exc_info=True)
