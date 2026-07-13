"""
routes/artifacts.py — Artifact API (Phase 5)

GET  /api/artifacts           — List artifacts
GET  /api/artifacts/{id}      — Get artifact metadata
GET  /api/artifacts/{id}/content — Get artifact file content
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.services.artifact import get_artifact_service

logger = logging.getLogger("routes.artifacts")
router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def _svc():
    return get_artifact_service()


@router.get("")
async def list_artifacts(
    task_id: Optional[str] = Query(None, description="Filter by task"),
    execution_id: Optional[str] = Query(None, description="Filter by execution"),
    type: Optional[str] = Query(None, description="Filter by type (file/code/image/text)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List artifacts, newest first."""
    records = _svc().list_artifacts(
        task_id=task_id,
        execution_id=execution_id,
        type=type,
        limit=limit,
        offset=offset,
    )
    return {
        "artifacts": records,
        "total": len(records),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Get artifact metadata."""
    artifact = _svc().get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str):
    """Get artifact file content as plain text."""
    svc = _svc()
    artifact = svc.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    content = svc.get_content(artifact_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Artifact content not found on disk")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content)
