"""
runtime/execution_store.py — Execution Observability Store (v3.2)

Design:
  ExecutionRecord       — mutable data class (sync, used by executor)
  MemoryExecutionStore  — in-memory impl (for tests, backward compat)
  DBExecutionStore      — SQLite-backed impl (production default)
  get_execution_store() — returns configured store singleton

API surface unchanged from v3.1:
  create(), get(), list(status, limit, offset), stats()
  .broadcaster — SSEBroadcaster for real-time events

DBExecutionStore:
  - Uses sync SQLAlchemy engine under the hood (avoids greenlet issues
    with aiosqlite + fire-and-forget tasks)
  - create() inserts a DB row then returns ExecutionRecord
  - Mutation methods on ExecutionRecord fire _sync_callback → sync DB write
  - get()/list() read from DB fresh
  - stats() uses aggregate queries
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from sqlalchemy import create_engine, select, func, desc, delete, text
from sqlalchemy.orm import Session as SyncSession

from backend.database import async_session

logger = logging.getLogger("runtime.execution_store")


# ── Token Cost Tracking ──

# Default cost per 1K tokens (micro USD)
TOKEN_COST_MAP = {
    "openrouter/auto": {"prompt_1k": 15, "completion_1k": 60},
    "openai/gpt-4o": {"prompt_1k": 10, "completion_1k": 30},
    "openai/gpt-4o-mini": {"prompt_1k": 0.15, "completion_1k": 0.6},
    "anthropic/claude-sonnet-4": {"prompt_1k": 3, "completion_1k": 15},
    "anthropic/claude-3.5-haiku": {"prompt_1k": 0.8, "completion_1k": 4},
}


def estimate_cost_from_tokens(
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "openrouter/auto",
) -> int:
    """Estimate cost in micro USD from token counts."""
    cost_map = TOKEN_COST_MAP.get(model, TOKEN_COST_MAP["openrouter/auto"])
    prompt_cost = (prompt_tokens / 1000) * cost_map["prompt_1k"]
    completion_cost = (completion_tokens / 1000) * cost_map["completion_1k"]
    return round((prompt_cost + completion_cost) * 1_000_000)


# ── SSE Event Helpers ──


def _sse_event(event_type: str, execution_id: str, data: dict) -> str:
    """Format an SSE event string."""
    payload = {
        "type": event_type,
        "execution_id": execution_id,
        "timestamp": time.time(),
        "data": data,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ── Execution Record ──


class ExecutionRecord:
    """
    Mutable record of a single runtime execution.

    When created via DBExecutionStore, _sync_callback is set so every
    state mutation (set_running/set_completed/set_failed) triggers a
    sync DB write.  In MemoryExecutionStore _sync_callback is None.
    """
    __slots__ = (
        "execution_id", "task_id", "teammate", "model",
        "start_time", "end_time", "duration_ms",
        "status", "error",
        "prompt_tokens", "completion_tokens", "total_tokens",
        "cost_micro_usd",
        "dag_id", "dag_node_id",
        "events",
        "_sync_callback",
    )

    def __init__(
        self,
        execution_id: str = "",
        task_id: str = "",
        teammate: str = "",
        model: str = "",
        dag_id: str = "",
        dag_node_id: str = "",
    ):
        self.execution_id = execution_id or f"exec_{uuid.uuid4().hex[:12]}"
        self.task_id = task_id
        self.teammate = teammate
        self.model = model
        self.start_time = time.time()
        self.end_time = 0.0
        self.duration_ms = 0
        self.status = "PENDING"
        self.error = ""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.cost_micro_usd = 0
        self.dag_id = dag_id
        self.dag_node_id = dag_node_id
        self.events: list[dict] = []
        self._sync_callback = None  # set by DBExecutionStore

    def set_running(self) -> None:
        self.status = "RUNNING"
        self.start_time = time.time()
        self._add_event("runtime_start", {
            "task_id": self.task_id,
            "teammate": self.teammate,
        })
        self._sync()

    def set_teammate_start(self, teammate: str) -> None:
        self.teammate = teammate
        self._add_event("teammate_start", {"teammate": teammate})
        self._sync()

    def add_tool_call(self, tool: str, input_preview: str = "") -> None:
        self._add_event("tool_call", {"tool": tool, "input_preview": input_preview})
        self._sync()

    def set_completed(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self.status = "COMPLETED"
        self.end_time = time.time()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.cost_micro_usd = estimate_cost_from_tokens(
            prompt_tokens, completion_tokens, self.model,
        )
        self._add_event("runtime_complete", {
            "status": "COMPLETED",
            "duration_ms": self.duration_ms,
            "total_tokens": self.total_tokens,
            "cost_micro_usd": self.cost_micro_usd,
        })
        self._sync()

    def set_failed(self, error: str) -> None:
        self.status = "FAILED"
        self.end_time = time.time()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)
        self.error = error[:500]
        self._add_event("runtime_complete", {
            "status": "FAILED",
            "error": self.error,
            "duration_ms": self.duration_ms,
        })
        self._sync()

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "teammate": self.teammate,
            "model": self.model,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error[:200] if self.error else "",
            "token_usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
            "cost_micro_usd": self.cost_micro_usd,
            "dag_id": self.dag_id,
            "dag_node_id": self.dag_node_id,
            "events": self.events,
        }

    def to_summary(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id[:12] if self.task_id else "",
            "teammate": self.teammate,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "total_tokens": self.total_tokens,
            "dag_id": self.dag_id,
            "dag_node_id": self.dag_node_id,
        }

    def _add_event(self, event_type: str, data: dict) -> None:
        self.events.append({
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        })

    def _sync(self) -> None:
        """Sync DB write via callback (set by DBExecutionStore)."""
        if self._sync_callback is not None:
            self._sync_callback(self)


# ── SSE Broadcaster ──


class SSESubscriber:
    """A single SSE subscriber with an async queue."""

    def __init__(self):
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.created_at = time.time()


class SSEBroadcaster:
    """
    Pub/sub for real-time execution events.

    Each execution can have multiple subscribers.
    Subscribers get events pushed to their async queue.
    """

    def __init__(self):
        self._subscribers: dict[str, list[SSESubscriber]] = {}

    def subscribe(self, execution_id: str) -> SSESubscriber:
        sub = SSESubscriber()
        if execution_id not in self._subscribers:
            self._subscribers[execution_id] = []
        self._subscribers[execution_id].append(sub)
        return sub

    def unsubscribe(self, execution_id: str, sub: SSESubscriber) -> None:
        subs = self._subscribers.get(execution_id, [])
        if sub in subs:
            subs.remove(sub)
        if not self._subscribers.get(execution_id):
            self._subscribers.pop(execution_id, None)

    async def publish(self, execution_id: str, event_type: str, data: dict) -> None:
        event = _sse_event(event_type, execution_id, data)
        subs = self._subscribers.get(execution_id, [])
        for sub in list(subs):
            try:
                await asyncio.wait_for(sub.queue.put(event), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                pass

    @property
    def active_subscriptions(self) -> int:
        return sum(len(subs) for subs in self._subscribers.values())


# ── Global SSE Broadcaster ──

_global_broadcaster: Optional[SSEBroadcaster] = None


def get_sse_broadcaster() -> SSEBroadcaster:
    global _global_broadcaster
    if _global_broadcaster is None:
        _global_broadcaster = SSEBroadcaster()
    return _global_broadcaster


# ── Memory Execution Store (legacy, for tests) ──


class MemoryExecutionStore:
    """
    In-memory execution store with optional max size.

    Thread-safe for async use (single event loop).
    Used when AI_TEAM_HUB_STORE=memory.
    """

    def __init__(self, max_size: int = 2000):
        self._records: dict[str, ExecutionRecord] = {}
        self._max_size = max_size
        self._broadcaster = get_sse_broadcaster()

    def create(
        self,
        execution_id: str = "",
        task_id: str = "",
        teammate: str = "",
        model: str = "",
        dag_id: str = "",
        dag_node_id: str = "",
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            execution_id=execution_id,
            task_id=task_id,
            teammate=teammate,
            model=model,
            dag_id=dag_id,
            dag_node_id=dag_node_id,
        )
        self._records[record.execution_id] = record
        if len(self._records) > self._max_size:
            self._evict_one()
        return record

    def get(self, execution_id: str) -> Optional[ExecutionRecord]:
        return self._records.get(execution_id)

    def list(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRecord]:
        records = list(self._records.values())
        if status:
            records = [r for r in records if r.status == status.upper()]
        records.sort(key=lambda r: r.start_time, reverse=True)
        return records[offset:offset + limit]

    def stats(self) -> dict:
        records = list(self._records.values())
        total = len(records)
        completed = sum(1 for r in records if r.status == "COMPLETED")
        failed = sum(1 for r in records if r.status == "FAILED")
        total_tokens = sum(r.total_tokens for r in records)
        total_cost = sum(r.cost_micro_usd for r in records)
        return {
            "total_executions": total,
            "completed": completed,
            "failed": failed,
            "running": sum(1 for r in records if r.status == "RUNNING"),
            "total_tokens": total_tokens,
            "total_cost_micro_usd": total_cost,
            "active_sse_subscriptions": self._broadcaster.active_subscriptions,
        }

    # ── Async wrappers (for routes that call the async API) ──

    async def aget(self, execution_id: str) -> Optional[ExecutionRecord]:
        return self.get(execution_id)

    async def alist(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRecord]:
        return self.list(status=status, limit=limit, offset=offset)

    async def astats(self) -> dict:
        return self.stats()

    @property
    def broadcaster(self) -> SSEBroadcaster:
        return self._broadcaster

    def _evict_one(self) -> None:
        candidates = [
            r for r in self._records.values()
            if r.status in ("COMPLETED", "FAILED")
        ]
        if candidates:
            oldest = min(candidates, key=lambda r: r.end_time)
            self._records.pop(oldest.execution_id, None)


# ── Helpers ──


def _record_from_db(row) -> ExecutionRecord:
    """Reconstruct ExecutionRecord from a DB model row + events."""
    import json as _json

    rec = ExecutionRecord(execution_id=row.execution_id)
    rec.task_id = row.task_id or ""
    rec.teammate = row.teammate or ""
    rec.model = row.model or ""
    rec.start_time = row.start_time or time.time()
    rec.end_time = row.end_time or 0.0
    rec.duration_ms = row.duration_ms or 0
    rec.status = row.status or "PENDING"
    rec.error = row.error or ""
    rec.prompt_tokens = row.prompt_tokens or 0
    rec.completion_tokens = row.completion_tokens or 0
    rec.total_tokens = row.total_tokens or 0
    rec.cost_micro_usd = row.cost_micro_usd or 0
    rec.dag_id = getattr(row, 'dag_id', '') or ''
    rec.dag_node_id = getattr(row, 'dag_node_id', '') or ''
    rec.events = []
    for evt in (row.events or []):
        payload = evt.payload
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload)
            except (_json.JSONDecodeError, TypeError):
                payload = {}
        rec.events.append({
            "type": evt.event_type,
            "timestamp": evt.timestamp,
            "data": payload if isinstance(payload, dict) else {},
        })
    return rec


# ── DB Execution Store (production default) ──


class DBExecutionStore:
    """
    SQLAlchemy-backed execution store.

    Uses sync engine internally (avoiding aiosqlite greenlet issues).
    Async paths (aget/alist/astats) run DB operations via the sync
    engine inside asyncio.to_thread so FastAPI route handlers can await.

    Every create() inserts a row and attaches _sync_callback so
    subsequent set_running/set_completed/set_failed persist to DB.
    """

    def __init__(self, db_url: str = ""):
        """
        db_url: optional SQLAlchemy DB URL.  Defaults to the project DB.
        For tests, pass "sqlite:///:memory:".
        """
        self._db_url = db_url or self._resolve_db_url()
        connect_args = {"check_same_thread": False} if "sqlite" in self._db_url else {}
        poolclass = None
        if "sqlite" in self._db_url and ":memory:" in self._db_url:
            from sqlalchemy.pool import StaticPool
            poolclass = StaticPool  # :memory: is per-connection; StaticPool keeps one connection
        self._engine = create_engine(
            self._db_url,
            echo=False,
            connect_args=connect_args,
            poolclass=poolclass,
        )
        # Create tables if they don't exist
        from backend.models import ExecutionRecordModel, ExecutionEventModel  # noqa: F401
        from backend.database import Base
        Base.metadata.create_all(self._engine)

        self._broadcaster = get_sse_broadcaster()

    @staticmethod
    def _resolve_db_url() -> str:
        """Build sync DB URL from configuration."""
        from backend.database import get_sync_db_url
        url = get_sync_db_url()
        # Only append SQLite query args when using SQLite
        if "sqlite" in url:
            url += "?journal_mode=WAL&timeout=10000"
        return url

    # ── Public API ──

    def create(
        self,
        execution_id: str = "",
        task_id: str = "",
        teammate: str = "",
        model: str = "",
        dag_id: str = "",
        dag_node_id: str = "",
    ) -> ExecutionRecord:
        from backend.models import ExecutionRecordModel

        rec = ExecutionRecord(
            execution_id=execution_id,
            task_id=task_id,
            teammate=teammate,
            model=model,
            dag_id=dag_id,
            dag_node_id=dag_node_id,
        )
        rec._sync_callback = self._do_sync

        # Insert row immediately (single-row INSERT is fast, no need to thread)
        def _insert():
            try:
                with SyncSession(self._engine) as session:
                    session.add(ExecutionRecordModel(
                        execution_id=rec.execution_id,
                        task_id=rec.task_id,
                        teammate=rec.teammate,
                        model=rec.model,
                        dag_id=rec.dag_id,
                        dag_node_id=rec.dag_node_id,
                        status=rec.status,
                        start_time=rec.start_time,
                        end_time=rec.end_time,
                        duration_ms=rec.duration_ms,
                        prompt_tokens=rec.prompt_tokens,
                        completion_tokens=rec.completion_tokens,
                        total_tokens=rec.total_tokens,
                        cost_micro_usd=rec.cost_micro_usd,
                        error=rec.error,
                    ))
                    session.commit()
            except Exception as e:
                logger.warning("[DBStore] create insert failed: %s", e)

        _insert()
        return rec

    # noinspection PyMethodMayBeStatic
    def _do_sync(self, rec: ExecutionRecord) -> None:
        """Sync ExecutionRecord state to DB — runs inline (single-row UPDATE is fast)."""
        from backend.models import ExecutionRecordModel, ExecutionEventModel

        try:
            with SyncSession(self._engine) as session:
                row = session.get(ExecutionRecordModel, rec.execution_id)
                if row is None:
                    return
                row.task_id = rec.task_id
                row.teammate = rec.teammate
                row.model = rec.model
                row.status = rec.status
                row.start_time = rec.start_time
                row.end_time = rec.end_time
                row.duration_ms = rec.duration_ms
                row.prompt_tokens = rec.prompt_tokens
                row.completion_tokens = rec.completion_tokens
                row.total_tokens = rec.total_tokens
                row.cost_micro_usd = rec.cost_micro_usd
                row.error = rec.error

                # Sync events
                existing = {e.event_type: e for e in row.events}
                for evt in rec.events:
                    if evt["type"] not in existing:
                        row.events.append(ExecutionEventModel(
                            execution_id=rec.execution_id,
                            event_type=evt["type"],
                            timestamp=evt.get("timestamp", time.time()),
                            payload=evt.get("data", {}),
                        ))
                session.commit()
        except Exception as e:
            logger.warning("[DBStore] _do_sync failed: %s", e)
            asyncio.get_running_loop().run_in_executor(None, _work)
        except RuntimeError:
            _work()  # no running loop (e.g. sync test) — run inline

    def get(self, execution_id: str) -> Optional[ExecutionRecord]:
        """Get execution record with events (async-friendly: runs in thread)."""
        # Sync version doesn't make sense here since callers use async
        raise NotImplementedError("Use async version: await store.aget(execution_id)")

    async def aget(self, execution_id: str) -> Optional[ExecutionRecord]:
        """Async get — calls sync method directly (SQLite fast enough)."""
        return self._get_sync(execution_id)

    def _get_sync(self, execution_id: str) -> Optional[ExecutionRecord]:
        """Sync implementation of aget."""
        from backend.models import ExecutionRecordModel

        try:
            with SyncSession(self._engine) as session:
                row = session.get(ExecutionRecordModel, execution_id)
                if row is None:
                    return None
                # Eager-load events
                from sqlalchemy.orm import selectinload
                from sqlalchemy import select as sa_select
                stmt = (
                    sa_select(ExecutionRecordModel)
                    .where(ExecutionRecordModel.execution_id == execution_id)
                    .options(selectinload(ExecutionRecordModel.events))
                )
                result = session.execute(stmt)
                row = result.scalars().first()
                if row is None:
                    return None
                return _record_from_db(row)
        except Exception as e:
            logger.warning("[DBStore] _get_sync failed: %s", e)
            return None

    def list(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRecord]:
        raise NotImplementedError("Use async version: await store.alist(...)")

    async def alist(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRecord]:
        """Async list — calls sync method directly."""
        return self._list_sync(status, limit, offset)

    def _list_sync(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionRecord]:
        """Sync implementation of alist."""
        from backend.models import ExecutionRecordModel
        from sqlalchemy.orm import selectinload

        try:
            with SyncSession(self._engine) as session:
                stmt = select(ExecutionRecordModel)
                if status:
                    stmt = stmt.where(
                        ExecutionRecordModel.status == status.upper()
                    )
                stmt = (
                    stmt
                    .options(selectinload(ExecutionRecordModel.events))
                    .order_by(desc(ExecutionRecordModel.start_time))
                    .offset(offset)
                    .limit(limit)
                )
                result = session.execute(stmt)
                rows = result.scalars().all()
                return [_record_from_db(r) for r in rows]
        except Exception as e:
            logger.warning("[DBStore] _list_sync failed: %s", e)
            return []

    async def astats(self) -> dict:
        """Async aggregate stats — calls sync method directly."""
        return self._stats_sync()

    def _stats_sync(self) -> dict:
        """Sync implementation of stats."""
        from backend.models import ExecutionRecordModel

        try:
            with SyncSession(self._engine) as session:
                total = session.scalar(
                    select(func.count(ExecutionRecordModel.execution_id))
                ) or 0
                completed = session.scalar(
                    select(func.count(ExecutionRecordModel.execution_id)).where(
                        ExecutionRecordModel.status == "COMPLETED"
                    )
                ) or 0
                failed = session.scalar(
                    select(func.count(ExecutionRecordModel.execution_id)).where(
                        ExecutionRecordModel.status == "FAILED"
                    )
                ) or 0
                running = session.scalar(
                    select(func.count(ExecutionRecordModel.execution_id)).where(
                        ExecutionRecordModel.status == "RUNNING"
                    )
                ) or 0
                total_tokens = session.scalar(
                    select(func.coalesce(func.sum(ExecutionRecordModel.total_tokens), 0))
                ) or 0
                total_cost = session.scalar(
                    select(func.coalesce(func.sum(ExecutionRecordModel.cost_micro_usd), 0))
                ) or 0

                return {
                    "total_executions": total,
                    "completed": completed,
                    "failed": failed,
                    "running": running,
                    "total_tokens": total_tokens,
                    "total_cost_micro_usd": total_cost,
                    "active_sse_subscriptions": self._broadcaster.active_subscriptions,
                }
        except Exception as e:
            logger.warning("[DBStore] _stats_sync failed: %s", e)
            return {
                "total_executions": 0,
                "completed": 0,
                "failed": 0,
                "running": 0,
                "total_tokens": 0,
                "total_cost_micro_usd": 0,
                "active_sse_subscriptions": 0,
            }

    def stats(self) -> dict:
        raise NotImplementedError("Use async version: await store.astats()")

    @property
    def broadcaster(self) -> SSEBroadcaster:
        return self._broadcaster


# ── Global Store Singleton ──

_global_store = None


def get_execution_store():
    """
    Return the configured execution store singleton.

    AI_TEAM_HUB_STORE=memory  → MemoryExecutionStore (tests, legacy)
    AI_TEAM_HUB_STORE=db      → DBExecutionStore (production default)
    unset                      → DBExecutionStore
    """
    global _global_store
    if _global_store is not None:
        return _global_store

    mode = os.environ.get("AI_TEAM_HUB_STORE", "db").lower()
    if mode == "memory":
        _global_store = MemoryExecutionStore()
        logger.info("ExecutionStore: MemoryExecutionStore (AI_TEAM_HUB_STORE=memory)")
    else:
        _global_store = DBExecutionStore()
        logger.info("ExecutionStore: DBExecutionStore (production)")
    return _global_store


def reset_execution_store() -> None:
    """Reset singleton (for testing)."""
    global _global_store
    _global_store = None


# Backward compat alias
ExecutionStore = MemoryExecutionStore
