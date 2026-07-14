"""autonomous/task_claim.py — Task Claim Protocol (Phase 13.2)

Helio 风格 task 竞争机制：
  1. Task 发布后，多个 teammate 可同时尝试 claim
  2. 原子确认 — 第一个成功 claim 的成为 owner
  3. 记录所有 claim 尝试

设计：
  - 竞争窗口期（claim_window_seconds）内允许 claim
  - 原子锁确保只有一个 owner
  - TaskOrchestrator 的 assign 阶段使用此协议
  - 复用 MemoryService 持久化 claim 记录

关联：
  - teammate_state.py — claim 前检查 is_available
  - cede_protocol.py — 已有 teammate 消息级别去重
  - event_wakeup.py — TASK_CREATED 事件触发 teammates 竞争
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("autonomous.task_claim")


@dataclass
class ClaimRecord:
    """A single claim attempt on a task."""
    id: str = ""
    task_id: str = ""
    teammate_id: str = ""
    teammate_name: str = ""
    status: str = ""            # claimed | rejected | failed
    reason: str = ""            # why claimed/rejected
    attempted_at: float = 0.0
    settled_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "teammate_id": self.teammate_id,
            "teammate_name": self.teammate_name,
            "status": self.status,
            "reason": self.reason,
            "attempted_at": self.attempted_at,
            "settled_at": self.settled_at,
        }


# ── Task Claim Manager ──

class TaskClaimManager:
    """Manages task claim competition with atomic ownership.

    Flow:
      1. Task created → each available teammate can try to claim
      2. claim() → atomic check if task is already claimed
      3. First caller wins, gets owner assignment
      4. All attempts recorded

    Thread-safe via asyncio.Lock.
    """

    CLAIM_WINDOW_SECONDS = 30  # time window for competitors to arrive
    MAX_CLAIMERS = 10           # max claim attempts per task

    def __init__(self):
        self._claims: dict[str, list[ClaimRecord]] = {}  # task_id → claims
        self._owners: dict[str, str] = {}                 # task_id → teammate_id
        self._lock = asyncio.Lock()

    async def claim(
        self,
        task_id: str,
        teammate_id: str,
        teammate_name: str = "",
        reason: str = "",
    ) -> tuple[bool, str]:
        """Attempt to claim a task.

        Returns:
          (True, "claimed") — owner confirmed
          (False, reason) — why claim was rejected
        """
        async with self._lock:
            # Check if task already claimed
            existing_owner = self._owners.get(task_id)
            if existing_owner:
                # Record this attempt
                await self._record_attempt(
                    task_id, teammate_id, teammate_name, "rejected",
                    f"Task already owned by {existing_owner}",
                )
                return False, f"Already claimed by {existing_owner}"

            # Check claim window (from first claim attempt time)
            attempts = self._claims.get(task_id, [])
            if attempts:
                first_attempt = attempts[0].attempted_at
                if time.time() - first_attempt > self.CLAIM_WINDOW_SECONDS:
                    # Window closed — early bird already won
                    return False, "Claim window closed"

            # Check max claimers
            if len(attempts) >= self.MAX_CLAIMERS:
                return False, "Max claim attempts reached"

            # ATOMIC: First to arrive wins
            self._owners[task_id] = teammate_id
            if task_id not in self._claims:
                self._claims[task_id] = []

            claim = ClaimRecord(
                id=str(uuid.uuid4()),
                task_id=task_id,
                teammate_id=teammate_id,
                teammate_name=teammate_name,
                status="claimed",
                reason=reason or f"{teammate_name} claimed the task",
                attempted_at=time.time(),
                settled_at=time.time(),
            )
            self._claims[task_id].append(claim)

        # Fire-and-forget persistence + state update
        asyncio.ensure_future(self._persist_claim(claim))
        asyncio.ensure_future(self._update_state(teammate_id, task_id))

        logger.info("[Claim] %s claimed task %s", teammate_name, task_id[:8])
        return True, "claimed"

    async def get_owner(self, task_id: str) -> Optional[str]:
        """Get the owner of a task (teammate_id)."""
        return self._owners.get(task_id)

    async def get_claims(self, task_id: str) -> list[ClaimRecord]:
        """Get all claim attempts for a task."""
        return list(self._claims.get(task_id, []))

    async def clear(self, task_id: str) -> None:
        """Release claim data (when task completes/fails)."""
        async with self._lock:
            self._owners.pop(task_id, None)
            self._claims.pop(task_id, None)

    async def _record_attempt(
        self, task_id: str, teammate_id: str, teammate_name: str,
        status: str, reason: str,
    ) -> None:
        """Record a rejected/failed claim attempt."""
        if task_id not in self._claims:
            self._claims[task_id] = []
        record = ClaimRecord(
            id=str(uuid.uuid4()),
            task_id=task_id,
            teammate_id=teammate_id,
            teammate_name=teammate_name,
            status=status,
            reason=reason,
            attempted_at=time.time(),
            settled_at=time.time(),
        )
        self._claims[task_id].append(record)
        asyncio.ensure_future(self._persist_claim(record))

    async def _persist_claim(self, record: ClaimRecord) -> None:
        """Write claim to memory items."""
        try:
            from backend.services.memory.memory_service import get_memory_service
            from backend.services.memory.memory_types import MemoryItem, MemoryType
            svc = get_memory_service()
            await svc.store(MemoryItem(
                memory_type=MemoryType.DECISION,
                content=f"[CLAIM] {record.teammate_name} {record.status} "
                        f"task {record.task_id[:12]}",
                source_id=record.task_id,
                relevance_score=0.5,
                metadata={
                    "event": "TASK_CLAIM",
                    "task_id": record.task_id,
                    "teammate_id": record.teammate_id,
                    "teammate_name": record.teammate_name,
                    "status": record.status,
                    "reason": record.reason,
                    "scope": "claim",
                },
            ))
        except Exception as e:
            logger.debug("[Claim] persist skipped: %s", e)

    async def _update_state(self, teammate_id: str, task_id: str) -> None:
        """Mark teammate as WORKING when they win a claim."""
        try:
            from backend.services.autonomous.teammate_state import get_state_manager
            manager = get_state_manager()
            await manager.set_working(teammate_id, task_id)
        except Exception as e:
            logger.debug("[Claim] state update skipped: %s", e)


# ── Singleton ──

_claim_manager: Optional[TaskClaimManager] = None


def get_claim_manager() -> TaskClaimManager:
    global _claim_manager
    if _claim_manager is None:
        _claim_manager = TaskClaimManager()
    return _claim_manager
