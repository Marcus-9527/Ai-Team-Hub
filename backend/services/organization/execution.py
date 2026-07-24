"""OrganizationExecutor — unified execution entry for AI operations.

Routes: OrganizationRuntime → OrganizationExecutor → old services.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class OrganizationExecutor:
    """Execution hub — all AI action execution routes through here."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Chat ──

    async def chat(
        self,
        ctx,
        user_input: str,
        *,
        trigger_id: str = "",
        run_id: str = "",
        teammates: Optional[list[dict]] = None,
        channel_id: str = "",
        shared_attachment_context: Optional[dict] = None,
        force_action=None,
    ) -> AsyncGenerator[str, None]:
        """Chat execution → OrganizationLoop.run()."""
        from backend.services.organization.engine import OrganizationLoop

        loop = OrganizationLoop(self.db)
        async for chunk in loop.run(
            ctx=ctx,
            user_input=user_input,
            trigger_id=trigger_id,
            run_id=run_id,
            teammates=teammates or [],
            channel_id=channel_id,
            shared_attachment_context=shared_attachment_context,
            force_action=force_action,
        ):
            yield chunk

    # ── Task delegate ──

    async def delegate(
        self,
        *,
        trigger_id: str,
        run_id: str,
        task_id: str,
        goal: str,
    ) -> None:
        """DELEGATE action → TeammateSelector → TaskOrchestrator.

        Selects best teammate by identity, stores result in state,
        emits team.member.selected event. Falls through to old
        TaskOrchestrator on no-match.
        """
        from backend.services.organization.registry import OrganizationStateService
        from backend.services.task.task_orchestrator import TaskOrchestrator

        svc = OrganizationStateService(self.db)
        await svc.set_state(
            run_id, "current_action", "main",
            {"action_type": "delegate", "task_id": task_id, "goal": goal, "status": "running"},
            trigger_id=trigger_id,
        )

        # ── Identity-aware selection —─
        selected = None
        experience: list[dict] = []
        try:
            from backend.services.organization.context import OrganizationContextBuilder
            from backend.services.organization.experience import OrganizationExperienceService
            ctx = await OrganizationContextBuilder(self.db).build(run_id)
            if ctx and ctx.members:
                # ── Find similar past experience —─
                exp_svc = OrganizationExperienceService()
                experience = await exp_svc.find_similar_experience(goal, limit=5)

                # Infer required_capabilities from goal keywords (deterministic)
                caps = self._infer_capabilities(goal)
                from backend.services.organization.selector import TeammateSelector
                selector = TeammateSelector(self.db)
                selected = await selector.select(
                    task_description=goal,
                    required_capabilities=caps,
                    members=ctx.members,
                    experience=experience,
                )

                # Emit experience.used event if experience affected selection
                if experience:
                    from backend.services.session.session_hooks import SessionHooks
                    hooks = SessionHooks(self.db)
                    for exp in experience:
                        await hooks.emit_event(
                            trigger_id, event_type="experience.used",
                            payload={
                                "task": goal[:200],
                                "teammate": exp.get("teammate", ""),
                                "matched_memory": exp.get("goal", "")[:200],
                            },
                        )
        except Exception:
            logger.warning("TeammateSelector failed, falling through", exc_info=True)

        if selected:
            await svc.update_state(
                run_id, "selected_teammate", "main",
                {**selected, "task_id": task_id},
                trigger_id=trigger_id,
            )
            # Emit selection event
            from backend.services.session.session_hooks import SessionHooks
            hooks = SessionHooks(self.db)
            await hooks.emit_event(
                trigger_id, event_type="team.member.selected",
                payload={
                    "run_id": run_id,
                    "teammate_id": selected["teammate_id"],
                    "score": str(selected["score"]),
                    "reasons": selected["reasons"],
                },
            )

        try:
            orch = TaskOrchestrator()
            await orch.start_task(self.db, task_id, goal, trigger_id=trigger_id)
            await svc.update_state(
                run_id, "current_action", "main",
                {"action_type": "delegate", "status": "completed"},
                trigger_id=trigger_id,
            )
        except Exception:
            await svc.update_state(
                run_id, "current_action", "main",
                {"action_type": "delegate", "status": "failed"},
                trigger_id=trigger_id,
            )
            raise

    @staticmethod
    def _infer_capabilities(goal: str) -> list[str]:
        """Simple keyword→capability mapping, aligned with DEFAULT_ROLE_CAPABILITIES."""
        g = goal.lower()
        caps: list[str] = []
        for kw, capability in (
            ("code", "code_execution"), ("python", "code_execution"), ("javascript", "code_execution"),
            ("write", "code_execution"), ("create", "code_execution"),
            ("edit", "file_edit"), ("file", "file_edit"),
            ("git", "git"),
            ("review", "review"), ("audit", "review"),
            ("diff", "git_diff"),
            ("test", "test_runner"), ("qa", "test_runner"),
            ("deploy", "deploy"), ("release", "deploy"),
        ):
            if kw in g and capability not in caps:
                caps.append(capability)
        return caps

    # ── Task execute ──

    async def execute(
        self,
        *,
        db_session: AsyncSession,
        task,
    ) -> None:
        """EXECUTE action → TaskExecutor directly.

        Stateless call — no SessionEvents (no trigger context).
        Lifecycle events are handled by OrganizationActionRouter.
        """
        from backend.services.task.task_executor import TaskExecutor
        from backend.services.runtime.executor import ExecutionRuntime

        runtime = ExecutionRuntime(max_workers=4)
        exec_ = TaskExecutor(runtime=runtime)
        await exec_.execute_task(db_session, task)

    # ── Tool call (event-only) ──

    async def tool(self, **kwargs) -> None:
        """TOOL_CALL — event-only, no execution needed."""

    # ── Complete (event-only) ──

    async def complete(self, **kwargs) -> None:
        """COMPLETE — event-only, no execution needed."""

    # ── Task progress ──

    async def get_progress(self, task_id: str) -> dict:
        """Execution progress for a task."""
        from backend.services.task.task_executor import TaskExecutor

        exec_ = TaskExecutor()
        return await exec_.get_task_progress(self.db, task_id)

    # ── Full task orchestration ──

    async def task(
        self,
        task_id: str,
        goal: str,
        *,
        channel_id: str = "",
        workspace_id: str = "",
        title: str = "",
    ) -> None:
        """Full task orchestration: trigger → run → delegate."""
        from backend.services.session.session_hooks import SessionHooks
        from backend.models.session import TriggerType
        from backend.services.task.task_manager import TaskManager
        from backend.services.organization import OrganizationRunService

        hooks = SessionHooks(self.db)
        trigger = await hooks.open_trigger(
            channel_id=channel_id,
            user_msg_id="",
            workspace_id=workspace_id,
            trigger_type=TriggerType.TASK,
            task_id=task_id,
        )

        # Link or create OrganizationRun
        mgr = TaskManager()
        task_obj = await mgr.get_task(self.db, task_id)
        run_id = task_obj.run_id if task_obj else ""
        if not run_id:
            org_run = await OrganizationRunService.create_run(
                self.db,
                run_type="task",
                source_id=task_id,
                channel_id=channel_id,
                workspace_id=workspace_id,
                title=title or f"Task: {(task_obj.title if task_obj else goal)[:100]}",
            )
            run_id = org_run.id
        trigger.run_id = run_id
        await hooks.emit_event(trigger.id, "run.created", run_id)

        await self.delegate(
            trigger_id=trigger.id,
            run_id=run_id,
            task_id=task_id,
            goal=goal,
        )
