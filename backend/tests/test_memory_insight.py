"""
test_memory_insight.py — V2.7 Phase C: MemoryInsight Unit Tests

Covers:
  1. MemoryInsight dataclass (to_dict/from_dict/__len__)
  2. InsightType enum + priority ordering
  3. MemoryInsightEngine rules (success, failure, optimization)
  4. MemoryInsightStore persistence (with real DB)
  5. MemoryIntelligenceService orchestration
  6. PlannerContextBuilder._collect_insights integration (unit)
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.services.memory.memory_insight import (
    InsightType,
    MemoryInsight,
    MemoryInsightEngine,
    TaskResultSnapshot,
    HIGH_QUALITY_THRESHOLD,
    HIGH_COST_THRESHOLD_MICRO,
)
from backend.services.memory.memory_insight_store import (
    MemoryInsightStore,
    get_insight_store,
    reset_insight_store,
)
from backend.services.memory.memory_intelligence import (
    MemoryIntelligenceService,
    get_intelligence_service,
    reset_intelligence_service,
)

# ═══════════════════════════════════════════════════════════════
# 1. Dataclass
# ═══════════════════════════════════════════════════════════════


class TestMemoryInsight:
    def test_create_minimal(self):
        """Minimal insight with no extra params."""
        ins = MemoryInsight()
        assert ins.id and len(ins.id) > 10
        assert ins.type == InsightType.SUCCESS_PATTERN
        assert ins.confidence == 0.0

    def test_to_dict_roundtrip(self):
        """to_dict() → from_dict() should preserve all fields."""
        original = MemoryInsight(
            id="test-1",
            type=InsightType.FAILURE_PATTERN,
            title="Test",
            content="Something failed",
            source_task_id="task-123",
            source_execution_id="exec-456",
            confidence=0.75,
            created_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
            metadata={"retries": 3},
        )
        d = original.to_dict()
        restored = MemoryInsight.from_dict(d)

        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.title == original.title
        assert restored.content == original.content
        assert restored.source_task_id == original.source_task_id
        assert restored.source_execution_id == original.source_execution_id
        assert restored.confidence == original.confidence
        assert restored.metadata == original.metadata
        assert restored.created_at == original.created_at

    def test_len_estimates(self):
        """__len__ should return total chars of title + content + metadata."""
        ins = MemoryInsight(title="Hi", content="World", metadata={"k": "v"})
        assert len(ins) > 0
        assert len(ins) >= len("Hi") + len("World") + len('{"k": "v"}')


# ═══════════════════════════════════════════════════════════════
# 2. InsightType Enum
# ═══════════════════════════════════════════════════════════════


class TestInsightType:
    def test_priority_order(self):
        """RISK_WARNING > FAILURE_PATTERN > OPTIMIZATION > SUCCESS_PATTERN."""
        assert InsightType.priority("RISK_WARNING") == 0
        assert InsightType.priority("FAILURE_PATTERN") == 1
        assert InsightType.priority("OPTIMIZATION") == 2
        assert InsightType.priority("SUCCESS_PATTERN") == 3

    def test_priority_unknown_defaults(self):
        """Unknown type gets high priority number."""
        assert InsightType.priority("UNKNOWN") == 99
        assert InsightType.priority("FOO") == 99


# ═══════════════════════════════════════════════════════════════
# 3. Engine Rules
# ═══════════════════════════════════════════════════════════════


class TestMemoryInsightEngine:
    @pytest.fixture
    def engine(self):
        return MemoryInsightEngine()

    def make_snapshot(self, **overrides) -> TaskResultSnapshot:
        base = {
            "task_step_id": "step-1",
            "task_execution_id": "exec-1",
            "outcome": "SUCCESS",
            "overall_quality": 0.9,
            "failure_category": "",
            "total_tokens": 1000,
            "estimated_cost": 100,
            "step_order": 1,
            "step_objective": "Test objective",
            "is_recoverable": "1",
        }
        base.update(overrides)
        return TaskResultSnapshot(base)

    # ── Success ──

    @pytest.mark.asyncio
    async def test_success_high_quality(self, engine):
        """SUCCESS + quality >= 0.8 → SUCCESS_PATTERN insight."""
        r = self.make_snapshot(outcome="SUCCESS", overall_quality=0.95)
        insights = await engine.analyze_task_result(r)
        assert len(insights) == 1
        assert insights[0].type == InsightType.SUCCESS_PATTERN
        assert insights[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_success_low_quality_no_insight(self, engine):
        """SUCCESS + quality < 0.8 → no insight."""
        r = self.make_snapshot(outcome="SUCCESS", overall_quality=0.5)
        insights = await engine.analyze_task_result(r)
        assert len(insights) == 0

    @pytest.mark.asyncio
    async def test_success_with_failure_category_no_insight(self, engine):
        """SUCCESS but failure_category set → excluded (contradiction)."""
        r = self.make_snapshot(
            outcome="SUCCESS",
            overall_quality=0.9,
            failure_category="timeout",
        )
        insights = await engine.analyze_task_result(r)
        assert len(insights) == 0

    # ── Failure ──

    @pytest.mark.asyncio
    async def test_failure_creates_insight(self, engine):
        """FAILURE → FAILURE_PATTERN insight."""
        r = self.make_snapshot(
            outcome="FAILURE",
            failure_category="tool_error",
            is_recoverable="0",
        )
        insights = await engine.analyze_task_result(r)
        assert len(insights) == 1
        assert insights[0].type == InsightType.FAILURE_PATTERN
        assert "tool_error" in insights[0].content or "tool_error" in insights[0].metadata.get("failure_category", "")

    @pytest.mark.asyncio
    async def test_non_failure_no_failure_insight(self, engine):
        """SUCCESS outcome → no FAILURE_PATTERN."""
        r = self.make_snapshot(outcome="SUCCESS")
        insights = await engine.analyze_task_result(r)
        types = [i.type for i in insights if i.type == InsightType.FAILURE_PATTERN]
        assert len(types) == 0

    # ── Optimization ──

    @pytest.mark.asyncio
    async def test_optimization_high_cost(self, engine):
        """cost >= HIGH_COST_THRESHOLD → OPTIMIZATION insight."""
        r = self.make_snapshot(outcome="SUCCESS", estimated_cost=HIGH_COST_THRESHOLD_MICRO + 100)
        insights = await engine.analyze_task_result(r)
        opt_types = [i for i in insights if i.type == InsightType.OPTIMIZATION]
        assert len(opt_types) >= 1
        assert "成本" in opt_types[0].content or "cost" in opt_types[0].content

    @pytest.mark.asyncio
    async def test_optimization_high_tokens(self, engine):
        """High token count → OPTIMIZATION insight."""
        r = self.make_snapshot(outcome="SUCCESS", total_tokens=15_000)
        insights = await engine.analyze_task_result(r)
        opt_types = [i for i in insights if i.type == InsightType.OPTIMIZATION]
        assert len(opt_types) >= 1

    @pytest.mark.asyncio
    async def test_optimization_low_cost_no_insight(self, engine):
        """Low cost + low tokens → no OPTIMIZATION insight."""
        r = self.make_snapshot(outcome="SUCCESS", estimated_cost=10, total_tokens=500)
        insights = await engine.analyze_task_result(r)
        opt_types = [i for i in insights if i.type == InsightType.OPTIMIZATION]
        assert len(opt_types) == 0

    # ── Risk factory ──

    def test_make_risk_insight(self, engine):
        """Static factory creates RISK_WARNING insight."""
        ins = MemoryInsightEngine.make_risk_insight(
            task_id="task-1",
            title="Risk: policy blocked",
            content="Task was blocked by content policy",
            confidence=0.9,
            extra_meta={"policy": "content_safety"},
        )
        assert ins.type == InsightType.RISK_WARNING
        assert ins.source_task_id == "task-1"
        assert ins.confidence == 0.9
        assert ins.metadata["policy"] == "content_safety"

    # ── generate_insights (batch) ──

    @pytest.mark.asyncio
    async def test_generate_insights_empty(self, engine):
        results = []
        insights = await engine.generate_insights(results)
        assert insights == []

    @pytest.mark.asyncio
    async def test_generate_insights_multiple(self, engine):
        success = self.make_snapshot(outcome="SUCCESS", overall_quality=0.95)
        failure = self.make_snapshot(outcome="FAILURE")
        insights = await engine.generate_insights([success, failure])
        assert len(insights) >= 2
        types = set(i.type for i in insights)
        assert InsightType.SUCCESS_PATTERN in types
        assert InsightType.FAILURE_PATTERN in types


# ═══════════════════════════════════════════════════════════════
# 4. Store (unit with optional async real DB)
# ═══════════════════════════════════════════════════════════════


class TestMemoryInsightStore:
    @pytest_asyncio.fixture
    async def store(self):
        reset_insight_store()
        store = get_insight_store()
        await store._ensure_table()
        from sqlalchemy import text
        from backend.database import engine
        async with engine.connect() as conn:
            await conn.execute(text("DELETE FROM memory_insights"))
            await conn.commit()
        reset_insight_store()
        yield get_insight_store()
        reset_insight_store()

    def sample_insight(self, **overrides) -> MemoryInsight:
        kwargs = {
            "type": InsightType.SUCCESS_PATTERN,
            "title": "Test insight",
            "content": "This is a test insight content",
            "source_task_id": "task-test-1",
            "confidence": 0.8,
        }
        kwargs.update(overrides)
        return MemoryInsight(**kwargs)

    @pytest.mark.asyncio
    async def test_create_and_list(self, store):
        """Create insight → list returns it."""
        ins = self.sample_insight()
        await store.create_insight(ins)

        listed = await store.list_insights(task_id="task-test-1")
        ids = [i.id for i in listed]
        assert ins.id in ids

    @pytest.mark.asyncio
    async def test_list_by_task_filters(self, store):
        """list_insights by task_id returns only that task's insights."""
        ins_a = self.sample_insight(source_task_id="task-a")
        ins_b = self.sample_insight(source_task_id="task-b")
        await store.create_insights_batch([ins_a, ins_b])

        task_a = await store.list_insights(task_id="task-a")
        task_b = await store.list_insights(task_id="task-b")

        assert len(task_a) == 1
        assert task_a[0].source_task_id == "task-a"
        assert len(task_b) == 1
        assert task_b[0].source_task_id == "task-b"

    @pytest.mark.asyncio
    async def test_list_by_type(self, store):
        """list_by_type filters correctly."""
        success = self.sample_insight(
            type=InsightType.SUCCESS_PATTERN, source_task_id="t1",
        )
        failure = self.sample_insight(
            type=InsightType.FAILURE_PATTERN, source_task_id="t1",
        )
        await store.create_insights_batch([success, failure])

        successes = await store.list_by_type(InsightType.SUCCESS_PATTERN)
        assert len(successes) == 1
        assert successes[0].type == InsightType.SUCCESS_PATTERN

    @pytest.mark.asyncio
    async def test_search(self, store):
        """Search keyword in content/title."""
        ins = self.sample_insight(content="uniquetermxyz")
        await store.create_insight(ins)

        results = await store.search_insights("uniquetermxyz")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_get_recent(self, store):
        """get_recent returns most recent first."""
        for i in range(5):
            await store.create_insight(self.sample_insight(source_task_id=f"t{i}"))
        recent = await store.get_recent(limit=3)
        assert len(recent) <= 3

    @pytest.mark.asyncio
    async def test_stats(self, store):
        """Stats returns type counts."""
        await store.create_insight(self.sample_insight(type=InsightType.SUCCESS_PATTERN, source_task_id="x"))
        await store.create_insight(self.sample_insight(type=InsightType.FAILURE_PATTERN, source_task_id="y"))
        stats = await store.stats()
        assert stats["total"] >= 2
        assert InsightType.SUCCESS_PATTERN in stats["by_type"]

    @pytest.mark.asyncio
    async def test_prune_old(self, store):
        """prune removes old insights."""
        old = self.sample_insight(
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            source_task_id="old",
        )
        new = self.sample_insight(source_task_id="new")
        await store.create_insight(old)
        await store.create_insight(new)

        deleted = await store.prune(older_than_days=30)
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_get_by_ids(self, store):
        """get_by_ids returns matching insights."""
        ins = self.sample_insight(source_task_id="by-ids")
        await store.create_insight(ins)
        found = await store.get_by_ids([ins.id])
        assert len(found) == 1
        assert found[0].id == ins.id


# ═══════════════════════════════════════════════════════════════
# 5. Intelligence Service (unit)
# ═══════════════════════════════════════════════════════════════


class TestMemoryIntelligenceService:
    @pytest.fixture(autouse=True)
    def reset_global(self):
        reset_intelligence_service()
        yield
        reset_intelligence_service()

    @pytest.fixture
    def svc(self):
        store = AsyncMock(spec=MemoryInsightStore)
        store.create_insights_batch = AsyncMock(return_value=["ins-1"])
        store.list_insights = AsyncMock(return_value=[MemoryInsight(title="test")])
        store.search_insights = AsyncMock(
            return_value=[MemoryInsight(title="search result")]
        )
        engine = MemoryInsightEngine()

        service = MemoryIntelligenceService(
            engine=engine, store=store, enabled=True
        )
        return service

    @pytest.mark.asyncio
    async def test_process_no_results(self, svc):
        """No execution results → no insights created."""
        db = AsyncMock()
        # Mock list_results_by_task to return empty
        with patch.object(
            svc._state, "list_results_by_task", AsyncMock(return_value=[])
        ):
            await svc.process_task_completion(db, "task-1")
        # No insights created
        svc._store.create_insights_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_with_results(self, svc):
        """Execution results → insights created."""
        db = AsyncMock()
        mock_result = {
            "task_step_id": "step-1",
            "task_execution_id": "exec-1",
            "outcome": "SUCCESS",
            "overall_quality": 0.95,
            "failure_category": "",
            "total_tokens": 100,
            "estimated_cost": 10,
            "step_order": 1,
            "step_objective": "test",
            "is_recoverable": "1",
        }
        with patch.object(
            svc._state, "list_results_by_task", AsyncMock(return_value=[mock_result])
        ):
            await svc.process_task_completion(db, "task-1")

        svc._store.create_insights_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_disabled_skips(self, svc):
        """enabled=False → skip processing."""
        svc.enabled = False
        db = AsyncMock()
        await svc.process_task_completion(db, "task-1")
        svc._store.create_insights_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_skips_risk(self, svc):
        """enabled=False → skip risk insight."""
        svc.enabled = False
        result = await svc.add_risk_insight("task-1", content="risk")
        assert result is None

    @pytest.mark.asyncio
    async def test_add_risk_insight(self, svc):
        """Risk insight created and persisted."""
        ins_id = await svc.add_risk_insight(
            "task-1",
            title="Risk warning",
            content="Something risky",
            confidence=0.9,
        )
        assert ins_id is not None

    @pytest.mark.asyncio
    async def test_list_insights(self, svc):
        """List delegates to store."""
        insights = await svc.list_insights(task_id="task-1")
        assert len(insights) == 1
        assert insights[0].title == "test"

    @pytest.mark.asyncio
    async def test_search_insights(self, svc):
        """Search delegates to store."""
        results = await svc.search_insights("keyword")
        assert len(results) == 1
        assert results[0].title == "search result"


# ═══════════════════════════════════════════════════════════════
# 6. PlannerContextBuilder integration
# ═══════════════════════════════════════════════════════════════


class TestPlannerContextInsights:
    @pytest.mark.asyncio
    async def test_collect_insights_no_intelligence_service(self):
        """When intelligence service is unavailable → empty."""
        from backend.services.task.task_planner_context import PlannerContextBuilder

        builder = PlannerContextBuilder(enable_insights=True)
        result = await builder._collect_insights(task_id="task-x")
        assert result == ""

    @pytest.mark.asyncio
    async def test_merge(self):
        """Merge returns combined text when both exist."""
        from backend.services.task.task_planner_context import PlannerContextBuilder

        merged = PlannerContextBuilder._merge_intelligence_insights(
            "intel text", "insight text"
        )
        assert "intel text" in merged
        assert "insight text" in merged
        assert "---" in merged

    def test_merge_only_intelligence(self):
        from backend.services.task.task_planner_context import PlannerContextBuilder

        merged = PlannerContextBuilder._merge_intelligence_insights(
            "intel only", ""
        )
        assert merged == "intel only"

    def test_merge_only_insights(self):
        from backend.services.task.task_planner_context import PlannerContextBuilder

        merged = PlannerContextBuilder._merge_intelligence_insights(
            "", "insight only"
        )
        assert merged == "insight only"

    def test_merge_both_empty(self):
        from backend.services.task.task_planner_context import PlannerContextBuilder

        merged = PlannerContextBuilder._merge_intelligence_insights("", "")
        assert merged == ""
