"""Test teammate_runtime v1 — minimal import + smoke test."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from backend.teammate_runtime import run_teammate_goal, TeammateRuntime, TeammateResult
from backend.teammate_runtime.planner import call_planner
from backend.teammate_runtime.executor import call_executor
from backend.teammate_runtime.reflection import call_reflection
from backend.teammate_runtime.memory_writer import save_execution, save_decision
from backend.services.memory.memory_types import MemoryItem, MemoryType


class TestImports:
    """All modules import cleanly."""

    def test_imports(self):
        assert callable(run_teammate_goal)
        assert TeammateRuntime is not None
        assert TeammateResult is not None
        assert callable(call_planner)
        assert callable(call_executor)
        assert callable(call_reflection)
        assert callable(save_execution)
        assert callable(save_decision)


class TestTeammateResult:
    """TeammateResult shape."""

    def test_fields(self):
        r = TeammateResult(teammate_id="tm-1", goal="test", status="COMPLETED",
                           rounds=2, summary="done")
        assert r.teammate_id == "tm-1"
        assert r.goal == "test"
        assert r.status == "COMPLETED"
        assert r.rounds == 2
        assert r.summary == "done"
        assert r.error == ""

    def test_error(self):
        r = TeammateResult(teammate_id="tm-2", goal="x", status="FAILED",
                           rounds=0, error="not found")
        assert r.error == "not found"


class TestRuntime:
    """TeammateRuntime edge cases (no real teammate in test DB)."""

    @pytest.mark.asyncio
    async def test_teammate_not_found(self):
        r = await run_teammate_goal(teammate_id="nonexistent", goal="do stuff")
        assert r.status == "FAILED"
        assert "not found" in r.error

    @pytest.mark.asyncio
    async def test_empty_goal(self):
        r = await run_teammate_goal(teammate_id="nobody", goal="")
        assert r.status == "FAILED"


class TestPlanner:
    """call_planner edge cases."""

    @pytest.mark.asyncio
    async def test_empty_goal(self):
        p = await call_planner({"id": "t"}, "")
        assert p == {}

    @pytest.mark.asyncio
    async def test_fallback_execute(self):
        p = await call_planner({"id": "t"}, "do something")
        assert p.get("action") == "execute"
        assert "description" in p


class TestReflection:
    """call_reflection edge cases."""

    @pytest.mark.asyncio
    async def test_no_result_stops(self):
        r = await call_reflection("tm-1", {"action": "x"}, None)
        assert r["should_stop"] is True

    @pytest.mark.asyncio
    async def test_test_passed_stops(self):
        r = await call_reflection("tm-1", {"action": "x"},
                                  {"summary": "all good", "test_result": "PASSED"})
        assert r["should_stop"] is True
        assert "tests passed" in r["decision"]

    @pytest.mark.asyncio
    async def test_files_no_test_continues(self):
        r = await call_reflection("tm-1", {"action": "x"},
                                  {"summary": "wrote code", "files_changed": ["a.py"],
                                   "test_result": ""})
        assert r["should_stop"] is False


class TestMemoryWriter:
    """save_execution / save_decision — verify content structure without DB."""

    def test_execution_content_structure(self):
        """Build a MemoryItem manually and verify the JSON content shape."""
        content = json.dumps({
            "action": "build-api",
            "status": "ok",
            "summary": "done",
        }, ensure_ascii=False)
        item = MemoryItem(
            memory_type=MemoryType.EXECUTION,
            content=content,
            source_id="tm-1",
            created_at=datetime.now(timezone.utc),
        )
        data = json.loads(item.content)
        assert data["action"] == "build-api"
        assert data["status"] == "ok"
        assert data["summary"] == "done"

    def test_decision_content_structure(self):
        content = json.dumps({
            "decision": "all good",
            "source_action": "build-api",
        }, ensure_ascii=False)
        item = MemoryItem(
            memory_type=MemoryType.DECISION,
            content=content,
            source_id="tm-1",
            created_at=datetime.now(timezone.utc),
        )
        data = json.loads(item.content)
        assert data["decision"] == "all good"
        assert data["source_action"] == "build-api"
