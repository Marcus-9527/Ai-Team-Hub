"""
routes/traces.py — Simple request logging endpoints.

Provides:
- GET /api/traces — list recent request logs
- GET /api/traces/{channel_id} — get logs for a specific channel

FSM trace recording has been removed. Only basic request logging remains.
"""
import time
from fastapi import APIRouter, HTTPException

from backend.services.orchestrator_observability import get_observability

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("/")
async def list_traces(limit: int = 20):
    """List recent request logs."""
    obs = get_observability()
    return obs.list_logs(limit=limit)


@router.get("/{channel_id}")
async def get_trace(channel_id: str):
    """Get logs for a specific channel."""
    obs = get_observability()
    logs = obs.get_logs_for_channel(channel_id)
    if not logs:
        raise HTTPException(status_code=404, detail="No logs found for this channel")
    return {"channel_id": channel_id, "logs": logs}
