"""MemoryConsolidator — across-run knowledge consolidation.

Reads existing scope=member/team/project MemoryItems from MemoryService
and aggregates them into knowledge-type MemoryItems (MEMBER_KNOWLEDGE,
TEAM_PATTERN, PROJECT_KNOWLEDGE).

Pure rule-based aggregation. No AI, no new tables.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Optional

from backend.services.memory.memory_service import MemoryService, get_memory_service
from backend.services.memory.memory_types import MemoryItem, MemoryType

logger = logging.getLogger("memory.consolidator")


class MemoryConsolidator:
    """Aggregate event-scoped memory into cross-run organization knowledge."""

    def __init__(self, memory_service: Optional[MemoryService] = None):
        self._mem = memory_service or get_memory_service()

    async def consolidate_run(self, run_id: str) -> int:
        """Re-read all event-scoped memory and produce knowledge items.

        Returns count of new knowledge items stored.
        """
        # Load all member/team/project scoped items
        member_items = await self._mem.query_by_scope("member", limit=200)
        team_items = await self._mem.query_by_scope("team", limit=200)
        proj_items = await self._mem.query_by_scope("project", limit=200)

        knowledge: list[MemoryItem] = []

        # 1. Member Knowledge — aggregate per-teammate
        knowledge.extend(self._build_member_knowledge(member_items))

        # 2. Team Pattern — aggregate across all runs
        knowledge.extend(self._build_team_knowledge(team_items))

        # 3. Project Knowledge — aggregate per workspace
        knowledge.extend(self._build_project_knowledge(proj_items))

        if not knowledge:
            return 0

        await self._mem.store_batch(knowledge)
        logger.info(
            "[Consolidator] run %s → %d knowledge items", run_id[:8], len(knowledge)
        )
        return len(knowledge)

    # ── Member Knowledge ──────────────────────────────────────────

    def _build_member_knowledge(
        self, items: list[MemoryItem],
    ) -> list[MemoryItem]:
        """Per-teammate capability summary."""
        # Group by teammate_id
        by_teammate: dict[str, list[MemoryItem]] = defaultdict(list)
        for item in items:
            tm = (item.metadata or {}).get("teammate_id")
            if tm:
                by_teammate[tm].append(item)

        result: list[MemoryItem] = []
        for teammate_id, mems in by_teammate.items():
            total = len(mems)
            successes = sum(
                1 for m in mems if (m.metadata or {}).get("outcome") == "completed"
            )
            failures = sum(
                1 for m in mems if (m.metadata or {}).get("outcome") == "failed"
            )
            turn_types = sorted(
                set(m.metadata.get("turn_type", "chat") for m in mems if m.metadata)
            )
            tool_calls = sum(
                (m.metadata or {}).get("tool_calls", 0) or 0 for m in mems
            )
            total_tokens = sum(
                (m.metadata or {}).get("tokens_total", 0) or 0 for m in mems
            )
            success_rate = f"{successes}/{total}"

            content = (
                f"[member] {teammate_id} runs={total} "
                f"success={success_rate} tools={tool_calls} "
                f"tokens={total_tokens} types={turn_types}"
            )

            result.append(MemoryItem(
                memory_type=MemoryType.MEMBER_KNOWLEDGE,
                content=content,
                source_id=teammate_id,
                relevance_score=1.0 - (failures / max(total, 1) * 0.5),
                metadata={
                    "teammate_id": teammate_id,
                    "total": total,
                    "successes": successes,
                    "failures": failures,
                    "turn_types": turn_types,
                    "tool_calls": tool_calls,
                    "total_tokens": total_tokens,
                },
            ))

        return result

    # ── Team Pattern ──────────────────────────────────────────────

    def _build_team_knowledge(
        self, items: list[MemoryItem],
    ) -> list[MemoryItem]:
        """Aggregate collaboration patterns across runs."""
        if not items:
            return []

        total_runs = len(items)
        total_turns = sum(
            (m.metadata or {}).get("total_turns", 0) or 0 for m in items
        )
        total_failed = sum(
            (m.metadata or {}).get("failed_turns", 0) or 0 for m in items
        )

        # Collect all teammate IDs seen across team memories
        all_teammates: Counter[str] = Counter()
        for m in items:
            ids = (m.metadata or {}).get("teammate_ids", []) or []
            all_teammates.update(ids)

        top_teammates = [tm for tm, _ in all_teammates.most_common(5)]

        # Most common trigger types
        trigger_types = sorted(set(
            (m.metadata or {}).get("trigger_type", "chat") for m in items
        ))

        content = (
            f"[team] runs={total_runs} turns={total_turns} "
            f"failures={total_failed} "
            f"active_teammates={top_teammates} "
            f"types={trigger_types}"
        )

        return [MemoryItem(
            memory_type=MemoryType.TEAM_PATTERN,
            content=content,
            source_id="team",
            relevance_score=1.0 - (total_failed / max(total_turns, 1) * 0.5),
            metadata={
                "total_runs": total_runs,
                "total_turns": total_turns,
                "failed_turns": total_failed,
                "active_teammates": top_teammates,
                "trigger_types": trigger_types,
            },
        )]

    # ── Project Knowledge ─────────────────────────────────────────

    def _build_project_knowledge(
        self, items: list[MemoryItem],
    ) -> list[MemoryItem]:
        """Per-workspace project fact aggregation."""
        by_workspace: dict[str, list[MemoryItem]] = defaultdict(list)
        for item in items:
            ws = (item.metadata or {}).get("workspace_id") or ""
            by_workspace[ws].append(item)

        result: list[MemoryItem] = []
        for ws_id, mems in by_workspace.items():
            total_runs = len(mems)
            total_tokens_in = sum(
                (m.metadata or {}).get("tokens_in", 0) or 0 for m in mems
            )
            total_tokens_out = sum(
                (m.metadata or {}).get("tokens_out", 0) or 0 for m in mems
            )
            total_failures = sum(
                (m.metadata or {}).get("failures", 0) or 0 for m in mems
            )

            content = (
                f"[project] workspace={ws_id or '(none)'} "
                f"runs={total_runs} failures={total_failures} "
                f"tokens_in={total_tokens_in} tokens_out={total_tokens_out}"
            )

            result.append(MemoryItem(
                memory_type=MemoryType.PROJECT_KNOWLEDGE,
                content=content,
                source_id=ws_id or "__root__",
                relevance_score=1.0 - (total_failures / max(total_runs, 1) * 0.3),
                metadata={
                    "workspace_id": ws_id,
                    "total_runs": total_runs,
                    "failures": total_failures,
                    "tokens_in": total_tokens_in,
                    "tokens_out": total_tokens_out,
                },
            ))

        return result


# Singleton
_consolidator: Optional[MemoryConsolidator] = None


def get_consolidator() -> MemoryConsolidator:
    global _consolidator
    if _consolidator is None:
        _consolidator = MemoryConsolidator()
    return _consolidator
