"""OrganizationStateManager — workspace-level intelligence from existing data.

Phase 18: reads OrganizationRun, SessionEvent, MemoryItem, Teammate
performance to build a persistent-state summary (no new ORM, no new tables).

Ponytail: read-only aggregation, no caching. Cache via cron/event if
called in hot path (>1 req/s per workspace).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export from registry.py (Phase 1.5 backward compat)
from .registry import OrganizationStateService  # noqa: F401

logger = logging.getLogger(__name__)


class OrganizationStateManager:
    """Build organization-level intelligence from persisted data.

    build_state(workspace_id) reads teammates + memories + runs to
    produce a cross-run summary dict consumed by DecisionEngine.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_state(self, workspace_id: str) -> dict:
        """Aggregate cross-run intelligence for a workspace.

        Returns:
            {
                "preferred_roles": {role: {count, avg_success_rate}},
                "successful_patterns": [str, ...],       # top 10
                "failure_patterns": [str, ...],           # top 10
                "team_strengths": {strength: frequency},   # top 10
                "team_weaknesses": {weakness: frequency},  # top 10
            }
        """
        from backend.models.chat import Teammate

        # ── 1. Teammate performance ──
        result = await self.db.execute(
            select(Teammate).where(Teammate.workspace_id == workspace_id)
        )
        teammates = list(result.scalars().all())

        all_strengths: dict[str, int] = {}
        all_weaknesses: dict[str, int] = {}
        preferred_roles: dict[str, dict] = {}

        for tm in teammates:
            for s in tm.strengths or []:
                all_strengths[s] = all_strengths.get(s, 0) + 1
            for w in tm.weaknesses or []:
                all_weaknesses[w] = all_weaknesses.get(w, 0) + 1
            role = (tm.role or "assistant").lower()
            if tm.execution_count and tm.execution_count > 0:
                pref = preferred_roles.setdefault(
                    role, {"count": 0, "total_success_rate": 0.0}
                )
                pref["count"] += 1
                pref["total_success_rate"] += (tm.success_rate or 0.0)

        # Normalise preferred_roles
        normalised_roles: dict = {}
        for role, data in preferred_roles.items():
            normalised_roles[role] = {
                "count": data["count"],
                "avg_success_rate": round(
                    data["total_success_rate"] / data["count"], 2
                ),
            }

        # ── 2. Pattern extraction from MemoryItems + Teammate records ──
        success_patterns: list[str] = []
        failure_patterns: list[str] = []

        # 2a. Teammate patterns
        for tm in teammates:
            for pat in tm.learned_patterns or []:
                success_patterns.append(str(pat)[:200])
            for pat in tm.failed_patterns or []:
                failure_patterns.append(str(pat)[:200])

        # 2b. MemoryItem patterns (DECISION / EXECUTION types)
        try:
            from backend.services.memory.memory_service import get_memory_service

            mem_svc = get_memory_service()
            pattern_items = await mem_svc.query_by_types(
                ["DECISION", "EXECUTION"], limit=200
            )
            for item in pattern_items:
                meta = item.metadata or {}
                if meta.get("workspace_id") != workspace_id:
                    continue
                outcome = (
                    meta.get("result", meta.get("outcome", "")) or ""
                ).lower()
                if outcome in ("success", "completed", "ok", "passed"):
                    success_patterns.append(item.content[:200])
                elif outcome in ("failure", "failed", "error", "exception"):
                    failure_patterns.append(item.content[:200])
        except Exception:
            logger.warning(
                "[OrgState] MemoryService unavailable, skipping memory patterns"
            )

        return {
            "preferred_roles": normalised_roles,
            "successful_patterns": success_patterns[:10],
            "failure_patterns": failure_patterns[:10],
            "team_strengths": dict(
                sorted(all_strengths.items(), key=lambda x: -x[1])[:10]
            ),
            "team_weaknesses": dict(
                sorted(all_weaknesses.items(), key=lambda x: -x[1])[:10]
            ),
        }
