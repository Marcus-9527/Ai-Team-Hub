"""OrganizationActionRuntime — action lifecycle hub.

Every AI action passes through here for lifecycle management.
Actual dispatch is done by OrganizationActionRouter.

    OrganizationRuntime
        │
        ▼
    OrganizationActionRuntime   ← lifecycle + action.created
        │
        ▼
    OrganizationActionRouter    ← started/completed/failed + dispatch
        │
        ▼
    OrganizationExecutor → old services

Phase 2.1: no action_type switching in this file.
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.organization.actions import OrganizationAction
from backend.services.organization.router import OrganizationActionRouter


class OrganizationActionRuntime:
    """Central action lifecycle hub.

    Emits action.created, delegates actual dispatch to Router.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.router = OrganizationActionRouter(db)

    # ── RESPOND (streaming) ──

    async def respond(
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
        """RESPOND action with lifecycle.

        Emits action.created, then delegates to Router for started/completed.
        """
        await self._emit_created(trigger_id, run_id, "respond")
        async for chunk in self.router.route_stream(
            OrganizationAction.RESPOND,
            ctx=ctx, user_input=user_input,
            trigger_id=trigger_id, run_id=run_id,
            teammates=teammates, channel_id=channel_id,
            shared_attachment_context=shared_attachment_context,
            force_action=force_action,
        ):
            yield chunk

    # ── Generic action dispatch (DELEGATE, EXECUTE, COMPLETE, TOOL_CALL) ──

    async def execute_action(
        self,
        action_type: OrganizationAction,
        *,
        trigger_id: str = "",
        run_id: str = "",
        **kwargs,
    ) -> None:
        """Route non-streaming action through Router.

        Emits action.created, then Router handles started/completed/failed.
        """
        await self._emit_created(trigger_id, run_id, action_type.value)
        await self.router.route(
            action_type, trigger_id=trigger_id, run_id=run_id, **kwargs,
        )

    # ── helpers ──

    async def _emit_created(
        self,
        trigger_id: str,
        run_id: str,
        action_type: str,
    ) -> None:
        from backend.services.session.session_hooks import SessionHooks
        hooks = SessionHooks(self.db)
        await hooks.emit_event(
            trigger_id, event_type="action.created",
            payload={"run_id": run_id, "action_type": action_type},
        )

    async def emit_action_event(
        self,
        phase: str,
        *,
        trigger_id: str = "",
        run_id: str = "",
        action_type: str = "",
        extra: dict | None = None,
    ) -> None:
        """Emit a single action lifecycle event (created/started/completed/failed).

        Public helper so TaskActionAdapter can emit events with correct timing
        without going through the full execute_action → route dispatch.
        """
        from backend.services.session.session_hooks import SessionHooks
        payload = {"run_id": run_id, "action_type": action_type}
        if extra:
            payload.update(extra)
        hooks = SessionHooks(self.db)
        await hooks.emit_event(
            trigger_id, event_type=f"action.{phase}", payload=payload,
        )
