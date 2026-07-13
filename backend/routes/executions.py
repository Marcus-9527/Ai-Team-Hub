"""
routes/executions.py — Execution Observability API (v3.2)

Provides:
  GET  /api/executions              — List executions (filterable)
  GET  /api/executions/{id}         — Get full execution record
  GET  /api/executions/{id}/stream  — SSE real-time event stream
  GET  /api/executions/stats        — Aggregate execution stats

Now backed by DBExecutionStore by default (configurable via env).
API surface unchanged.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.services.runtime.execution_store import (
    get_execution_store,
    get_sse_broadcaster,
    ExecutionRecord,
)

logger = logging.getLogger("routes.executions")
router = APIRouter(prefix="/api/executions", tags=["executions"])


def _get_store():
    return get_execution_store()


# ── List ──


@router.get("")
async def list_executions(
    status: Optional[str] = Query(None, description="Filter by status (COMPLETED/FAILED/RUNNING/PENDING)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List execution records, newest first."""
    store = _get_store()
    records = await store.alist(status=status, limit=limit, offset=offset)
    return {
        "executions": [r.to_summary() for r in records],
        "total": len(records),
        "limit": limit,
        "offset": offset,
    }


# ── Stats ──


@router.get("/stats")
async def execution_stats():
    """Aggregate execution statistics."""
    store = _get_store()
    return await store.astats()


# ── Get Single ──


@router.get("/{execution_id}")
async def get_execution(execution_id: str):
    """Get full execution record with event timeline."""
    store = _get_store()
    record = await store.aget(execution_id)
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")
    return record.to_dict()


# ── SSE Stream ──


@router.get("/{execution_id}/stream")
async def stream_execution(execution_id: str):
    """
    SSE real-time event stream for an execution.
    """
    store = _get_store()
    record = await store.aget(execution_id)

    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")

    broadcaster = get_sse_broadcaster()
    sub = broadcaster.subscribe(execution_id)

    async def event_stream():
        try:
            # First, replay past events
            for evt in record.events:
                yield _sse_line(evt["type"], execution_id, evt["data"])

            # If already terminated, close stream
            if record.status in ("COMPLETED", "FAILED"):
                yield _sse_line("stream_end", execution_id, {"reason": "execution_completed"})
                return

            # Wait for new events
            import asyncio
            deadline = asyncio.get_event_loop().time() + 300  # 5 min timeout

            while asyncio.get_event_loop().time() < deadline:
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=30)
                    yield event

                    parsed = json.loads(event[5:].strip())
                    if parsed.get("type") == "runtime_complete":
                        yield _sse_line("stream_end", execution_id, {"reason": "execution_completed"})
                        return
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

            yield _sse_line("stream_end", execution_id, {"reason": "timeout"})

        finally:
            broadcaster.unsubscribe(execution_id, sub)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_line(event_type: str, execution_id: str, data: dict) -> str:
    """Format a single SSE event line."""
    if not data.get("timestamp"):
        import time
        data["timestamp"] = time.time()
    payload = {
        "type": event_type,
        "execution_id": execution_id,
        "timestamp": data.pop("timestamp", None),
        "data": data,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
