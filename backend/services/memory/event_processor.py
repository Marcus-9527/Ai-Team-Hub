"""MemoryEventProcessor — 基于 SessionEvent 的组织知识提取器。

把 SessionEvent 事件流转化为三类组织记忆：

- member memory  — 单个队友经验（某队友在某类任务中的表现）
- team memory   — 团队协作经验（多队友配合模式、转交模式）
- project memory — 项目事实（任务成果、目标、结果）

设计原则：
- SessionEvent 是唯一事实来源，不读其他表。
- 规则式提取（不引入 AI）。
- 使用现有的 MemoryService 存储。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import (
    SessionTrigger, SessionTurn, SessionEvent,
    TriggerType,
)
from backend.services.memory.memory_service import MemoryService, get_memory_service
from backend.services.memory.memory_types import MemoryItem, MemoryType

logger = logging.getLogger("memory.event_processor")

_MEMORY_MEMBER_SCOPE = "member"
_MEMORY_TEAM_SCOPE = "team"
_MEMORY_PROJECT_SCOPE = "project"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryEventProcessor:
    """从 SessionEvent 事件流提取组织记忆。"""

    def __init__(self, memory_service: Optional[MemoryService] = None):
        self._memory = memory_service or get_memory_service()

    # ── Public entry ──────────────────────────────────────────────

    async def process_trigger(self, db: AsyncSession, trigger_id: str) -> int:
        """处理一个 trigger 的所有事件，生成组织记忆。返回新创建的 memory item 数。"""
        trigger = await db.get(SessionTrigger, trigger_id)
        if trigger is None:
            logger.warning("[MEP] trigger %s not found", trigger_id[:8])
            return 0

        events = await self._load_events(db, trigger_id)
        turns = await self._load_turns(db, trigger_id)

        items: list[MemoryItem] = []

        # 1. member memory — 每个 turn 贡献一个成员经验
        for turn in turns:
            member_items = self._extract_member_memory(trigger, turn)
            items.extend(member_items)

        # 2. team memory — 多队友协作模式
        if len(turns) >= 2:
            team_items = self._extract_team_memory(trigger, turns, events)
            items.extend(team_items)

        # 3. project memory — trigger 级别的事实
        proj_items = self._extract_project_memory(trigger, events)
        items.extend(proj_items)

        if not items:
            return 0

        await self._memory.store_batch(items)
        logger.info(
            "[MEP] trigger %s → %d memories (member=%d team=%d project=%d)",
            trigger_id[:8], len(items),
            sum(1 for i in items if i.metadata.get("scope") == _MEMORY_MEMBER_SCOPE),
            sum(1 for i in items if i.metadata.get("scope") == _MEMORY_TEAM_SCOPE),
            sum(1 for i in items if i.metadata.get("scope") == _MEMORY_PROJECT_SCOPE),
        )
        return len(items)

    # ── Event / Turn loaders ─────────────────────────────────────

    async def _load_events(self, db: AsyncSession, trigger_id: str) -> list[SessionEvent]:
        result = await db.execute(
            select(SessionEvent)
            .where(SessionEvent.trigger_id == trigger_id)
            .order_by(SessionEvent.timestamp)
        )
        return list(result.scalars().all())

    async def _load_turns(self, db: AsyncSession, trigger_id: str) -> list[SessionTurn]:
        result = await db.execute(
            select(SessionTurn)
            .where(SessionTurn.trigger_id == trigger_id)
            .order_by(SessionTurn.start_time)
        )
        return list(result.scalars().all())

    # ── Extraction: member memory ────────────────────────────────

    def _extract_member_memory(
        self, trigger: SessionTrigger, turn: SessionTurn,
    ) -> list[MemoryItem]:
        """从单个 turn 提取成员经验。

        X: 某队友完成了什么动作（plan/review/task），成功/失败。
        """
        teammate_id = turn.teammate_id
        if not teammate_id:
            return []

        turn_type = turn.turn_type or "chat"
        action = turn.action or "unknown"
        outcome = "failed" if turn.failure else "completed"
        tokens = (turn.tokens_in or 0) + (turn.tokens_out or 0)

        content_parts = [
            f"[{turn_type}] teammate {teammate_id} {outcome} with action={action}",
        ]
        if turn.failure:
            content_parts.append(f" | error: {turn.failure[:200]}")
        if tokens:
            content_parts.append(f" | tokens: {tokens}")
        content = "".join(content_parts)

        turn_events = self._compute_turn_events(turn)
        total_tool_calls = turn_events.get("tool_calls", 0)

        mem = MemoryItem(
            memory_type=MemoryType.TEAMMATE,
            content=content,
            source_id=trigger.id,
            relevance_score=0.0,
            embedding=self._memory.compute_embedding(content),
            created_at=turn.start_time or _now(),
            metadata={
                "scope": _MEMORY_MEMBER_SCOPE,
                "teammate_id": teammate_id,
                "turn_type": turn_type,
                "action": action,
                "outcome": outcome,
                "failed": bool(turn.failure),
                "tokens_total": tokens,
                "tool_calls": total_tool_calls,
                "trigger_type": trigger.trigger_type,
                "source": "session_event",
            },
        )
        return [mem]

    def _compute_turn_events(self, turn: SessionTurn) -> dict:
        """Simple estimate from the turn's metadata (no event re-query)."""
        meta = turn.metadata_json or {}
        return {
            "tool_calls": meta.get("tool_calls", 0),
            "retries": meta.get("retries", 0),
        }

    # ── Extraction: team memory ──────────────────────────────────

    def _extract_team_memory(
        self, trigger: SessionTrigger, turns: list[SessionTurn],
        events: list[SessionEvent],
    ) -> list[MemoryItem]:
        """从 trigger 的多 turn 协作提取团队记忆。

        描述：X 个队友在 Y 类任务中协作，先后出现哪些角色。
        """
        teammate_ids = sorted(set(t.id for t in turns if t.teammate_id))
        turn_types = sorted(set(t.turn_type or "chat" for t in turns))
        n_teammates = len(teammate_ids)

        # 失败率
        total = len(turns)
        failed = sum(1 for t in turns if t.failure)
        fail_rate = f"{failed}/{total}"

        content = (
            f"[team] {n_teammates} teammates ({', '.join(teammate_ids[:3])}"
            f"{'...' if n_teammates > 3 else ''}) "
            f"collaborated on trigger_type={trigger.trigger_type} "
            f"turn_types={turn_types} "
            f"fail_rate={fail_rate}"
        )

        mem = MemoryItem(
            memory_type=MemoryType.TEAMMATE,
            content=content,
            source_id=trigger.id,
            relevance_score=0.0,
            embedding=self._memory.compute_embedding(content),
            created_at=trigger.trigger_time or _now(),
            metadata={
                "scope": _MEMORY_TEAM_SCOPE,
                "n_teammates": n_teammates,
                "teammate_ids": teammate_ids,
                "turn_types": turn_types,
                "total_turns": total,
                "failed_turns": failed,
                "trigger_type": trigger.trigger_type,
                "source": "session_event",
            },
        )
        return [mem]

    # ── Extraction: project memory ───────────────────────────────

    def _extract_project_memory(
        self, trigger: SessionTrigger, events: list[SessionEvent],
    ) -> list[MemoryItem]:
        """从 trigger 的事件提取项目事实。

        描述：什么任务、哪种类型、成败、耗时、tokens 使用量。
        """
        # 从 trigger 元数据
        task_id = trigger.task_id or ""
        workspace_id = trigger.workspace_id or ""
        trigger_type = trigger.trigger_type

        # 从事件流统计
        close_events = [e for e in events if e.event_type == "turn.close"]
        total_tokens_in = sum((e.payload or {}).get("tokens_in", 0) or 0 for e in close_events)
        total_tokens_out = sum((e.payload or {}).get("tokens_out", 0) or 0 for e in close_events)

        fail_events = [e for e in events if e.event_type == "turn.fail"]
        n_failures = len(fail_events)

        content = (
            f"[project] trigger_type={trigger_type}"
            f"{f' task_id={task_id[:8]}' if task_id else ''}"
            f" turns={len(close_events)}"
            f" failures={n_failures}"
            f" tokens_in={total_tokens_in} tokens_out={total_tokens_out}"
        )

        mem = MemoryItem(
            memory_type=MemoryType.TASK,
            content=content,
            source_id=trigger.id,
            relevance_score=0.0,
            embedding=self._memory.compute_embedding(content),
            created_at=trigger.trigger_time or _now(),
            metadata={
                "scope": _MEMORY_PROJECT_SCOPE,
                "task_id": task_id,
                "workspace_id": workspace_id,
                "trigger_type": trigger_type,
                "total_turns": len(close_events),
                "failures": n_failures,
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
                "source": "session_event",
            },
        )
        return [mem]


# ── Singleton ─────────────────────────────────────────────────────

_processor: Optional[MemoryEventProcessor] = None


def get_event_processor() -> MemoryEventProcessor:
    global _processor
    if _processor is None:
        _processor = MemoryEventProcessor()
    return _processor
