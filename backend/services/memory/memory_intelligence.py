"""
memory_intelligence.py — V2.7 Phase C: MemoryIntelligenceService

Orchestrates the insight generation pipeline:

  Task completion event
       ↓
  MemoryInsightEngine.analyze_task_result()
       ↓
  MemoryInsightStore.create_insights_batch()
       ↓
  Insights ready for PlannerContext consumption

Caller: MemoryEventHandler (fire-and-forget, never blocks Task lifecycle).

Constraints:
  ✅ No LLM calls
  ✅ No MAEOS, TaskExecutor, Planner core modification
  ✅ Failures are logged and swallowed — never propagate to Task
  ✅ All new logic can be disabled via enabled flag
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.memory.memory_insight import (
    MemoryInsight,
    MemoryInsightEngine,
    TaskResultSnapshot,
    InsightType,
)
from backend.services.memory.memory_insight_store import (
    MemoryInsightStore,
    get_insight_store,
)
from backend.services.task.task_state import TaskStateManager

logger = logging.getLogger("memory.intelligence")


class MemoryIntelligenceService:
    """
    Unified entry point for insight generation on task completion.

    Flow:
      1. Load task's execution results (joined with execution data)
      2. Wrap in TaskResultSnapshot adapters
      3. Run MemoryInsightEngine.generate_insights()
      4. Persist to MemoryInsightStore
      5. Log results (no return — fire-and-forget)

    Use:
        svc = MemoryIntelligenceService()
        await svc.process_task_completion(db, task_id)
    """

    def __init__(
        self,
        engine: Optional[MemoryInsightEngine] = None,
        store: Optional[MemoryInsightStore] = None,
        enabled: bool = True,
    ):
        self._engine = engine or MemoryInsightEngine()
        self._store = store or get_insight_store()
        self._state = TaskStateManager()
        self.enabled = enabled

    # ── Main entry point (fire-and-forget) ──

    async def process_task_completion(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> None:
        """
        Analyze task execution results and generate insights.

        Called fire-and-forget from MemoryEventHandler.
        All exceptions are caught and logged — never propagates.
        """
        if not self.enabled:
            logger.debug(f"[INTELLIGENCE] Disabled, skipping task {task_id}")
            return

        try:
            raw_results = await self._state.list_results_by_task(db, task_id)
            if not raw_results:
                logger.debug(f"[INTELLIGENCE] No results for task {task_id}")
                return

            snapshots = [TaskResultSnapshot(r) for r in raw_results]

            insights = await self._engine.generate_insights(snapshots)
            if not insights:
                logger.debug(f"[INTELLIGENCE] No insights for task {task_id}")
                return

            # Tag with source task
            for ins in insights:
                ins.source_task_id = task_id

            ids = await self._store.create_insights_batch(insights)

            logger.info(
                f"[INTELLIGENCE] Task {task_id}: generated "
                f"{len(ids)} insights "
                f"({len(raw_results)} results analyzed)"
            )
            for ins in insights:
                logger.debug(
                    f"  [{ins.type}] conf={ins.confidence:.2f} | {ins.content[:80]}"
                )

        except Exception as e:
            logger.warning(
                f"[INTELLIGENCE] Failed to process task {task_id}: {e}",
                exc_info=True,
            )

    # ── Standalone: add a risk insight (called from hooks) ──

    async def add_risk_insight(
        self,
        task_id: str,
        *,
        title: str = "风险警告",
        content: str = "",
        confidence: float = 0.8,
        extra_meta: Optional[dict] = None,
    ) -> Optional[str]:
        """Create and persist a RISK_WARNING insight. Returns insight id or None."""
        if not self.enabled:
            return None
        try:
            insight = MemoryInsightEngine.make_risk_insight(
                task_id=task_id,
                title=title,
                content=content,
                confidence=confidence,
                extra_meta=extra_meta,
            )
            return await self._store.create_insight(insight)
        except Exception as e:
            logger.warning(
                f"[INTELLIGENCE] Failed to add risk insight for {task_id}: {e}",
                exc_info=True,
            )
            return None

    # ── Query (delegates to store) ──

    async def list_insights(
        self,
        task_id: str = "",
        limit: int = 50,
        offset: int = 0,
        workspace_id: Optional[str] = None,
    ) -> list[MemoryInsight]:
        try:
            return await self._store.list_insights(
                task_id=task_id, limit=limit, offset=offset, workspace_id=workspace_id,
            )
        except Exception as e:
            logger.warning(f"[INTELLIGENCE] list_insights error: {e}")
            return []

    async def search_insights(
        self,
        keyword: str,
        limit: int = 20,
    ) -> list[MemoryInsight]:
        try:
            return await self._store.search_insights(keyword, limit=limit)
        except Exception as e:
            logger.warning(f"[INTELLIGENCE] search_insights error: {e}")
            return []


# ── Singleton ──

_service: Optional[MemoryIntelligenceService] = None


def get_intelligence_service() -> MemoryIntelligenceService:
    global _service
    if _service is None:
        _service = MemoryIntelligenceService()
    return _service


def reset_intelligence_service() -> None:
    global _service
    _service = None
