"""Session 生命周期钩子 + Event Stream。

核心是 open_trigger() + start_turn()/close_turn()，与 MemoryTaskHook 同级
但挂在 Ai 生命周期上。

每个 turn 方法自动产生 SessionEvent，形成可查询的事件链。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import (
    SessionTrigger, SessionTurn, SessionEvent,
    TriggerType, TurnAction,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionHooks:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Trigger ──

    async def open_trigger(
        self,
        *,
        channel_id: str,
        user_msg_id: str,
        workspace_id: Optional[str] = None,
        trigger_type: TriggerType = TriggerType.CHAT,
        task_id: Optional[str] = None,
        teammate_id: Optional[str] = None,
    ) -> SessionTrigger:
        trigger = SessionTrigger(
            trigger_type=trigger_type.value,
            channel_id=channel_id,
            user_msg_id=user_msg_id,
            workspace_id=workspace_id,
            task_id=task_id,
            teammate_id=teammate_id,
            trigger_time=_now(),
        )
        self.db.add(trigger)
        await self.db.flush()
        return trigger

    async def close_trigger(
        self,
        trigger_id: str,
        *,
        status: str = "completed",
    ) -> None:
        trigger = await self.db.get(SessionTrigger, trigger_id)
        if trigger is None:
            return
        trigger.status = status
        trigger.ended_at = _now()
        await self.db.flush()
        await self.emit_event(
            trigger_id, event_type="trigger.close",
            payload={"status": status},
        )

    # ── Event Stream ──

    async def emit_event(
        self,
        trigger_id: str,
        *,
        turn_id: Optional[str] = None,
        event_type: str,
        payload: Optional[dict] = None,
    ) -> SessionEvent:
        """写入一条 SessionEvent 到事件流。"""
        event = SessionEvent(
            trigger_id=trigger_id,
            turn_id=turn_id,
            event_type=event_type,
            payload=payload or {},
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def events_for_trigger(
        self, trigger_id: str, *, limit: int = 100,
    ) -> list[SessionEvent]:
        """按时间序获取 trigger 下所有事件。"""
        from sqlalchemy import select
        result = await self.db.execute(
            select(SessionEvent)
            .where(SessionEvent.trigger_id == trigger_id)
            .order_by(SessionEvent.timestamp)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def events_for_turn(self, turn_id: str) -> list[SessionEvent]:
        """获取指定 turn 下所有事件。"""
        from sqlalchemy import select
        result = await self.db.execute(
            select(SessionEvent)
            .where(SessionEvent.turn_id == turn_id)
            .order_by(SessionEvent.timestamp)
        )
        return list(result.scalars().all())

    # ── Turn ──

    async def start_turn(self, trigger_id: str, *, teammate_id: str) -> SessionTurn:
        turn = SessionTurn(
            trigger_id=trigger_id,
            teammate_id=teammate_id,
            action=TurnAction.RESPONDED.value,
            start_time=_now(),
        )
        self.db.add(turn)
        await self.db.flush()

        await self.emit_event(
            trigger_id, turn_id=turn.id,
            event_type="turn.start",
            payload={"teammate_id": teammate_id},
        )
        return turn

    async def close_turn(
        self,
        turn_id: str,
        *,
        action: TurnAction,
        response_msg_id: Optional[str] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
    ) -> None:
        turn = await self.db.get(SessionTurn, turn_id)
        if turn is None:
            return
        turn.action = action.value
        turn.response_msg_id = response_msg_id
        turn.tokens_in = tokens_in
        turn.tokens_out = tokens_out
        turn.end_time = _now()
        await self.db.flush()

        await self.emit_event(
            turn.trigger_id, turn_id=turn_id,
            event_type="turn.close",
            payload={
                "action": action.value,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        )

    async def record_failed_turn(
        self,
        trigger_id: str,
        *,
        teammate_id: str,
        failure: str,
        execution_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> SessionTurn:
        turn = SessionTurn(
            trigger_id=trigger_id,
            teammate_id=teammate_id,
            action=TurnAction.RESPONDED.value,
            failure=failure,
            execution_id=execution_id,
            metadata_json=metadata,
            start_time=_now(),
            end_time=_now(),
        )
        self.db.add(turn)
        await self.db.flush()

        await self.emit_event(
            trigger_id, turn_id=turn.id,
            event_type="turn.fail",
            payload={"failure": failure},
        )
        return turn

    async def record_turn(
        self,
        trigger_id: str,
        *,
        teammate_id: str,
        action: TurnAction = TurnAction.RESPONDED,
        response_msg_id: Optional[str] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
    ) -> SessionTurn:
        """一步完成 start + close，用于 background task 或已完成的事件。"""
        turn = SessionTurn(
            trigger_id=trigger_id,
            teammate_id=teammate_id,
            action=action.value,
            response_msg_id=response_msg_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            start_time=_now(),
            end_time=_now(),
        )
        self.db.add(turn)
        await self.db.flush()

        await self.emit_event(
            trigger_id, turn_id=turn.id,
            event_type="turn.record",
            payload={
                "action": action.value,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        )
        return turn

    # ── Query ──

    async def turns_for_trigger(self, trigger_id: str) -> list[SessionTurn]:
        from sqlalchemy import select

        result = await self.db.execute(
            select(SessionTurn).where(SessionTurn.trigger_id == trigger_id)
        )
        return list(result.scalars().all())
