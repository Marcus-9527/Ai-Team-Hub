"""
Tests for the Artifact System (Phase 5).

These hit the ArtifactService directly (sync), verifying:
  - create / get / list round-trip
  - filesystem content storage
  - filter params
"""

import os
import sys
import tempfile

# ── Test setup: use a temp dir + file-based SQLite ──
_tmp = tempfile.mkdtemp()
os.environ["AI_TEAM_HUB_DB"] = os.path.join(_tmp, "test.db")

# Patch DB_PATH so the artifact service uses the same DB
import backend.database
backend.database.DB_PATH = os.path.join(_tmp, "test.db")
# Re-call makedirs for the new path
os.makedirs(os.path.dirname(backend.database.DB_PATH), exist_ok=True)

from backend.services.artifact import ArtifactService, ARTIFACTS_DIR


def test_artifact_crud():
    # Override artifacts dir to temp
    import backend.services.artifact as amod
    amod.ARTIFACTS_DIR = os.path.join(_tmp, "artifacts")
    os.makedirs(amod.ARTIFACTS_DIR, exist_ok=True)

    svc = ArtifactService(db_url=f"sqlite:///{backend.database.DB_PATH}")

    # ── Create ──
    art = svc.create_artifact(
        "print('hello world')",
        name="hello.py",
        type="code",
        task_id="task-1",
        execution_id="exec-1",
        metadata={"language": "python"},
    )
    assert art["id"].startswith("art_")
    assert art["name"] == "hello.py"
    assert art["type"] == "code"
    assert art["task_id"] == "task-1"
    assert art["execution_id"] == "exec-1"
    assert art["metadata"]["language"] == "python"
    assert art["content_hash"]  # non-empty
    assert art["created_at"]

    # Verify file on disk
    assert os.path.exists(art["path"])
    with open(art["path"]) as f:
        assert f.read() == "print('hello world')"

    # ── Get ──
    fetched = svc.get_artifact(art["id"])
    assert fetched is not None
    assert fetched["name"] == "hello.py"

    # ── Get (miss) ──
    assert svc.get_artifact("nonexistent") is None

    # ── Get content ──
    content = svc.get_content(art["id"])
    assert content == "print('hello world')"

    # ── List (all) ──
    all_arts = svc.list_artifacts()
    assert len(all_arts) >= 1
    assert all_arts[0]["id"] == art["id"]

    # ── List (by task) ──
    task_arts = svc.list_artifacts(task_id="task-1")
    assert len(task_arts) == 1

    # ── List (by execution) ──
    exec_arts = svc.list_artifacts(execution_id="exec-1")
    assert len(exec_arts) == 1

    # ── List (by type) ──
    type_arts = svc.list_artifacts(type="code")
    assert len(type_arts) == 1
    assert svc.list_artifacts(type="image") == []

    # ── List (empty filter) ──
    no_match = svc.list_artifacts(task_id="no-such-task")
    assert no_match == []

    # ── Binary content ──
    bin_art = svc.create_artifact(
        b"\x89PNG\r\n\x1a\n",
        name="img.png",
        type="image",
        metadata={"size": 8},
    )
    assert bin_art["type"] == "image"

    # ── Ordering (newest first) ──
    arts = svc.list_artifacts(limit=10)
    assert arts[0]["id"] == bin_art["id"]  # most recent first
    assert len(arts) == 2

    print("ALL ARTIFACT TESTS PASSED")


if __name__ == "__main__":
    test_artifact_crud()
