"""autonomous/teammate_state.py — Teammate Runtime State (Phase 13.4)

记录每个 teammate 的运行状态，是 Cede Protocol 和 Task Claim 的基础。

States:
  ACTIVE     — 在线、就绪
  IDLE       — 在线但空闲
  WORKING    — 执行任务中
  OFFLINE    — 已离线

规范：
- 无 FSM 库/状态机模式。状态 = 原子字段。
- Cede/TaskClaim/EventWakeup 通过 state 做决策。
- 所有 state 变更写入 memory 做持久化记录。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("autonomous.teammate_state")


class TeammateState(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    WORKING = "working"
    OFFLINE = "offline"


class TeammateRuntimeState:
    """Mutable state holder for a single teammate (Phase 13.4).

    Thread-safe for async use: all access via the singleton manager.
    """

    __slots__ = (
        "teammate_id", "state", "current_task_id",
        "last_state_change", "state_history",
        "last_activity", "consecutive_idle_seconds",
    )

    def __init__(self, teammate_id: str):
        self.teammate_id = teammate_id
        self.state = TeammateState.ACTIVE
        self.current_task_id: Optional[str] = None
        self.last_state_change = time.time()
        self.state_history: list[dict] = []
        self.last_activity = time.time()
        self.consecutive_idle_seconds = 0.0

    def set_state(self, new_state: TeammateState, task_id: str = "") -> dict:
        """Transition to a new state. Returns the transition record.

        - Stores previous state in history.
        - Updates last_activity on any transition.
        - Sets current_task_id when entering WORKING.
        """
        old = self.state.value
        now = time.time()
        prev_idle = self.consecutive_idle_seconds

        if self.state == TeammateState.IDLE and new_state != TeammateState.IDLE:
            self.consecutive_idle_seconds = now - self.last_state_change
        elif self.state != TeammateState.IDLE and new_state == TeammateState.IDLE:
            pass  # start idle timer on next transition

        self.state = new_state
        self.current_task_id = task_id if new_state == TeammateState.WORKING else (
            self.current_task_id if new_state == TeammateState.ACTIVE else None
        )
        self.last_state_change = now
        self.last_activity = now

        record = {
            "teammate_id": self.teammate_id,
            "from_state": old,
            "to_state": new_state.value,
            "task_id": task_id or "",
            "timestamp": now,
            "utc": datetime.now(timezone.utc).isoformat(),
        }
        self.state_history.append(record)
        # Keep history bounded
        if len(self.state_history) > 100:
            self.state_history = self.state_history[-50:]
        return record

    def touch(self) -> None:
        """Update last_activity without state change."""
        self.last_activity = time.time()

    @property
    def idle_seconds(self) -> float:
        if self.state == TeammateState.IDLE:
            return time.time() - self.last_state_change
        return 0.0

    @property
    def is_available(self) -> bool:
        """Available to respond or claim tasks."""
        return self.state in (TeammateState.ACTIVE, TeammateState.IDLE)

    def to_dict(self) -> dict:
        return {
            "teammate_id": self.teammate_id,
            "state": self.state.value,
            "current_task_id": self.current_task_id or "",
            "last_activity": self.last_activity,
            "last_state_change": self.last_state_change,
            "idle_seconds": self.idle_seconds,
            "is_available": self.is_available,
            "consecutive_idle_seconds": self.consecutive_idle_seconds,
            "history_count": len(self.state_history),
        }


# ── Global State Manager ──

class TeammateStateManager:
    """Holds all teammate runtime states. Singleton.

    Because state is transient (not persisted), we store in memory.
    For crash recovery, state is logged to memory items on every change.
    """

    def __init__(self):
        self._states: dict[str, TeammateRuntimeState] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, teammate_id: str) -> TeammateRuntimeState:
        if teammate_id not in self._states:
            self._states[teammate_id] = TeammateRuntimeState(teammate_id)
        return self._states[teammate_id]

    async def get(self, teammate_id: str) -> Optional[TeammateRuntimeState]:
        return self._states.get(teammate_id)

    async def set_state(
        self, teammate_id: str, new_state: TeammateState, task_id: str = "",
        *,
        db=None, run_id: Optional[str] = None,
    ) -> dict:
        """Transition state and persist record to memory.

        If *db* and *run_id* are provided, also dual-write to
        OrganizationState (member type) for DB-backed persistence.
        """
        async with self._lock:
            st = await self.get_or_create(teammate_id)
            record = st.set_state(new_state, task_id)
        # Fire-and-forget memory persistence
        asyncio.ensure_future(self._persist_transition(record))
        # Dual-write to OrganizationState if DB available
        if db is not None and run_id is not None:
            try:
                from backend.services.organization.state import OrganizationStateService
                svc = OrganizationStateService(db)
                await svc.set_state(
                    run_id, "member", teammate_id,
                    {"state": new_state.value, "task_id": task_id},
                )
            except Exception as e:
                logger.warning("[TEAMMATE-STATE] OrganizationState dual-write failed: %s", e)
        return record

    async def set_working(self, teammate_id: str, task_id: str) -> dict:
        return await self.set_state(teammate_id, TeammateState.WORKING, task_id)

    async def set_idle(self, teammate_id: str) -> dict:
        return await self.set_state(teammate_id, TeammateState.IDLE)

    async def set_active(self, teammate_id: str) -> dict:
        return await self.set_state(teammate_id, TeammateState.ACTIVE)

    async def set_offline(self, teammate_id: str) -> dict:
        return await self.set_state(teammate_id, TeammateState.OFFLINE)

    async def touch(self, teammate_id: str) -> None:
        st = await self.get_or_create(teammate_id)
        st.touch()

    async def list_available(self) -> list[TeammateRuntimeState]:
        return [s for s in self._states.values() if s.is_available]

    async def list_all(self) -> list[dict]:
        return [s.to_dict() for s in self._states.values()]

    async def list_all_states(self, filter_state: str = "") -> list[dict]:
        results = []
        for s in self._states.values():
            if filter_state and s.state.value != filter_state:
                continue
            results.append(s.to_dict())
        return results

    async def _persist_transition(self, record: dict) -> None:
        """Write state transition to memory items for crash recovery."""
        try:
            from backend.services.memory.memory_service import get_memory_service
            from backend.services.memory.memory_types import MemoryItem, MemoryType
            svc = get_memory_service()
            await svc.store(MemoryItem(
                memory_type=MemoryType.EVENT,
                content=f"[STATE_TRANSITION] {record['teammate_id']}: "
                        f"{record['from_state']} → {record['to_state']}",
                source_id=record["teammate_id"],
                relevance_score=0.3,
                metadata={
                    "event": "STATE_TRANSITION",
                    "teammate_id": record["teammate_id"],
                    "from_state": record["from_state"],
                    "to_state": record["to_state"],
                    "task_id": record["task_id"],
                    "scope": "runtime",
                },
            ))
        except Exception as e:
            logger.debug("[StateManager] persist skipped: %s", e)


# ── Singleton ──

_manager: Optional[TeammateStateManager] = None


def get_state_manager() -> TeammateStateManager:
    global _manager
    if _manager is None:
        _manager = TeammateStateManager()
    return _manager
