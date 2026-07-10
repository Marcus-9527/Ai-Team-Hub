"""
routes/v1_observability.py — Observability API for UI consumption.

Provides structured data for:
- Task timeline view
- Team interaction flow
- Cost breakdown
- Cache hit visualization
"""
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Any, Dict, List

router = APIRouter(prefix="/v1", tags=["v1-observability"])


class TimelineResponse(BaseModel):
    request_id: str = ""
    events: List[Dict[str, Any]] = []
    total_duration_ms: float = 0


class CacheVisualizationResponse(BaseModel):
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0
    layers: List[Dict[str, Any]] = []


@router.get("/timeline/{request_id}", response_model=TimelineResponse)
async def get_task_timeline(request_id: str):
    """Get team interaction timeline for UI rendering."""
    from backend.services.orchestrator_observability import get_observability
    start = time.time()

    obs = get_observability()
    replay = obs.replay(request_id) if hasattr(obs, "replay") else {}
    events = replay.get("events", [])

    total_ms = 0
    timeline_events = []
    for ev in events:
        lat = ev.get("latency_ms", 0)
        total_ms += lat
        timeline_events.append({
            "step": ev.get("step", ""),
            "teammate": ev.get("agent", ""),
            "latency_ms": lat,
            "timestamp": ev.get("timestamp", ""),
            "phase": _classify_phase(ev.get("step", "")),
        })

    return TimelineResponse(
        request_id=request_id,
        events=timeline_events,
        total_duration_ms=round(total_ms, 2),
    )


@router.get("/cost/{request_id}")
async def get_cost_breakdown(request_id: str):
    """Get cost breakdown for a team collaboration."""
    from backend.services.orchestrator_observability import get_observability

    obs = get_observability()
    replay = obs.replay(request_id) if hasattr(obs, "replay") else {}
    events = replay.get("events", [])

    teammate_costs = {}
    total_calls = 0
    for ev in events:
        teammate = ev.get("agent", "system")
        if teammate != "system":
            total_calls += 1
            if teammate not in teammate_costs:
                teammate_costs[teammate] = {"calls": 0, "tokens_estimated": 0}
            teammate_costs[teammate]["calls"] += 1
            output_len = len(str(ev.get("output_data", "")))
            teammate_costs[teammate]["tokens_estimated"] += output_len // 4

    return {
        "request_id": request_id,
        "total_calls": total_calls,
        "breakdown": teammate_costs,
        "total_estimated_tokens": sum(a["tokens_estimated"] for a in teammate_costs.values()),
        "note": "Cost estimation is approximate. Actual billing depends on model pricing.",
    }


@router.get("/cache/vis", response_model=CacheVisualizationResponse)
async def get_cache_visualization():
    """Get cache hit/miss data for visualization."""
    from backend.cache import teammate_cache, channel_cache, apikey_cache, message_cache

    caches = [
        ("teammate", teammate_cache),
        ("channel", channel_cache),
        ("apikey", apikey_cache),
        ("message", message_cache),
    ]

    total_hits = 0
    total_misses = 0
    layers = []

    for name, cache in caches:
        h = cache.stats.get("hits", 0)
        m = cache.stats.get("misses", 0)
        total = h + m
        rate = round(h / total * 100, 1) if total > 0 else 0

        total_hits += h
        total_misses += m

        layers.append({
            "name": name,
            "hits": h,
            "misses": m,
            "hit_rate": rate,
            "total": total,
        })

    grand_total = total_hits + total_misses
    overall_rate = round(total_hits / grand_total * 100, 1) if grand_total > 0 else 0

    return CacheVisualizationResponse(
        hits=total_hits,
        misses=total_misses,
        hit_rate=overall_rate,
        layers=layers,
    )


@router.get("/team/interactions/{request_id}")
async def get_team_interactions(request_id: str):
    """Get team member interaction flow for a request."""
    from backend.services.orchestrator_observability import get_observability

    obs = get_observability()
    replay = obs.replay(request_id) if hasattr(obs, "replay") else {}
    events = replay.get("events", [])

    interactions = []
    for ev in events:
        step = ev.get("step", "")
        if step.startswith("fsm_") or step in ("fsm_completed", "init"):
            interactions.append({
                "step": step.replace("fsm_", ""),
                "state": step.replace("fsm_", ""),
                "latency_ms": ev.get("latency_ms", 0),
                "teammate": ev.get("agent", "system"),
            })

    return {
        "request_id": request_id,
        "interactions": interactions,
        "final_state": interactions[-1]["state"] if interactions else "unknown",
        "total_interactions": len(interactions),
    }


@router.get("/system/summary")
async def get_system_summary():
    """Get overall system summary for dashboard."""
    from backend.services.orchestrator_observability import get_observability
    from backend.cache import teammate_cache, channel_cache, apikey_cache, message_cache

    obs = get_observability()

    trace_count = len(obs._traces) if hasattr(obs, "_traces") else 0

    return {
        "system": "AI Team Hub",
        "version": "2.1.0",
        "total_traces": trace_count,
        "cache_summary": {
            "teammate_cache": teammate_cache.stats,
            "channel_cache": channel_cache.stats,
            "apikey_cache": apikey_cache.stats,
            "message_cache": message_cache.stats,
        },
        "active_components": {
            "observability": True,
            "team_engine": True,
            "workspace_manager": True,
            "cache_kernel": True,
        },
    }


def _classify_phase(step: str) -> str:
    """Classify a step into a UI-friendly phase."""
    step_lower = step.lower()
    if "init" in step_lower or "classif" in step_lower:
        return "initialization"
    if "plan" in step_lower or "strategy" in step_lower:
        return "planning"
    if "execut" in step_lower or "engineer" in step_lower:
        return "execution"
    if "review" in step_lower or "valid" in step_lower or "quality" in step_lower:
        return "review"
    if "divers" in step_lower:
        return "diversity"
    if "cache" in step_lower:
        return "cache"
    if "fsm" in step_lower or "complete" in step_lower:
        return "completion"
    return "processing"
