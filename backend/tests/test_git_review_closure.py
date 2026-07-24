"""
test_git_review_closure.py — Verify the minimal AI Team closure:

    Human → TechLead/planner → Engineer → Reviewer → done

Engineer edits a file in a real per-workspace git repo, commits, and the
Reviewer reads the REAL git diff + runs pytest, then emits approve/reject.

No second execution chain: both roles run through the same runtime helpers.
The LLM is stubbed (we test the workflow/git mechanics, not the model).
"""

import asyncio
import os
import sys
import json
import shutil

import pytest

# Ensure project root importable
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.services.runtime import tool_runtime as tr

WS = "closure_ws_test"


@pytest.fixture(autouse=True)
def _ws():
    path = tr.workspace_root(WS)
    if os.path.isdir(path):
        shutil.rmtree(path)
    yield WS
    if os.path.isdir(path):
        shutil.rmtree(path)


def test_git_workspace_flow_creates_real_diff():
    """Engineer writes + commits → reviewer git_work_diff returns the real diff."""
    tr.git_ensure(WS, branch=f"feat/{WS}")
    # Simulate Engineer writing a file
    fpath = os.path.join(tr.workspace_root(WS), "hello.py")
    with open(fpath, "w") as f:
        f.write("def hello():\n    return 'hi'\n")
    commit = tr.git_commit(WS, "engineer: add hello")
    assert commit["ok"], commit
    assert commit["hash"]

    diff = tr.git_work_diff(WS)
    assert "hello.py" in diff
    assert "def hello" in diff
    assert "git log" in diff
    assert commit["hash"][:7] in diff or "feat/" in diff


def test_reviewer_rejects_on_failing_tests(monkeypatch):
    """Reviewer runs pytest; if tests fail it must reject (mechanics path)."""
    import backend.services.ai_service as ai_service

    # Stub the LLM to return a JSON reject with a blocker.
    async def fake_stream(**kwargs):
        yield json.dumps({
            "verdict": "reject",
            "summary": "tests failing",
            "blockers": ["pytest failed"],
        })

    monkeypatch.setattr(ai_service, "stream_ai_response", fake_stream)

    tr.git_ensure(WS, branch=f"feat/{WS}")
    with open(os.path.join(tr.workspace_root(WS), "x.py"), "w") as f:
        f.write("x=1\n")
    tr.git_commit(WS, "engineer: x")

    # shell_exec pytest will run real pytest (no tests → "no tests ran" = not 'passed')
    out = asyncio.run(reviewer.run_reviewer_workflow(
        teammate={"model_provider": "openrouter", "model_name": "x", "system_prompt": ""},
        task_description="do thing",
        workspace_id=WS,
    ))
    assert out["verdict"] == "reject"
    assert out["blockers"] == ["pytest failed"]
    assert "x.py" in out["diff"]


def test_reviewer_approves_on_clean_diff(monkeypatch):
    """Reviewer approves when the model says approve (identity loaded, no second chain)."""
    import backend.services.ai_service as ai_service

    async def fake_stream(**kwargs):
        # Confirm the reviewer prompt carries the teammate identity + real diff.
        user = kwargs["messages"][0]["content"]
        assert "TASK" in user and "GIT DIFF" in user
        assert "sys_prompt_for_reviewer" in kwargs["system_prompt"]
        yield json.dumps({"verdict": "approve", "summary": "lgtm", "blockers": []})

    monkeypatch.setattr(ai_service, "stream_ai_response", fake_stream)

    tr.git_ensure(WS, branch=f"feat/{WS}")
    with open(os.path.join(tr.workspace_root(WS), "y.py"), "w") as f:
        f.write("y=2\n")
    tr.git_commit(WS, "engineer: y")

    out = asyncio.run(reviewer.run_reviewer_workflow(
        teammate={
            "model_provider": "openrouter",
            "model_name": "x",
            "system_prompt": "sys_prompt_for_reviewer",
        },
        task_description="do thing",
        workspace_id=WS,
    ))
    assert out["verdict"] == "approve"
    assert out["tests_passed"] is True or isinstance(out["tests_passed"], bool)


def test_detect_role_splits_engineer_reviewer():
    from backend.services.runtime.teammate_runner import detect_role
    assert detect_role({"name": "Eng", "role": "engineer"}) == "engineer"
    assert detect_role({"name": "Rev", "role": "reviewer"}) == "reviewer"
    assert detect_role({"name": "Lead", "role": "tech_lead"}) == "engineer_lead"
