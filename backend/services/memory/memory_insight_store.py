"""
memory_insight_store.py — V2.7 Phase C: MemoryInsight Persistence

Raw SQLite persistence for MemoryInsight records.
No SQLAlchemy Models — uses aiosqlite through the existing async engine.

Table: memory_insights
  id                  TEXT PRIMARY KEY
  type                TEXT NOT NULL
  title               TEXT NOT NULL DEFAULT ''
  content             TEXT NOT NULL DEFAULT ''
  source_task_id      TEXT NOT NULL DEFAULT ''
  source_execution_id TEXT NOT NULL DEFAULT ''
  confidence          REAL NOT NULL DEFAULT 0.0
  created_at          TEXT NOT NULL
  metadata_json       TEXT NOT NULL DEFAULT '{}'

Constraints:
  ✅ No Task Model reuse
  ✅ Same engine/session pattern as MemoryService
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from backend.database import engine
from backend.services.memory.memory_insight import MemoryInsight, InsightType

logger = logging.getLogger("memory.insight_store")


# ── SQL constants ───────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_insights (
    id                  TEXT PRIMARY KEY,
    type                TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    content             TEXT NOT NULL DEFAULT '',
    source_task_id      TEXT NOT NULL DEFAULT '',
    source_execution_id TEXT NOT NULL DEFAULT '',
    confidence          REAL NOT NULL DEFAULT 0.0,
    created_at          TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_insight_type         ON memory_insights(type);",
    "CREATE INDEX IF NOT EXISTS idx_insight_source_task  ON memory_insights(source_task_id);",
    "CREATE INDEX IF NOT EXISTS idx_insight_created_at   ON memory_insights(created_at);",
]

INSERT_SQL = """
INSERT OR REPLACE INTO memory_insights
    (id, type, title, content, source_task_id, source_execution_id,
     confidence, created_at, metadata_json)
VALUES
    (:id, :type, :title, :content, :source_task_id, :source_execution_id,
     :confidence, :created_at, :metadata_json)
"""

SELECT_BY_TASK_SQL = """
SELECT * FROM memory_insights
WHERE (source_task_id = :task_id OR :task_id = '')
ORDER BY
    CASE type
        WHEN 'RISK_WARNING'     THEN 0
        WHEN 'FAILURE_PATTERN'  THEN 1
        WHEN 'OPTIMIZATION'     THEN 2
        WHEN 'SUCCESS_PATTERN'  THEN 3
        ELSE 99
    END,
    created_at DESC
LIMIT :limit
OFFSET :offset
"""

SELECT_BY_TYPE_SQL = """
SELECT * FROM memory_insights
WHERE type = :type
ORDER BY confidence DESC, created_at DESC
LIMIT :limit
"""

SELECT_RECENT_SQL = """
SELECT * FROM memory_insights
ORDER BY created_at DESC
LIMIT :limit
"""

SELECT_BY_IDS_SQL = """
SELECT * FROM memory_insights WHERE id IN ({})
"""

DELETE_OLD_SQL = """
DELETE FROM memory_insights
WHERE created_at < :before
"""

COUNT_SQL = """
SELECT type, COUNT(*) as cnt FROM memory_insights GROUP BY type
"""

SEARCH_SQL = """
SELECT * FROM memory_insights
WHERE content LIKE :keyword
   OR title   LIKE :keyword
ORDER BY confidence DESC, created_at DESC
LIMIT :limit
"""


# ═════════════════════════════════════════════════════════════════
# MemoryInsightStore
# ═════════════════════════════════════════════════════════════════


class MemoryInsightStore:
    """
    Persistent store for MemoryInsight records.

    Thread-safe via async engine. Auto-creates table on first use.
    """

    def __init__(self):
        self._ready = False

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with engine.connect() as conn:
            await conn.execute(text(CREATE_TABLE_SQL))
            for idx_sql in CREATE_INDEX_SQL:
                await conn.execute(text(idx_sql))
            await conn.commit()
        self._ready = True
        logger.debug("memory_insights table ready")

    # ── Write ──

    async def create_insight(self, insight: MemoryInsight) -> str:
        """Persist a single MemoryInsight. Returns its id."""
        await self._ensure_table()
        async with engine.connect() as conn:
            await conn.execute(
                text(INSERT_SQL),
                {
                    "id": insight.id,
                    "type": insight.type,
                    "title": insight.title,
                    "content": insight.content,
                    "source_task_id": insight.source_task_id,
                    "source_execution_id": insight.source_execution_id,
                    "confidence": insight.confidence,
                    "created_at": insight.created_at.isoformat(),
                    "metadata_json": json.dumps(insight.metadata, ensure_ascii=False),
                },
            )
            await conn.commit()
        logger.debug(f"[INSIGHT] stored {insight.id} type={insight.type}")
        return insight.id

    async def create_insights_batch(self, insights: list[MemoryInsight]) -> list[str]:
        """Persist multiple insights in one transaction."""
        if not insights:
            return []
        await self._ensure_table()
        async with engine.connect() as conn:
            for ins in insights:
                await conn.execute(
                    text(INSERT_SQL),
                    {
                        "id": ins.id,
                        "type": ins.type,
                        "title": ins.title,
                        "content": ins.content,
                        "source_task_id": ins.source_task_id,
                        "source_execution_id": ins.source_execution_id,
                        "confidence": ins.confidence,
                        "created_at": ins.created_at.isoformat(),
                        "metadata_json": json.dumps(ins.metadata, ensure_ascii=False),
                    },
                )
            await conn.commit()
        ids = [ins.id for ins in insights]
        logger.debug(f"[INSIGHT] stored batch {len(insights)} items")
        return ids

    # ── Query ──

    async def list_insights(
        self,
        *,
        task_id: str = "",
        limit: int = 50,
        offset: int = 0,
        workspace_id: Optional[str] = None,
    ) -> list[MemoryInsight]:
        """List insights by task (or all if task_id empty), optionally filtered by workspace_id."""
        await self._ensure_table()
        if workspace_id:
            sql = """
                SELECT * FROM memory_insights
                WHERE (:task_id = '' OR source_task_id = :task_id)
                  AND json_extract(metadata_json, '$.workspace_id') = :ws
                ORDER BY
                    CASE type
                        WHEN 'RISK_WARNING'     THEN 0
                        WHEN 'FAILURE_PATTERN'  THEN 1
                        WHEN 'OPTIMIZATION'     THEN 2
                        WHEN 'SUCCESS_PATTERN'  THEN 3
                        ELSE 99
                    END,
                    created_at DESC
                LIMIT :limit
                OFFSET :offset
            """
        else:
            sql = SELECT_BY_TASK_SQL
        async with engine.connect() as conn:
            result = await conn.execute(
                text(sql),
                {"task_id": task_id, "limit": limit, "offset": offset, "ws": workspace_id}
                if workspace_id
                else {"task_id": task_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()
        return [self._row_to_insight(row) for row in rows]

    async def list_by_type(
        self,
        insight_type: str,
        *,
        limit: int = 20,
    ) -> list[MemoryInsight]:
        """List insights of a specific type, by confidence desc."""
        await self._ensure_table()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(SELECT_BY_TYPE_SQL),
                {"type": insight_type, "limit": limit},
            )
            rows = result.fetchall()
        return [self._row_to_insight(row) for row in rows]

    async def get_recent(self, limit: int = 20, *, workspace_id: Optional[str] = None) -> list[MemoryInsight]:
        """Get most recent insights, optionally filtered by workspace_id."""
        await self._ensure_table()
        if workspace_id:
            sql = """
                SELECT * FROM memory_insights
                WHERE json_extract(metadata_json, '$.workspace_id') = :ws
                ORDER BY created_at DESC
                LIMIT :limit
            """
        else:
            sql = SELECT_RECENT_SQL
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), {"limit": limit, "ws": workspace_id} if workspace_id else {"limit": limit})
            rows = result.fetchall()
        return [self._row_to_insight(row) for row in rows]

    async def get_by_ids(self, ids: list[str]) -> list[MemoryInsight]:
        """Fetch specific insights by id."""
        if not ids:
            return []
        await self._ensure_table()
        placeholders = ",".join([f":id_{i}" for i in range(len(ids))])
        params = {f"id_{i}": v for i, v in enumerate(ids)}
        async with engine.connect() as conn:
            result = await conn.execute(
                text(SELECT_BY_IDS_SQL.format(placeholders)),
                params,
            )
            rows = result.fetchall()
        return [self._row_to_insight(row) for row in rows]

    async def search_insights(
        self,
        keyword: str,
        *,
        limit: int = 20,
    ) -> list[MemoryInsight]:
        """Search insights by keyword in content/title."""
        await self._ensure_table()
        like_pattern = f"%{keyword}%"
        async with engine.connect() as conn:
            result = await conn.execute(
                text(SEARCH_SQL),
                {"keyword": like_pattern, "limit": limit},
            )
            rows = result.fetchall()
        return [self._row_to_insight(row) for row in rows]

    async def stats(self) -> dict:
        """Get storage statistics."""
        await self._ensure_table()
        async with engine.connect() as conn:
            result = await conn.execute(text(COUNT_SQL))
            rows = result.fetchall()
        by_type = {row[0]: row[1] for row in rows}
        return {"total": sum(by_type.values()), "by_type": by_type}

    async def prune(self, *, older_than_days: int = 60) -> int:
        """Delete old insights. Returns count deleted."""
        await self._ensure_table()
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        async with engine.connect() as conn:
            result = await conn.execute(
                text(DELETE_OLD_SQL),
                {"before": cutoff.isoformat()},
            )
            await conn.commit()
        deleted = result.rowcount
        if deleted:
            logger.info(f"[INSIGHT] Pruned {deleted} old insights")
        return deleted

    # ── Helpers ──

    @staticmethod
    def _row_to_insight(row) -> MemoryInsight:
        created_at = datetime.now(timezone.utc)
        raw_dt = row._mapping.get("created_at")
        if raw_dt:
            try:
                created_at = datetime.fromisoformat(raw_dt)
            except (ValueError, TypeError):
                pass

        meta = {}
        raw_meta = row._mapping.get("metadata_json", "{}")
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}

        return MemoryInsight(
            id=row._mapping.get("id", ""),
            type=row._mapping.get("type", InsightType.SUCCESS_PATTERN),
            title=row._mapping.get("title", ""),
            content=row._mapping.get("content", ""),
            source_task_id=row._mapping.get("source_task_id", ""),
            source_execution_id=row._mapping.get("source_execution_id", ""),
            confidence=float(row._mapping.get("confidence", 0.0)),
            created_at=created_at,
            metadata=meta,
        )


# ── Singleton ──

_store: Optional[MemoryInsightStore] = None


def get_insight_store() -> MemoryInsightStore:
    global _store
    if _store is None:
        _store = MemoryInsightStore()
    return _store


def reset_insight_store() -> None:
    global _store
    _store = None
