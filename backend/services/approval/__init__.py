"""Approval Service — manages human approval lifecycle for DAG execution nodes."""
import asyncio
import logging
import time
import uuid
from enum import Enum

logger = logging.getLogger("approval")


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalRecord:
    """An approval request tied to a DAG node execution."""

    __slots__ = (
        "id", "execution_id", "dag_node_id", "status",
        "requested_by", "approved_by", "created_at", "resolved_at",
        "_event",
    )

    def __init__(self, execution_id: str, dag_node_id: str,
                 requested_by: str = ""):
        self.id = f"apr_{uuid.uuid4().hex[:12]}"
        self.execution_id = execution_id
        self.dag_node_id = dag_node_id
        self.status = ApprovalStatus.PENDING
        self.requested_by = requested_by
        self.approved_by = ""
        self.created_at = time.time()
        self.resolved_at = 0.0
        self._event = asyncio.Event()

    def approve(self, approved_by: str = "") -> None:
        if self.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot approve — status is {self.status.value}")
        self.status = ApprovalStatus.APPROVED
        self.approved_by = approved_by
        self.resolved_at = time.time()
        self._event.set()

    def reject(self, approved_by: str = "") -> None:
        if self.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot reject — status is {self.status.value}")
        self.status = ApprovalStatus.REJECTED
        self.approved_by = approved_by
        self.resolved_at = time.time()
        self._event.set()

    async def wait(self, timeout: float = 86400.0) -> bool:
        """Block until resolved. Returns True if APPROVED, False if REJECTED/timed out."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.status = ApprovalStatus.REJECTED
            self.resolved_at = time.time()
            self._event.set()
            return False
        return self.status == ApprovalStatus.APPROVED

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "dag_node_id": self.dag_node_id,
            "status": self.status.value,
            "requested_by": self.requested_by,
            "approved_by": self.approved_by,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ApprovalService:
    """In-memory approval registry for DAG node approvals.

    ponytail: in-memory dict; swap to DB-backed when multi-process or
    persistence is needed.
    """

    def __init__(self):
        self._records: dict[str, ApprovalRecord] = {}

    def create(self, execution_id: str, dag_node_id: str,
               requested_by: str = "") -> ApprovalRecord:
        rec = ApprovalRecord(execution_id, dag_node_id, requested_by)
        self._records[rec.id] = rec
        logger.info("[APPROVAL] created %s for node %s (exec %s)",
                     rec.id, dag_node_id, execution_id)
        return rec

    def get(self, approval_id: str) -> ApprovalRecord | None:
        return self._records.get(approval_id)

    def approve(self, approval_id: str, by: str = "") -> ApprovalRecord | None:
        rec = self._records.get(approval_id)
        if rec:
            rec.approve(by)
            logger.info("[APPROVAL] %s approved by %s", approval_id, by or "anon")
        return rec

    def reject(self, approval_id: str, by: str = "") -> ApprovalRecord | None:
        rec = self._records.get(approval_id)
        if rec:
            rec.reject(by)
            logger.info("[APPROVAL] %s rejected by %s", approval_id, by or "anon")
        return rec

    def list_pending(self) -> list[dict]:
        return [r.to_dict() for r in self._records.values()
                if r.status == ApprovalStatus.PENDING]

    def list_all(self) -> list[dict]:
        return [r.to_dict() for r in self._records.values()]


# ── Singleton ──

_approval_service: ApprovalService | None = None


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service


def reset_approval_service() -> None:
    global _approval_service
    _approval_service = None
