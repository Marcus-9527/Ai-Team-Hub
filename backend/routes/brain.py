"""routes/brain.py — Brain API (Phase 6 + Phase 12).

Aggregates: memory, insights, evaluations, brain fragments, brain loader.
All routes are read/query — writes happen through hooks and reflection.

Ponytail: Brain is a label on existing subsystems. This file IS the delta.
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query

from backend.services.memory.memory_service import get_memory_service
from backend.services.memory.memory_intelligence import get_intelligence_service
from backend.services.evaluation import EvaluationService
from backend.database import async_session
from backend.services.brain.fragment_store import (
    get_brain_fragment_store,
    BrainFragmentType,
)
from backend.services.brain.brain_loader import get_brain_loader
from backend.services.brain.reflection import get_reflection_service
from backend.services.brain.consolidation import get_consolidation_service

logger = logging.getLogger("routes.brain")
router = APIRouter(prefix="/api/brain", tags=["brain"])


# ═══════════════════════════════════════════════════════════════
# Phase 6: Overview / Memory / Search
# ═══════════════════════════════════════════════════════════════


@router.get("")
async def brain_overview():
    """Aggregate memory stats, recent insights, evaluation summary."""
    svc = get_memory_service()
    intel = get_intelligence_service()
    eval_svc = EvaluationService()

    memory_counts = await svc.stats()

    async with async_session() as db:
        insights = await intel.list_insights(limit=20)
        eval_stats = await eval_svc.stats(db)
        recent_evaluations = await eval_svc.list_evaluations(db, limit=10)

    return {
        "memory_counts": memory_counts,
        "recent_insights": [i.to_dict() for i in insights],
        "evaluation_stats": eval_stats,
        "recent_evaluations": recent_evaluations,
    }


@router.get("/memory")
async def brain_memory(source_id: str = "", memory_type: str = "", limit: int = 100):
    """Query memory items directly."""
    svc = get_memory_service()
    items = await svc.query(source_id=source_id or None, memory_type=memory_type or None, limit=limit)
    return {"items": [it.to_dict() for it in items], "count": len(items)}


@router.get("/search")
async def brain_search(q: str = Query("", description="Search query"), top_k: int = 10):
    """Semantic search over memory items."""
    if not q:
        return {"items": [], "count": 0}
    svc = get_memory_service()
    vec = svc.compute_embedding(q)
    items = await svc.semantic_search(vec, top_k=top_k, min_score=0.1)
    return {"items": [it.to_dict() for it in items], "count": len(items)}


@router.post("/reflect")
async def brain_reflect(task_id: str = ""):
    """Trigger insight generation for a task. Fire-and-forget."""
    intel = get_intelligence_service()

    async def _run():
        try:
            async with async_session() as db:
                await intel.process_task_completion(db, task_id)
                await db.commit()
        except Exception as e:
            logger.warning("[BRAIN] reflection failed for %s: %s", task_id, e)

    asyncio.ensure_future(_run())
    return {"status": "reflection_triggered", "task_id": task_id}


# ═══════════════════════════════════════════════════════════════
# Phase 12: Brain Fragment API
# ═══════════════════════════════════════════════════════════════


@router.get("/fragments/{teammate_id}")
async def list_fragments(teammate_id: str):
    """Get all current brain fragments for a teammate."""
    store = get_brain_fragment_store()
    fragments = await store.get_all_by_teammate(teammate_id)
    return {"fragments": [f.to_dict() for f in fragments], "count": len(fragments)}


@router.get("/fragments/{teammate_id}/{fragment_type}")
async def get_fragment(teammate_id: str, fragment_type: str):
    """Get the latest version of a specific fragment type for a teammate."""
    store = get_brain_fragment_store()
    frag = await store.get_latest(teammate_id, fragment_type)
    if frag is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "fragment not found"})
    return frag.to_dict()


@router.get("/fragments/{teammate_id}/{fragment_type}/versions")
async def list_fragment_versions(teammate_id: str, fragment_type: str):
    """List all versions of a fragment type for a teammate."""
    store = get_brain_fragment_store()
    versions = await store.list_versions(teammate_id, fragment_type)
    return {"versions": [v.to_dict() for v in versions], "count": len(versions)}


@router.post("/fragments/{teammate_id}/{fragment_type}/rollback")
async def rollback_fragment(teammate_id: str, fragment_type: str, target_version: int = Query(...)):
    """Rollback a fragment to a previous version."""
    store = get_brain_fragment_store()
    new_id = await store.rollback(teammate_id, fragment_type, target_version)
    if new_id is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": f"version {target_version} not found"})
    return {"status": "rolled_back", "new_id": new_id, "target_version": target_version}


@router.get("/loader/{teammate_id}")
async def brain_loader_prompt(
    teammate_id: str,
    recent_memory_limit: int = Query(10, le=50),
    extra_context: str = Query("", max_length=500),
):
    """Preview the prompt BrainLoader would build for a teammate.

    Returns the assembled system prompt sections (for debugging/UI preview).
    """
    loader = get_brain_loader()
    prompt = await loader.build_prompt(
        teammate_id, recent_memory_limit=recent_memory_limit, extra_context=extra_context,
    )
    return {"teammate_id": teammate_id, "prompt": prompt}


@router.get("/fragment-types")
async def list_fragment_types():
    """List available brain fragment types."""
    return {"types": [e.value for e in BrainFragmentType]}


@router.post("/consolidate")
async def trigger_consolidation(lookback_hours: int = 48):
    """Manually trigger memory → brain consolidation. Returns count of fragments created."""
    svc = get_consolidation_service()
    count = await svc.consolidate(lookback_hours=lookback_hours)
    return {"status": "consolidation_complete", "fragments_created": count}
