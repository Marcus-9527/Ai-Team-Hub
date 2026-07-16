"""autonomous/cede_protocol.py — Cede Protocol (Phase 13.1)

Helio 风格：每个 teammate 判断是否响应消息。

Decisions:
  RESPOND  — 该队友有相关内容要回复
  CEDE     — 该队友没有相关信息，让给其他人
  IGNORE   — 消息不相关，彻底忽略

记录：
  - 所有决策持久化到 memory（CedeRecord）
  - 防止多个 AI 同时回复同一消息

设计：
  - cede 决策在 stream_teammate 之前判断
  - RESPOND = 即刻开始流式回复，CEDE/IGNORE = 跳过该队友
  - 依赖 TeammateRuntimeState（确保不 WORKING 的队友不进入竞争）

集成点：
  - team_collaboration.py::generate_team_response() 在循环每个 teammate 前
  - chat route 在调用 generate_team_response 前
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("autonomous.cede_protocol")


class CedeDecision(Enum):
    RESPOND = "respond"
    CEDE = "cede"
    IGNORE = "ignore"


@dataclass
class CedeRecord:
    """A single respond/cede/ignore decision."""
    id: str = ""
    channel_id: str = ""
    message_id: str = ""
    teammate_id: str = ""
    teammate_name: str = ""
    decision: str = ""           # RESPOND/CEDE/IGNORE
    reason: str = ""             # why this decision
    confidence: float = 0.0     # how confident the decision was
    timestamp: float = 0.0
    round: int = 0               # collaboration round number

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "teammate_id": self.teammate_id,
            "teammate_name": self.teammate_name,
            "decision": self.decision,
            "reason": self.reason,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "round": self.round,
        }


# ── Cede Protocol Engine ──

class CedeProtocol:
    """Determine if a teammate should respond to a given message.

    Rules (in order):
      1. If teammate state is WORKING → CEDE (already busy)
      2. If teammate already RESPONDed to this message → CEDE (no double-reply)
      3. Role relevance → every relevant teammate RESPONDs; off-domain → CEDE

    The actual LLM call to make the decision is done via a lightweight
    categorizer prompt. In the minimal implementation we use role-based rules.
    """

    def __init__(self):
        self._records: dict[str, list[CedeRecord]] = {}  # message_id → records
        self._respond_lock = asyncio.Lock()

    # ── Decision API ──

    async def decide(
        self,
        teammate: dict,
        message: str,
        channel_id: str = "",
        message_id: str = "",
        history_texts: list[str] = None,
    ) -> CedeDecision:
        """Make a respond/cede/ignore decision for a teammate.

        Uses a tiered approach:
          1. Quick rules (state, already-responded)
          2. LLM-based relevance check if rules are ambiguous
        """
        teammate_id = teammate.get("id", "")
        name = teammate.get("name", "?")

        # Tier 1: Already responded to this message → CEDE (no double-reply)
        if await self._has_responded(teammate_id, message_id):
            logger.debug("[Cede] %s already responded to msg %s — CEDE", name, message_id[:8])
            return CedeDecision.CEDE

        # Role-based relevance check. Every relevant teammate may RESPOND —
        # there is intentionally NO cross-teammate claim guard, so all relevant
        # teammates reply (not just the first one to grab the message).
        role_match, confidence = self._check_role_relevance(teammate, message[:200])

        if confidence >= 0.3:
            decision = CedeDecision.RESPOND if role_match else CedeDecision.CEDE
        else:
            decision = CedeDecision.CEDE

        logger.debug("[Cede] %s (%s) → %s (conf=%.2f)", name,
                     teammate.get("role", "?"), decision.value, confidence)
        return decision

    async def record_decision(
        self,
        teammate: dict,
        message_id: str,
        decision: CedeDecision,
        channel_id: str = "",
        round: int = 0,
    ) -> str:
        """Record a cede decision and persist it."""
        record_id = str(uuid.uuid4())
        teammate_id = teammate.get("id", "")
        name = teammate.get("name", "?")

        record = CedeRecord(
            id=record_id,
            channel_id=channel_id,
            message_id=message_id,
            teammate_id=teammate_id,
            teammate_name=name,
            decision=decision.value,
            reason=self._decision_reason(decision, teammate),
            confidence=1.0 if decision == CedeDecision.RESPOND else 0.6,
            timestamp=time.time(),
            round=round,
        )

        if message_id not in self._records:
            self._records[message_id] = []
        self._records[message_id].append(record)

        # Fire-and-forget persistence
        asyncio.ensure_future(self._persist_decision(record))
        return record_id

    async def get_message_decisions(self, message_id: str) -> list[CedeRecord]:
        """Get all decisions for a message."""
        return list(self._records.get(message_id, []))

    async def who_responded(self, message_id: str) -> list[CedeRecord]:
        """Get all RESPOND decisions for a message."""
        return [
            r for r in self._records.get(message_id, [])
            if r.decision == CedeDecision.RESPOND.value
        ]

    # ── Freshness Context Evaluation (Phase 19) ──

    async def evaluate_context(
        self,
        channel_id: str,
        message_id: str,
        teammate_id: str,
        teammate_name: str = "",
        max_messages: int = 20,
    ) -> tuple[CedeDecision, str]:
        """Read recent channel messages, decide if this teammate should respond.

        Returns (decision, record_id). Auto-records the decision.
        """
        recent = await self._fetch_channel_messages(channel_id, message_id, max_messages)
        teammate = await self._load_teammate(teammate_id)
        if not teammate:
            teammate = {"id": teammate_id, "name": teammate_name or teammate_id, "role": ""}

        decision = await self.decide(
            teammate=teammate,
            message=recent[0] if recent else "",
            channel_id=channel_id,
            message_id=message_id,
            history_texts=recent[1:] if len(recent) > 1 else None,
        )
        record_id = await self.record_decision(teammate, message_id, decision, channel_id)
        return decision, record_id

    # ── DB Helpers ──

    async def _fetch_channel_messages(
        self, channel_id: str, message_id: str, limit: int = 20,
    ) -> list[str]:
        """Fetch recent messages from a channel (excluding the target message)."""
        try:
            from backend.database import async_session
            from sqlalchemy import select, desc
            from backend.models import Message
            async with async_session() as db:
                res = await db.execute(
                    select(Message)
                    .where(Message.channel_id == channel_id)
                    .order_by(desc(Message.created_at))
                    .limit(limit)
                )
                msgs = res.scalars().all()
            return [m.content for m in msgs if m.id != message_id and m.content]
        except Exception as e:
            logger.debug("[Cede] channel fetch skipped: %s", e)
            return []

    async def _load_teammate(self, teammate_id: str) -> Optional[dict]:
        """Load a teammate from DB as dict."""
        try:
            from backend.database import async_session
            from sqlalchemy import select
            from backend.models import Teammate
            async with async_session() as db:
                res = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
                obj = res.scalar_one_or_none()
                return obj.to_dict() if obj else None
        except Exception as e:
            logger.debug("[Cede] teammate load skipped: %s", e)
            return None

    # ── Internals ──

    async def _has_responded(self, teammate_id: str, message_id: str) -> bool:
        """Check if this teammate already made a decision on this message."""
        records = self._records.get(message_id, [])
        return any(r.teammate_id == teammate_id for r in records)

    def _check_role_relevance(self, teammate: dict, message: str) -> tuple[bool, float]:
        """Check if the teammate's role is relevant to the message.

        Returns (relevant, confidence).
        Simple keyword-based heuristic; could be replaced with LLM call.
        """
        role = (teammate.get("role", "") or "").lower()
        sys_prompt = (teammate.get("system_prompt", "") or "").lower()
        name = (teammate.get("name", "") or "").lower()
        message_lower = message.lower()

        # Combined text for role detection
        role_text = f"{role} {sys_prompt} {name}"

        # Keyword maps
        engineering_kw = ["code", "implement", "bug", "refactor", "test", "api",
                          "backend", "frontend", "deploy", "database", "sql",
                          "python", "javascript", "git", "代码", "实现", "部署"]
        design_kw = ["design", "ui", "ux", "layout", "user interface", "visual",
                     "wireframe", "prototype", "样式", "设计", "布局", "交互"]
        product_kw = ["product", "feature", "roadmap", "priority", "requirement",
                      "user story", "需求", "功能", "优先级", "规划"]
        analyst_kw = ["risk", "analysis", "data", "metric", "performance",
                      "edge case", "分析", "数据", "指标", "风险"]
        techlead_kw = ["architecture", "system design", "component", "module",
                       "reliability", "scalability", "架构", "系统设计"]

        # Determine area keywords based on role
        if "engineer" in role_text or "engineer" in name:
            area_keywords = engineering_kw
        elif "design" in role_text:
            area_keywords = design_kw
        elif "product" in role_text or "pm" in role_text:
            area_keywords = product_kw
        elif "analyst" in role_text:
            area_keywords = analyst_kw
        elif "techlead" in role_text or "tech lead" in role_text:
            area_keywords = techlead_kw
        elif "review" in role_text or "reviewer" in role_text:
            area_keywords = engineering_kw + ["review", "quality", "code review",
                                              "审核", "审查"]
        else:
            # Unknown role → always respond (cannot filter by keyword)
            # Every teammate gets a chance to speak; avoids silent teammate bug
            # where unknown-role teammates never reach the 0.3 confidence threshold
            # because the combined keyword pool dilutes match ratio.
            return True, 1.0

        # Count keyword matches within the chosen area
        matches = sum(1 for kw in area_keywords if kw in message_lower)
        total = len(area_keywords)
        if total == 0:
            return True, 0.5

        ratio = matches / max(total * 0.1, 1)  # cf: 10% keyword coverage = high relevance
        confidence = min(ratio, 1.0)

        is_relevant = matches >= 2 or confidence >= 0.3

        # No keyword match → generic message, give the benefit of the doubt
        if matches == 0:
            return True, 0.3  # ponytail: default respond to avoid silent ceiling

        return is_relevant, confidence

    def _decision_reason(self, decision: CedeDecision, teammate: dict) -> str:
        """Reason string for logging/display."""
        name = teammate.get("name", "?")
        role = teammate.get("role", "?")
        if decision == CedeDecision.RESPOND:
            return f"{name} ({role}) has relevant input"
        elif decision == CedeDecision.CEDE:
            return f"{name} ({role}) defers to other teammates"
        else:
            return f"{name} ({role}) — message not in domain"

    async def _persist_decision(self, record: CedeRecord) -> None:
        """Write decision to memory items."""
        try:
            from backend.services.memory.memory_service import get_memory_service
            from backend.services.memory.memory_types import MemoryItem, MemoryType
            svc = get_memory_service()
            await svc.store(MemoryItem(
                memory_type=MemoryType.DECISION,
                content=f"[CEDE] {record.teammate_name} → {record.decision} "
                        f"for msg {record.message_id[:12]}",
                source_id=record.message_id,
                relevance_score=0.4,
                metadata={
                    "event": "CEDE_DECISION",
                    "teammate_id": record.teammate_id,
                    "message_id": record.message_id,
                    "decision": record.decision,
                    "channel_id": record.channel_id,
                    "scope": "cede",
                },
            ))
        except Exception as e:
            logger.debug("[Cede] persist skipped: %s", e)


# ── Singleton ──

_cede_protocol: Optional[CedeProtocol] = None


def get_cede_protocol() -> CedeProtocol:
    global _cede_protocol
    if _cede_protocol is None:
        _cede_protocol = CedeProtocol()
    return _cede_protocol
