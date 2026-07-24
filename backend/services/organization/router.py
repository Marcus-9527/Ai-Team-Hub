"""OrganizationActionRouter — unified action dispatch + lifecycle events.

The single place where OrganizationAction → executor mapping lives.
Emits action.started / action.completed / action.failed.

    OrganizationActionRuntime
        │
        ▼
    OrganizationActionRouter   ← routes action_type → executor + emission
        │
        ▼
    OrganizationExecutor → old services
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.organization.actions import OrganizationAction
from backend.services.organization.execution import OrganizationExecutor


class OrganizationActionRouter:
    """Action dispatch hub — maps action_type to executor + emits lifecycle events."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.executor = OrganizationExecutor(db)

    # ── RESPOND (streaming) ──

    async def route_stream(
        self,
        action_type: OrganizationAction,
        *,
        trigger_id: str = "",
        run_id: str = "",
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """Route a streaming action (RESPOND) with action.started/completed/failed."""
        # Normalize: dispatch_respond passes user_message, action_runtime passes user_input
        user_msg = kwargs.pop("user_message", None)
        if user_msg is not None and "user_input" not in kwargs:
            kwargs["user_input"] = user_msg

        await self._emit(trigger_id, run_id, action_type, "started")
        try:
            if action_type == OrganizationAction.RESPOND:
                async for chunk in self.executor.chat(**kwargs):
                    yield chunk
            else:
                raise ValueError(f"route_stream only supports RESPOND, got {action_type}")

            await self._emit(trigger_id, run_id, action_type, "completed")
        except Exception as e:
            await self._emit(trigger_id, run_id, action_type, "failed",
                             extra={"error": str(e)})
            raise

    # ── Non-streaming actions (DELEGATE, EXECUTE, TOOL_CALL, COMPLETE) ──

    async def route(
        self,
        action_type: OrganizationAction,
        *,
        trigger_id: str = "",
        run_id: str = "",
        **kwargs,
    ) -> None:
        """Route a non-streaming action with action.started/completed/failed."""
        await self._emit(trigger_id, run_id, action_type, "started")
        try:
            if action_type == OrganizationAction.DELEGATE:
                await self.executor.delegate(trigger_id=trigger_id, run_id=run_id, **kwargs)
            elif action_type == OrganizationAction.PLAN:
                pass  # event-only, orchestrated by TaskActionAdapter
            elif action_type == OrganizationAction.REVIEW:
                pass  # event-only, orchestrated by TaskActionAdapter
            elif action_type == OrganizationAction.EXECUTE:
                await self.executor.execute(
                    db_session=kwargs["db_session"], task=kwargs["task"],
                )
            elif action_type == OrganizationAction.VERIFY:
                pass  # event-only, orchestrated by TaskActionAdapter
            elif action_type == OrganizationAction.TOOL_CALL:
                await self.executor.tool(**kwargs)
            elif action_type == OrganizationAction.COMPLETE:
                await self.executor.complete(**kwargs)
            else:
                raise ValueError(f"Unknown action type: {action_type}")

            await self._emit(trigger_id, run_id, action_type, "completed")
        except Exception as e:
            await self._emit(trigger_id, run_id, action_type, "failed",
                             extra={"error": str(e)})
            raise

    # ── Event helper ──

    async def _emit(
        self,
        trigger_id: str,
        run_id: str,
        action_type: OrganizationAction,
        phase: str,
        extra: Optional[dict] = None,
    ) -> None:
        from backend.services.session.session_hooks import SessionHooks
        hooks = SessionHooks(self.db)
        payload: dict = {"run_id": run_id, "action_type": action_type.value}
        if extra:
            payload.update(extra)
        await hooks.emit_event(trigger_id, event_type=f"action.{phase}",
                               payload=payload)
