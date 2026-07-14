"""
services/artifact/ — Artifact Service (Phase 5)

Artifact = an AI-produced output persisted to filesystem + SQLite metadata.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from typing import Optional

from sqlalchemy import create_engine, select, desc
from sqlalchemy.orm import Session as SyncSession

from backend.database import DB_PATH

logger = logging.getLogger("artifact")

ARTIFACTS_DIR = os.path.join(os.path.dirname(DB_PATH), "artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)


class ArtifactService:
    """Thin CRUD for artifact metadata + file storage.

    Files go to data/artifacts/<artifact_id>. Data/artifacts/ sits
    next to the SQLite db so backups cover both.
    """

    def __init__(self, db_url: str = ""):
        if not db_url:
            from backend.database import get_sync_db_url
            db_url = get_sync_db_url()
        self._engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
        )
        # Ensure table exists
        from backend.models import ArtifactModel  # noqa: F401
        from backend.database import Base
        Base.metadata.create_all(self._engine)

    # ── Public API ──

    def create_artifact(
        self,
        content: str | bytes,
        *,
        name: str,
        type: str = "file",
        task_id: str = "",
        execution_id: str = "",
        metadata: dict = None,
    ) -> dict:
        """Persist an artifact: write content to disk, insert DB row, return dict."""
        from backend.models import ArtifactModel

        artifact_id = f"art_{uuid.uuid4().hex[:12]}"

        # Content hash for dedup (SHA-256 truncated)
        raw = content if isinstance(content, bytes) else content.encode("utf-8")
        content_hash = hashlib.sha256(raw).hexdigest()[:16]

        # Write to filesystem
        file_path = os.path.join(ARTIFACTS_DIR, artifact_id)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(file_path, mode) as f:
            f.write(content)

        meta = (metadata or {}).copy()
        meta.setdefault("size", len(raw))

        with SyncSession(self._engine) as session:
            row = ArtifactModel(
                id=artifact_id,
                task_id=task_id or None,
                execution_id=execution_id or None,
                type=type,
                name=name,
                path=file_path,
                content_hash=content_hash,
                meta=meta,
            )
            session.add(row)
            session.commit()
            session.refresh(row)

        logger.info("Artifact created: %s (%s, %s)", artifact_id, name, type)
        return row.to_dict()

    def get_artifact(self, artifact_id: str) -> Optional[dict]:
        """Return artifact metadata dict, or None."""
        from backend.models import ArtifactModel
        with SyncSession(self._engine) as session:
            row = session.get(ArtifactModel, artifact_id)
            return row.to_dict() if row else None

    def list_artifacts(
        self,
        task_id: str = None,
        execution_id: str = None,
        type: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """List artifacts, newest first, with optional filters."""
        from backend.models import ArtifactModel
        with SyncSession(self._engine) as session:
            stmt = select(ArtifactModel)
            if task_id:
                stmt = stmt.where(ArtifactModel.task_id == task_id)
            if execution_id:
                stmt = stmt.where(ArtifactModel.execution_id == execution_id)
            if type:
                stmt = stmt.where(ArtifactModel.type == type)
            stmt = stmt.order_by(desc(ArtifactModel.created_at)).offset(offset).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [r.to_dict() for r in rows]

    def get_content(self, artifact_id: str) -> Optional[str]:
        """Read artifact content from filesystem. Returns None if missing."""
        from backend.models import ArtifactModel
        with SyncSession(self._engine) as session:
            row = session.get(ArtifactModel, artifact_id)
            if not row:
                return None
        try:
            with open(row.path, "r") as f:
                return f.read()
        except (FileNotFoundError, IOError):
            logger.warning("Artifact file missing: %s", row.path)
            return None


# ── Singleton ──

_artifact_service: Optional[ArtifactService] = None


def get_artifact_service() -> ArtifactService:
    global _artifact_service
    if _artifact_service is None:
        _artifact_service = ArtifactService()
    return _artifact_service
