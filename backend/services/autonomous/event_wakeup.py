"""autonomous/event_wakeup.py — Event Wakeup Bus (Phase 13.3)

事件触发 teammate 唤醒机制。

Events (Phase 13.3 spec):
  TASK_CREATED       — 新任务创建，触发 claim 竞争
  TASK_FAILED        — 任务失败，触发其他 teammate 分析/重试
  REVIEW_REJECTED    — Review 驳回，触发修复
  BRAIN_UPDATED      — Brain 片段更新，触发 teammate 重新读取

Design:
  - 事件总线模式 — fire → 订阅者收到通知
  - 每个 teammate 可注册对不同事件的兴趣
  - 事件触发后调用 TeammateRunner 或 TaskOrchestrator
  - 不上新 scheduler/FSM — 复用 asyncio.create_task 做 fire-and-forget

Integration:
  - task_orchestrator.py — 在 review 驳回时 fire REVIEW_REJECTED
  - routes/tasks.py — 在 task 创建时 fire TASK_CREATED
  - BrainTaskHook — 在 brain 更新时 fire BRAIN_UPDATED
  - TASK_FAILED — 从 task lifecycle 事件 fire
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("autonomous.event_wakeup")


class WakeupEvent(Enum):
    TASK_CREATED = "task_created"
    TASK_FAILED = "task_failed"
    REVIEW_REJECTED = "review_rejected"
    BRAIN_UPDATED = "brain_updated"
    MESSAGE_EVENT = "message_event"  # Phase 19: new message in channel


@dataclass
class WakeupPayload:
    """Data carried with a wakeup event."""
    event_type: str
    task_id: str = ""
    teammate_id: str = ""           # affected teammate (if any)
    channel_id: str = ""
    reason: str = ""                 # additional context
    data: dict = field(default_factory=dict)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "task_id": self.task_id,
            "teammate_id": self.teammate_id,
            "channel_id": self.channel_id,
            "reason": self.reason[:200] if self.reason else "",
            "data": self.data,
            "timestamp": self.timestamp or time.time(),
        }


# ── Event Actions ──

# Each handler is an async callable that takes a WakeupPayload
EventHandler = Callable[[WakeupPayload], None]  # None = fire-and-forget


# ── Event Wakeup Bus ──

class EventWakeupBus:
    """Pub/sub event bus for teammate wakeup.

    Usage:
        bus = get_event_wakeup_bus()

        # Subscribe a specific teammate to an event
        bus.subscribe(WakeupEvent.TASK_CREATED, handler_fn)

        # Fire an event → all subscribers notified
        bus.fire(WakeupEvent.TASK_CREATED, WakeupPayload(task_id="..."))

    Each handler is fire-and-forget (via asyncio.ensure_future).
    """

    def __init__(self):
        self._subscribers: dict[WakeupEvent, list[EventHandler]] = {
            e: [] for e in WakeupEvent
        }
        self._history: list[WakeupPayload] = []
        self._max_history = 200

    # ── Subscribe / Unsubscribe ──

    def subscribe(self, event: WakeupEvent, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        if handler not in self._subscribers[event]:
            self._subscribers[event].append(handler)
            logger.debug("[Wakeup] subscriber registered for %s (%d total)",
                         event.value, len(self._subscribers[event]))

    def unsubscribe(self, event: WakeupEvent, handler: EventHandler) -> None:
        """Remove a handler for an event type."""
        if handler in self._subscribers[event]:
            self._subscribers[event].remove(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Remove a handler from all event types."""
        for event in WakeupEvent:
            self.unsubscribe(event, handler)

    # ── Fire Event ──

    def fire(self, event: WakeupEvent, payload: WakeupPayload) -> None:
        """Fire an event — all subscribers get called as fire-and-forget tasks.

        This is synchronous (returns immediately). Subscribers run in background.
        """
        payload.timestamp = payload.timestamp or time.time()

        # Record history
        self._history.append(payload)
        if len(self._history) > self._max_history:
            self._history = self._history[-100:]

        subscribers = list(self._subscribers.get(event, []))
        if not subscribers:
            logger.debug("[Wakeup] event %s fired — no subscribers", event.value)
            return

        for handler in subscribers:
            try:
                asyncio.ensure_future(self._call_handler(handler, payload))
            except Exception as e:
                logger.warning("[Wakeup] handler dispatch failed: %s", e)

        logger.info("[Wakeup] %s fired → %d handlers", event.value, len(subscribers))

    async def _call_handler(self, handler: EventHandler, payload: WakeupPayload) -> None:
        """Safely call a handler handler."""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(payload)
            else:
                handler(payload)
        except Exception as e:
            logger.warning("[Wakeup] handler failed on %s: %s", payload.event_type, e)

    # ── Query ──

    def count_subscribers(self, event: Optional[WakeupEvent] = None) -> int:
        """Return subscriber count. If event is None, return total across all."""
        if event:
            return len(self._subscribers.get(event, []))
        return sum(len(subs) for subs in self._subscribers.values())

    def get_history(
        self,
        event_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get recent wakeup history, optionally filtered by event type."""
        history = self._history
        if event_type:
            history = [p for p in history if p.event_type == event_type]
        return [p.to_dict() for p in history[-limit:]]

    def reset(self) -> None:
        """Clear all subscribers and history (for tests)."""
        self._subscribers = {e: [] for e in WakeupEvent}
        self._history = []

    # ── Built-in Handlers ──

    @staticmethod
    def _on_task_created(payload: WakeupPayload) -> None:
        """Handler: TASK_CREATED → wake up available teammates.

        The handler triggers Task Claim Protocol for the new task.
        """
        from backend.services.autonomous.task_claim import get_claim_manager
        from backend.services.autonomous.teammate_state import get_state_manager
        from backend.database import async_session
        from sqlalchemy import select
        from backend.models import Teammate

        async def _wake():
            task_id = payload.task_id
            if not task_id:
                return

            # Phase 19: check event-triggered automation rules
            asyncio.ensure_future(_trigger_automation_rules(
                "task_created", channel_id=payload.channel_id, task_id=task_id))

            # Get all available teammates
            state_manager = get_state_manager()
            available = await state_manager.list_available()

            # Map state → teammate dicts for claim
            async with async_session() as db:
                from sqlalchemy import select as _select
                from backend.models import Teammate
                res = await db.execute(_select(Teammate))
                all_tms = {}
                for t in res.scalars().all():
                    # Build minimal dict (Teammate ORM has no to_dict)
                    all_tms[t.id] = {
                        "id": t.id,
                        "name": t.name,
                        "role": t.role or "",
                        "system_prompt": t.system_prompt or "",
                    }

            claim_manager = get_claim_manager()
            claimed = False

            for tm_state in available:
                tm_id = tm_state.teammate_id
                tm = all_tms.get(tm_id)
                if not tm:
                    continue
                # Attempt to claim
                ok, msg = await claim_manager.claim(
                    task_id=task_id,
                    teammate_id=tm_id,
                    teammate_name=tm.get("name", ""),
                    reason=f"Auto-wakeup from TASK_CREATED: {payload.reason[:100]}",
                )
                if ok:
                    claimed = True
                    # Phase 19: after claim, start real execution via TaskOrchestrator
                    from backend.database import async_session as _exec_db
                    from backend.services.task.task_orchestrator import TaskOrchestrator
                    from backend.services.runtime.executor import ExecutionRuntime
                    from sqlalchemy import select as _tm_select
                    from backend.models import TaskModel

                    async def _execute():
                        try:
                            async with _exec_db() as db:
                                res = await db.execute(_tm_select(TaskModel).where(TaskModel.id == task_id))
                                t = res.scalar_one_or_none()
                                if t:
                                    rt = ExecutionRuntime(max_workers=4)
                                    orch = TaskOrchestrator(runtime=rt)
                                    await orch.start_task(db, t.id, t.intent or t.title)
                                    await db.commit()
                                    logger.info("[Wakeup] Task %s executing after claim", task_id[:8])
                        except Exception as ex:
                            logger.warning("[Wakeup] execution after claim failed: %s", ex)

                    asyncio.ensure_future(_execute())
                    break

            if not claimed:
                logger.info("[Wakeup] No teammate claimed task %s", task_id[:8])

        asyncio.ensure_future(_wake())

    @staticmethod
    def _on_task_failed(payload: WakeupPayload) -> None:
        """Handler: TASK_FAILED → notify available teammates to analyze.

        Don't auto-claim; wait for human or analyst teammate to decide.
        Stores a memory record so the team can triage.
        """
        from backend.services.memory.memory_service import get_memory_service
        from backend.services.memory.memory_types import MemoryItem, MemoryType

        async def _notify():
            # Phase 19: check event-triggered automation rules
            asyncio.ensure_future(_trigger_automation_rules(
                "task_failed", channel_id=payload.channel_id, task_id=payload.task_id))
            try:
                svc = get_memory_service()
                await svc.store(MemoryItem(
                    memory_type=MemoryType.EVENT,
                    content=("[TASK_FAILED] Task %s failed. Reason: %s"
                             % (payload.task_id[:12], payload.reason[:200])),
                    source_id=payload.task_id,
                    relevance_score=0.6,
                    metadata={
                        "event": "TASK_FAILED",
                        "task_id": payload.task_id,
                        "reason": payload.reason[:200],
                        "scope": "alert",
                    },
                ))
            except Exception as e:
                logger.debug("[Wakeup] failed to store TASK_FAILED record: %s", e)

        asyncio.ensure_future(_notify())

    @staticmethod
    def _on_review_rejected(payload: WakeupPayload) -> None:
        """Handler: REVIEW_REJECTED → notify the original engineer teammate.

        The engineer state is already set to ACTIVE/IDLE after finishing the task.
        No re-claim needed — the review relay already creates a fix task.
        """
        from backend.services.memory.memory_service import get_memory_service
        from backend.services.memory.memory_types import MemoryItem, MemoryType

        async def _notify():
            # Phase 19: check event-triggered automation rules
            asyncio.ensure_future(_trigger_automation_rules(
                "review_rejected", channel_id=payload.channel_id, task_id=payload.task_id))
            try:
                svc = get_memory_service()
                await svc.store(MemoryItem(
                    memory_type=MemoryType.EVENT,
                    content=("[REVIEW_REJECTED] Task %s rejected. Comments: %s"
                             % (payload.task_id[:12], payload.reason[:200])),
                    source_id=payload.task_id,
                    relevance_score=0.7,
                    metadata={
                        "event": "REVIEW_REJECTED",
                        "task_id": payload.task_id,
                        "teammate_id": payload.teammate_id,
                        "reason": payload.reason[:200],
                        "scope": "alert",
                    },
                ))
            except Exception as e:
                logger.debug("[Wakeup] failed to store REVIEW_REJECTED: %s", e)

        asyncio.ensure_future(_notify())

    @staticmethod
    def _on_brain_updated(payload: WakeupPayload) -> None:
        """Handler: BRAIN_UPDATED → refresh brain loader cache for affected teammate.

        No-op for now (brain_loader is stateless). In future, could
        invalidate a per-teammate prompt cache.
        """
        logger.debug("[Wakeup] BRAIN_UPDATED for teammate %s — no cache invalidation needed",
                     payload.teammate_id[:8] if payload.teammate_id else "?")


# ═══════════════════════════════════════════════════════════════
# Phase 19: Automation-event bridge — check event-triggered rules
# ═══════════════════════════════════════════════════════════════

async def _trigger_automation_rules(event_type: str, channel_id: str = "", task_id: str = "") -> None:
    """Check active automation rules with matching trigger_event and create tasks."""
    try:
        from backend.database import async_session
        from sqlalchemy import select
        from backend.models import AutomationRuleModel
        from backend.services.task.task_manager import TaskManager
        from backend.services.task.task_orchestrator import TaskOrchestrator
        from backend.services.runtime.executor import ExecutionRuntime

        async with async_session() as db:
            res = await db.execute(
                select(AutomationRuleModel).where(
                    AutomationRuleModel.is_active == "1",
                    AutomationRuleModel.trigger_event == event_type,
                )
            )
            rules = res.scalars().all()
            for rule in rules:
                mgr = TaskManager()
                task = await mgr.create_task(
                    db,
                    title=rule.task_title,
                    description=rule.description,
                    channel_id=channel_id or rule.channel_id or None,
                    intent=rule.task_intent or rule.task_title,
                )
                await db.commit()
                runtime = ExecutionRuntime(max_workers=4)
                orch = TaskOrchestrator(runtime=runtime)
                asyncio.create_task(orch.start_task(db, task.id, rule.task_intent or rule.task_title))
                logger.info("[AutoEvent] rule '%s' triggered → task %s", rule.name, task.id[:8])
    except Exception as e:
        logger.debug("[AutoEvent] check failed (non-fatal): %s", e)


# ── Register Built-in Handlers ──

def register_default_handlers(bus: Optional[EventWakeupBus] = None) -> EventWakeupBus:
    """Register the built-in event handlers on the bus."""
    b = bus or get_event_wakeup_bus()
    b.subscribe(WakeupEvent.TASK_CREATED, EventWakeupBus._on_task_created)
    b.subscribe(WakeupEvent.TASK_FAILED, EventWakeupBus._on_task_failed)
    b.subscribe(WakeupEvent.REVIEW_REJECTED, EventWakeupBus._on_review_rejected)
    b.subscribe(WakeupEvent.BRAIN_UPDATED, EventWakeupBus._on_brain_updated)
    return b


# ── Singleton ──

_wakeup_bus: Optional[EventWakeupBus] = None


def get_event_wakeup_bus() -> EventWakeupBus:
    global _wakeup_bus
    if _wakeup_bus is None:
        _wakeup_bus = register_default_handlers(EventWakeupBus())
    return _wakeup_bus
