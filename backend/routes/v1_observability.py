"""
routes/v1_observability.py — Observability API for UI consumption.

Provides structured data for:
- Task timeline view
- Agent execution graph
- Cost breakdown
- Cache hit visualization
- FSM state transitions
"""
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Any, Dict, List

router = APIRouter(prefix="/v1", tags=["v1-observability"])


class TimelineResponse(BaseModel):
    task_id: str = ""
    events: List[Dict[str, Any]] = []
    total_duration_ms: float = 0


class AgentGraphResponse(BaseModel):
    task_id: str = ""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []


class CacheVisualizationResponse(BaseModel):
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0
    layers: List[Dict[str, Any]] = []


@router.get("/timeline/{task_id}", response_model=TimelineResponse)
async def get_task_timeline(task_id: str):
    """Get task execution timeline for UI rendering."""
    from backend.services.orchestrator_core import get_observability
    start = time.time()

    obs = get_observability()
    replay = obs.replay(task_id) if hasattr(obs, "replay") else {}
    events = replay.get("events", [])

    total_ms = 0
    timeline_events = []
    for ev in events:
        lat = ev.get("latency_ms", 0)
        total_ms += lat
        timeline_events.append({
            "step": ev.get("step", ""),
            "agent": ev.get("agent", ""),
            "latency_ms": lat,
            "timestamp": ev.get("timestamp", ""),
            "phase": _classify_phase(ev.get("step", "")),
        })

    return TimelineResponse(
        task_id=task_id,
        events=timeline_events,
        total_duration_ms=round(total_ms, 2),
    )


@router.get("/agent-graph/{task_id}", response_model=AgentGraphResponse)
async def get_agent_graph(task_id: str):
    """Get agent execution graph (nodes = agents, edges = transitions)."""
    from backend.services.orchestrator_core import get_observability

    obs = get_observability()
    replay = obs.replay(task_id) if hasattr(obs, "replay") else {}
    events = replay.get("events", [])

    nodes = []
    edges = []
    seen_agents = set()

    for i, ev in enumerate(events):
        agent = ev.get("agent", "system")
        step = ev.get("step", "")

        if agent not in seen_agents:
            seen_agents.add(agent)
            nodes.append({
                "id": agent,
                "label": agent,
                "type": "agent" if agent != "system" else "system",
                "latency_ms": ev.get("latency_ms", 0),
            })

        # Create edges between consecutive events
        if i > 0:
            prev_agent = events[i-1].get("agent", "system")
            edges.append({
                "from": prev_agent,
                "to": agent,
                "label": step,
            })

    return AgentGraphResponse(
        task_id=task_id,
        nodes=nodes,
        edges=edges,
    )


@router.get("/cost/{task_id}")
async def get_cost_breakdown(task_id: str):
    """Get cost breakdown for a task."""
    from backend.services.orchestrator_core import get_observability

    obs = get_observability()
    replay = obs.replay(task_id) if hasattr(obs, "replay") else {}
    events = replay.get("events", [])

    agent_costs = {}
    total_calls = 0
    for ev in events:
        agent = ev.get("agent", "system")
        if agent != "system":
            total_calls += 1
            if agent not in agent_costs:
                agent_costs[agent] = {"calls": 0, "tokens_estimated": 0}
            agent_costs[agent]["calls"] += 1
            # Estimate tokens from output_data length
            output_len = len(str(ev.get("output_data", "")))
            agent_costs[agent]["tokens_estimated"] += output_len // 4  # rough estimate

    return {
        "task_id": task_id,
        "total_calls": total_calls,
        "breakdown": agent_costs,
        "total_estimated_tokens": sum(a["tokens_estimated"] for a in agent_costs.values()),
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


@router.get("/fsm-transitions/{task_id}")
async def get_fsm_transitions(task_id: str):
    """Get FSM state transitions for a task."""
    from backend.services.orchestrator_core import get_observability

    obs = get_observability()
    replay = obs.replay(task_id) if hasattr(obs, "replay") else {}
    events = replay.get("events", [])

    transitions = []
    for ev in events:
        step = ev.get("step", "")
        if step.startswith("fsm_") or step in ("fsm_completed", "init"):
            transitions.append({
                "step": step,
                "state": step.replace("fsm_", ""),
                "latency_ms": ev.get("latency_ms", 0),
                "agent": ev.get("agent", "system"),
            })

    return {
        "task_id": task_id,
        "transitions": transitions,
        "final_state": transitions[-1]["state"] if transitions else "unknown",
        "total_transitions": len(transitions),
    }


@router.get("/system/summary")
async def get_system_summary():
    """Get overall system summary for dashboard."""
    from backend.services.orchestrator_core import get_observability
    from backend.cache import teammate_cache, channel_cache, apikey_cache, message_cache

    obs = get_observability()

    # Count traces
    trace_count = len(obs._traces) if hasattr(obs, "_traces") else 0

    return {
        "system": "AI Team Hub",
        "version": "2.0.0",
        "total_traces": trace_count,
        "cache_summary": {
            "teammate_cache": teammate_cache.stats,
            "channel_cache": channel_cache.stats,
            "apikey_cache": apikey_cache.stats,
            "message_cache": message_cache.stats,
        },
        "active_components": {
            "observability": True,
            "fsm_orchestrator": True,
            "maeos": True,
            "workspace_manager": True,
            "cache_kernel": True,
        },
    }


def _classify_phase(step: str) -> str:
    """Classify a step into a UI-friendly phase."""
    step_lower = step.lower()
    if "init" in step_lower or "classif" in step_lower:
        return "initialization"
    if "plan" in step_lower:
        return "planning"
    if "execut" in step_lower:
        return "execution"
    if "review" in step_lower or "valid" in step_lower:
        return "review"
    if "divers" in step_lower:
        return "diversity"
    if "cache" in step_lower:
        return "cache"
    if "fsm" in step_lower or "complete" in step_lower:
        return "completion"
    return "processing"
