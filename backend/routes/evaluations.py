"""
routes/evaluations.py — Evaluation System API (Phase 6)

Endpoints:
  GET /api/evaluations/stats           — Aggregate evaluation statistics
  GET /api/evaluations/{execution_id}  — Get evaluation for an execution
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.services.evaluation import EvaluationService
from backend.services.runtime.execution_store import get_execution_store

logger = logging.getLogger("routes.evaluations")
router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])

_eval_service = EvaluationService()


# ── Stats (must precede /{execution_id} to avoid wildcard swallowing) ──


@router.get("/stats")
async def evaluation_stats():
    """Aggregate evaluation statistics across all executions."""
    return await _eval_service.stats()


# ── Get evaluation for an execution ──


@router.get("/{execution_id}")
async def get_evaluation(execution_id: str):
    """Get the evaluation record for an execution.

    If no evaluation exists yet, runs one on-the-fly using the
    stored execution record.
    """
    ev = await _eval_service.get(execution_id)
    if ev is None:
        # Run evaluation on the fly
        store = get_execution_store()
        rec = await store.aget(execution_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        ev = await _eval_service.evaluate(execution_id, rec.to_dict())

    return ev.to_dict()
