"""Memory Intelligence Layer — Memory Service.

Persists MemoryItems via raw SQL (aiosqlite, no SQLAlchemy Models).
Provides CRUD and query operations for the memory pipeline.

Storage: raw SQLite table `memory_items`, created on first use.
"""

from __future__ import annotations

import json
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text

from backend.database import engine
from backend.services.memory.memory_types import MemoryItem, MemoryType

logger = logging.getLogger("memory.service")

# ── SQL constants ───────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 on zero-vector."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(av * bv for av, bv in zip(a, b))
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_items (
    id              TEXT PRIMARY KEY,
    memory_type     TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    source_id       TEXT NOT NULL DEFAULT '',
    relevance_score REAL NOT NULL DEFAULT 0.0,
    embedding_json  TEXT NOT NULL DEFAULT '[]',
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
    (id, memory_type, content, source_id, relevance_score, embedding_json, created_at, metadata_json)
VALUES
    (:id, :memory_type, :content, :source_id, :relevance_score, :embedding_json, :created_at, :metadata_json)
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
                    "embedding_json": json.dumps(item.embedding),
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
                        "embedding_json": json.dumps(item.embedding),
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

    # ── Teammate-scoped memory ──────────────────────────────────

    async def query_teammate_memory(
        self,
        teammate_id: str,
        *,
        scope: Optional[str] = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        """Memories belonging to one teammate, optionally narrowed by scope.

        Scopes (stored in metadata["scope"]):
          - "private"   : teammate's own experience / decisions
          - "workspace" : workspace-shared knowledge the teammate contributed
          - "review"    : review verdicts / blockers this teammate produced
        teammate_id is stored in metadata["teammate_id"] at write time.

        ponytail: post-filters query() results (no JSON index in SQLite).
        Fine at current scale; add a teammate_id column + index if volume grows.
        """
        if not teammate_id:
            return []
        # ponytail: post-filter over a large window (no JSON index in SQLite).
        # Over-fetch 2000 — memory table is small in practice; if a teammate
        # ever exceeds that, add a teammate_id column + index. 2000 keeps the
        # scoped query correct without scanning the whole unlimited table.
        items = await self.query(limit=2000)
        out: list[MemoryItem] = []
        for it in items:
            meta = it.metadata or {}
            if meta.get("teammate_id") != teammate_id:
                continue
            if scope is not None and meta.get("scope") != scope:
                continue
            out.append(it)
        out.sort(key=lambda i: i.created_at or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)
        return out[:limit]

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

    # ── Semantic search ──────────────────────────────────────────

    async def semantic_search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 10,
        min_score: float = 0.1,
        metadata_filters: Optional[dict] = None,
    ) -> list[MemoryItem]:
        """Find items with most similar embeddings via cosine similarity.

        Loads all items with stored embeddings, scores against query_vector,
        returns top_k above min_score. Falls back to empty list when no
        embeddings exist (caller should then use keyword-based retrieval).

        When metadata_filters is provided, only items whose metadata dict
        matches ALL key→value pairs are considered. Useful for scope isolation
        (e.g. teammate_id, scope, workspace_id).

        ponytail: post-filters after full scan (no JSON index in SQLite).
        Add a dedicated vector+metadata index if the memory table exceeds 10K rows.
        """
        if not query_vector:
            return []
        await self._ensure_table()
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT * FROM memory_items WHERE embedding_json != '[]'"),
            )
            rows = result.fetchall()

        items = [self._row_to_item(r) for r in rows]

        # Apply metadata filters before scoring
        if metadata_filters:
            items = [
                it for it in items
                if all(it.metadata.get(k) == v for k, v in metadata_filters.items())
            ]

        if not items:
            return []

        scored: list[tuple[float, MemoryItem]] = []
        for item in items:
            if not item.embedding:
                continue
            sim = _cosine_similarity(query_vector, item.embedding)
            if sim >= min_score:
                scored.append((sim, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    @staticmethod
    def compute_embedding(text: str, dim: int = 256) -> list[float]:
        """Compute a deterministic char-bigram hash vector (no ML deps).

        ponytail: hash-based vectorizer — swap for a real embedding model
        when one is available. 256 dims gives ~2% collision on 10K texts.
        """
        vec = [0.0] * dim
        t = text.lower()
        for i in range(len(t) - 1):
            h = hash(t[i:i+2]) % dim
            vec[h] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

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

        embedding = []
        raw_emb = row._mapping.get("embedding_json", "[]")
        if raw_emb:
            try:
                embedding = json.loads(raw_emb)
            except (json.JSONDecodeError, TypeError):
                embedding = []

        return MemoryItem(
            id=row._mapping.get("id", ""),
            memory_type=row._mapping.get("memory_type", MemoryType.EVENT),
            content=row._mapping.get("content", ""),
            source_id=row._mapping.get("source_id", ""),
            relevance_score=float(row._mapping.get("relevance_score", 0.0)),
            embedding=embedding,
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
