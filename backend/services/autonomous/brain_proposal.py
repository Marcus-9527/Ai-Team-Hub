"""autonomous/brain_proposal.py — Brain Proposal Approval (Phase 13.5)

Reflection 生成 proposal → 人工批准 → 写入 Brain。

Proposal 生命周期：
  1. CREATED  — ReflectionService 检测到需修改核心人格时创建
  2. APPROVED — 用户（通过 UI）批准
  3. REJECTED — 用户拒绝
  4. EXPIRED  — 超时自动过期 (72h)

内容：
  - target_type: 要修改的 BrainFragmentType
  - proposed_content: 修改后的内容
  - original_content: 修改前的原始内容
  - diff_summary: LLM 生成的变更摘要
  - teammate_id: 关联的 teammate
  - task_id: 触发 proposal 的 task（如果有）

存储：
  复用 memory_items 表，item_type = "brain:proposal"
  metadata 包含审批相关字段。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("autonomous.brain_proposal")


class ProposalStatus(Enum):
    CREATED = "created"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


PROPOSAL_TTL_SECONDS = 72 * 3600  # 72 hours


@dataclass
class Proposal:
    """A brain modification proposal awaiting approval."""
    id: str = ""
    teammate_id: str = ""
    target_type: str = ""              # BrainFragmentType value
    target_label: str = ""             # Human-readable label
    proposed_content: str = ""
    original_content: str = ""
    diff_summary: str = ""             # LLM or heuristic summary of changes
    status: str = ProposalStatus.CREATED.value
    task_id: str = ""                  # optional trigger task
    reason: str = ""                   # why this change is proposed
    created_at: float = 0.0
    resolved_at: float = 0.0
    resolved_by: str = ""             # who approved/rejected ("user" or "system_expiry")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "teammate_id": self.teammate_id,
            "target_type": self.target_type,
            "target_label": self.target_label,
            "proposed_content": self.proposed_content[:500],
            "original_content": self.original_content[:500],
            "diff_summary": self.diff_summary,
            "status": self.status,
            "task_id": self.task_id,
            "reason": self.reason[:200],
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }

    def is_expired(self) -> bool:
        if self.status != ProposalStatus.CREATED.value:
            return False
        return time.time() - self.created_at > PROPOSAL_TTL_SECONDS


# ── Proposal Manager ──

class BrainProposalManager:
    """Manages the proposal lifecycle: create → approve/reject/expire → apply.

    Singleton. Uses in-memory dict for active proposals, persists to memory.
    """

    def __init__(self):
        self._proposals: dict[str, Proposal] = {}  # id → Proposal
        self._lock = asyncio.Lock()

    async def create(
        self,
        teammate_id: str,
        target_type: str,
        target_label: str,
        proposed_content: str,
        original_content: str = "",
        diff_summary: str = "",
        task_id: str = "",
        reason: str = "",
    ) -> Proposal:
        """Create a new proposal. Returns the Proposal object with assigned id."""
        proposal = Proposal(
            id=f"prop_{uuid.uuid4().hex[:12]}",
            teammate_id=teammate_id,
            target_type=target_type,
            target_label=target_label,
            proposed_content=proposed_content,
            original_content=original_content,
            diff_summary=diff_summary or self._auto_diff_summary(
                original_content, proposed_content,
            ),
            status=ProposalStatus.CREATED.value,
            task_id=task_id,
            reason=reason,
            created_at=time.time(),
        )

        async with self._lock:
            self._proposals[proposal.id] = proposal

        asyncio.ensure_future(self._persist(proposal))

        logger.info("[Proposal] created %s for %s type=%s",
                     proposal.id[:12], teammate_id[:8], target_type)
        return proposal

    async def approve(
        self,
        proposal_id: str,
        resolved_by: str = "user",
    ) -> tuple[bool, str]:
        """Approve a proposal → apply the change to brain fragments.

        Returns (success, message).
        """
        async with self._lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return False, "Proposal not found"
            if proposal.status != ProposalStatus.CREATED.value:
                return False, f"Proposal is already {proposal.status}"

            proposal.status = ProposalStatus.APPROVED.value
            proposal.resolved_at = time.time()
            proposal.resolved_by = resolved_by

        # Apply the change (fire-and-forget)
        ok = await self._apply_proposal(proposal)

        asyncio.ensure_future(self._persist(proposal))

        if ok:
            logger.info("[Proposal] %s APPROVED and applied", proposal_id[:12])
            return True, "approved and applied"
        else:
            return False, "approved but application failed (see logs)"

    async def reject(
        self,
        proposal_id: str,
        resolved_by: str = "user",
    ) -> tuple[bool, str]:
        """Reject a proposal (no brain change)."""
        async with self._lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return False, "Proposal not found"
            if proposal.status != ProposalStatus.CREATED.value:
                return False, f"Proposal is already {proposal.status}"

            proposal.status = ProposalStatus.REJECTED.value
            proposal.resolved_at = time.time()
            proposal.resolved_by = resolved_by

        asyncio.ensure_future(self._persist(proposal))
        logger.info("[Proposal] %s REJECTED by %s", proposal_id[:12], resolved_by)
        return True, "rejected"

    async def expire(self) -> int:
        """Expire all overdue proposals. Returns count of expired proposals."""
        expired = []
        async with self._lock:
            for prop in list(self._proposals.values()):
                if prop.is_expired():
                    prop.status = ProposalStatus.EXPIRED.value
                    prop.resolved_at = time.time()
                    prop.resolved_by = "system_expiry"
                    expired.append(prop)

        for prop in expired:
            asyncio.ensure_future(self._persist(prop))

        if expired:
            logger.info("[Proposal] expired %d proposal(s)", len(expired))
        return len(expired)

    async def get(self, proposal_id: str) -> Optional[Proposal]:
        """Get a proposal by id."""
        return self._proposals.get(proposal_id)

    async def list(
        self,
        status: str = "",
        teammate_id: str = "",
        limit: int = 50,
    ) -> list[Proposal]:
        """List proposals with optional filters."""
        results = list(self._proposals.values())
        if status:
            results = [p for p in results if p.status == status]
        if teammate_id:
            results = [p for p in results if p.teammate_id == teammate_id]
        results.sort(key=lambda p: p.created_at, reverse=True)
        return results[:limit]

    async def list_pending(self) -> list[Proposal]:
        """List all created/unresolved proposals."""
        return await self.list(status=ProposalStatus.CREATED.value)

    async def count_pending(self) -> int:
        return len(await self.list_pending())

    # ── Internal ──

    async def _apply_proposal(self, proposal: Proposal) -> bool:
        """Apply the approved proposal to brain fragments."""
        try:
            from backend.services.brain.fragment_store import (
                get_brain_fragment_store,
                BrainFragment,
                BrainFragmentType,
            )

            # Parse target_type back to enum
            try:
                ftype = BrainFragmentType(proposal.target_type)
            except ValueError:
                logger.warning("[Proposal] unknown target_type: %s", proposal.target_type)
                return False

            store = get_brain_fragment_store()
            frag = BrainFragment(
                teammate_id=proposal.teammate_id,
                fragment_type=ftype,
                content=proposal.proposed_content,
                confidence=0.8,
                source=f"proposal:{proposal.id}",
            )
            await store.store(frag)

            logger.info("[Proposal] applied %s → %s for %s",
                         proposal.id[:12], proposal.target_type, proposal.teammate_id[:8])

            # Fire BRAIN_UPDATED event
            try:
                from backend.services.autonomous.event_wakeup import (
                    get_event_wakeup_bus,
                    WakeupEvent,
                    WakeupPayload,
                )
                bus = get_event_wakeup_bus()
                bus.fire(WakeupEvent.BRAIN_UPDATED, WakeupPayload(
                    event_type=WakeupEvent.BRAIN_UPDATED.value,
                    teammate_id=proposal.teammate_id,
                    reason=f"Proposal {proposal.id[:12]} approved — "
                           f"updated {proposal.target_type}",
                    data={"proposal_id": proposal.id, "target_type": proposal.target_type},
                ))
            except Exception:
                pass

            return True
        except Exception as e:
            logger.error("[Proposal] apply failed for %s: %s", proposal.id[:12], e)
            return False

    async def _persist(self, proposal: Proposal) -> None:
        """Write proposal to memory items."""
        try:
            from backend.services.memory.memory_service import get_memory_service
            from backend.services.memory.memory_types import MemoryItem, MemoryType
            svc = get_memory_service()
            await svc.store(MemoryItem(
                memory_type="brain:proposal",
                content=("[PROPOSAL] %s for %s (%s): %s"
                         % (proposal.id[:12], proposal.teammate_id[:8],
                            proposal.target_type, proposal.diff_summary[:200])),
                source_id=proposal.id,
                relevance_score=0.6,
                metadata={
                    "event": "BRAIN_PROPOSAL",
                    "proposal_id": proposal.id,
                    "teammate_id": proposal.teammate_id,
                    "target_type": proposal.target_type,
                    "status": proposal.status,
                    "task_id": proposal.task_id,
                    "scope": "proposal",
                },
            ))
        except Exception as e:
            logger.debug("[Proposal] persist skipped: %s", e)

    @staticmethod
    def _auto_diff_summary(old: str, new: str) -> str:
        """Generate a simple diff summary (character-level)."""
        if not old:
            return "New fragment created"
        if old == new:
            return "No change"
        # Simple word-level diff
        old_words = set(old.lower().split())
        new_words = set(new.lower().split())
        added = new_words - old_words
        removed = old_words - new_words

        parts = []
        if added:
            parts.append(f"Added: {', '.join(list(added)[:5])}")
        if removed:
            parts.append(f"Removed: {', '.join(list(removed)[:5])}")
        if not parts:
            return "Content modified (minor)"

        return "; ".join(parts)


# ── Singleton ──

_proposal_manager: Optional[BrainProposalManager] = None


def get_proposal_manager() -> BrainProposalManager:
    global _proposal_manager
    if _proposal_manager is None:
        _proposal_manager = BrainProposalManager()
    return _proposal_manager
