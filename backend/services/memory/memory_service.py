"""Memory Intelligence Layer — Memory Service.

Persists MemoryItems via raw SQL (aiosqlite, no SQLAlchemy Models).
Provides CRUD and query operations for the memory pipeline.

Storage: raw SQLite table `memory_items`, created on first use.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text

from backend.database import engine
from backend.services.memory.memory_types import MemoryItem, MemoryType

logger = logging.getLogger("memory.service")

# ── SQL constants ───────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_items (
    id              TEXT PRIMARY KEY,
    memory_type     TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    source_id       TEXT NOT NULL DEFAULT '',
    relevance_score REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_items(memory_type);",
    "CREATE INDEX IF NOT EXISTS idx_source_id  ON memory_items(source_id);",
    "CREATE INDEX IF NOT EXISTS idx_created_at  ON memory_items(created_at);",
]

INSERT_SQL = """
INSERT OR REPLACE INTO memory_items
    (id, memory_type, content, source_id, relevance_score, created_at, metadata_json)
VALUES
    (:id, :memory_type, :content, :source_id, :relevance_score, :created_at, :metadata_json)
"""

SELECT_BY_SCOPE_SQL = """
SELECT * FROM memory_items
WHERE (:memory_type IS NULL OR memory_type = :memory_type)
  AND (:source_id  IS NULL OR source_id = :source_id)
ORDER BY
    CASE memory_type
        WHEN 'EXECUTION' THEN 0
        WHEN 'DECISION'  THEN 1
        WHEN 'TASK'      THEN 2
        WHEN 'CHANNEL'   THEN 3
        WHEN 'WORKSPACE' THEN 4
        WHEN 'EVENT'     THEN 5
        WHEN 'GLOBAL'    THEN 6
        ELSE 99
    END,
    created_at DESC
LIMIT :limit
"""

SELECT_RECENT_SQL = """
SELECT * FROM memory_items
ORDER BY created_at DESC
LIMIT :limit
"""

SELECT_BY_IDS_SQL = """
SELECT * FROM memory_items WHERE id IN :ids
"""

DELETE_OLD_SQL = """
DELETE FROM memory_items
WHERE memory_type = :memory_type
  AND created_at < :before
"""

COUNT_SQL = """
SELECT memory_type, COUNT(*) as cnt FROM memory_items GROUP BY memory_type
"""


# ═════════════════════════════════════════════════════════════════
# MemoryService
# ═════════════════════════════════════════════════════════════════


class MemoryService:
    """Persistent memory store for MemoryItems.

    Thread-safe via async engine. Auto-creates table on first use.
    """

    def __init__(self):
        self._ready = False

    async def _ensure_table(self) -> None:
        """Create table + indexes on first use (idempotent)."""
        if self._ready:
            return
        async with engine.connect() as conn:
            await conn.execute(text(CREATE_TABLE_SQL))
            for idx_sql in CREATE_INDEX_SQL:
                await conn.execute(text(idx_sql))
            await conn.commit()
        self._ready = True
        logger.debug("memory_items table ready")

    # ── Write ─────────────────────────────────────────────────

    async def store(self, item: MemoryItem) -> str:
        """Persist a single MemoryItem. Returns its id."""
        await self._ensure_table()
        async with engine.connect() as conn:
            await conn.execute(
                text(INSERT_SQL),
                {
                    "id": item.id,
                    "memory_type": item.memory_type,
                    "content": item.content,
                    "source_id": item.source_id,
                    "relevance_score": item.relevance_score,
                    "created_at": item.created_at.isoformat(),
                    "metadata_json": json.dumps(item.metadata, ensure_ascii=False),
                },
            )
            await conn.commit()
        logger.debug(f"Stored memory {item.id} type={item.memory_type}")
        return item.id

    async def store_batch(self, items: list[MemoryItem]) -> list[str]:
        """Persist multiple items in one transaction."""
        if not items:
            return []
        await self._ensure_table()
        async with engine.connect() as conn:
            for item in items:
                await conn.execute(
                    text(INSERT_SQL),
                    {
                        "id": item.id,
                        "memory_type": item.memory_type,
                        "content": item.content,
                        "source_id": item.source_id,
                        "relevance_score": item.relevance_score,
                        "created_at": item.created_at.isoformat(),
                        "metadata_json": json.dumps(item.metadata, ensure_ascii=False),
                    },
                )
            await conn.commit()
        ids = [item.id for item in items]
        logger.debug(f"Stored {len(items)} memory items")
        return ids

    # ── Query ─────────────────────────────────────────────────

    async def query(
        self,
        *,
        memory_type: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        """Query items by type and/or source, ordered by priority + recency."""
        await self._ensure_table()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(SELECT_BY_SCOPE_SQL),
                {
                    "memory_type": memory_type,
                    "source_id": source_id,
                    "limit": limit,
                },
            )
            rows = result.fetchall()

        return [self._row_to_item(row) for row in rows]

    async def query_by_types(
        self,
        types: list[str],
        *,
        limit: int = 100,
    ) -> list[MemoryItem]:
        """Query items matching any of the given types."""
        await self._ensure_table()
        all_items: list[MemoryItem] = []
        # Naive per-type query — acceptable at small scale
        for mt in types:
            batch = await self.query(memory_type=mt, limit=limit // max(len(types), 1))
            all_items.extend(batch)
        # Sort by recency
        all_items.sort(key=lambda i: i.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return all_items[:limit]

    async def get_recent(
        self,
        limit: int = 20,
        *,
        max_hours: Optional[float] = None,
    ) -> list[MemoryItem]:
        """Get most recent memory items."""
        await self._ensure_table()
        async with engine.connect() as conn:
            result = await conn.execute(text(SELECT_RECENT_SQL), {"limit": limit})
            rows = result.fetchall()

        items = [self._row_to_item(row) for row in rows]

        if max_hours is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
            items = [i for i in items if i.created_at and i.created_at >= cutoff]

        return items

    async def get_by_ids(self, ids: list[str]) -> list[MemoryItem]:
        """Fetch specific items by id."""
        if not ids:
            return []
        await self._ensure_table()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(SELECT_BY_IDS_SQL),
                {"ids": tuple(ids)},
            )
            rows = result.fetchall()
        return [self._row_to_item(row) for row in rows]

    async def stats(self) -> dict:
        """Get storage statistics."""
        await self._ensure_table()
        async with engine.connect() as conn:
            result = await conn.execute(text(COUNT_SQL))
            rows = result.fetchall()

        by_type = {row[0]: row[1] for row in rows}
        total = sum(by_type.values())
        return {
            "total_items": total,
            "by_type": by_type,
        }

    async def prune(
        self,
        memory_type: str,
        *,
        older_than_days: int = 30,
    ) -> int:
        """Delete old items of a given type. Returns count deleted."""
        await self._ensure_table()
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        async with engine.connect() as conn:
            result = await conn.execute(
                text(DELETE_OLD_SQL),
                {
                    "memory_type": memory_type,
                    "before": cutoff.isoformat(),
                },
            )
            await conn.commit()
        deleted = result.rowcount
        if deleted:
            logger.info(f"Pruned {deleted} old {memory_type} items")
        return deleted

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _row_to_item(row) -> MemoryItem:
        """Convert a raw SQLAlchemy Row to MemoryItem."""
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

        return MemoryItem(
            id=row._mapping.get("id", ""),
            memory_type=row._mapping.get("memory_type", MemoryType.EVENT),
            content=row._mapping.get("content", ""),
            source_id=row._mapping.get("source_id", ""),
            relevance_score=float(row._mapping.get("relevance_score", 0.0)),
            created_at=created_at,
            metadata=meta,
        )


# ── Singleton ───────────────────────────────────────────────────

_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """Get the singleton MemoryService instance."""
    global _service
    if _service is None:
        _service = MemoryService()
    return _service
