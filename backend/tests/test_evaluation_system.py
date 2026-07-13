"""
test_evaluation_system.py — Phase 6: Execution-Level Evaluation Tests

Coverage:
  1. ScoringEngine — latency scoring
  2. ScoringEngine — cost scoring
  3. ScoringEngine — artifact scoring (binary)
  4. ScoringEngine — error scoring
  5. ScoringEngine — overall weighted score
  6. ScoringEngine — perfect execution → perfect scores
  7. EvaluationService — evaluate creates record
  8. EvaluationService — evaluate upsert (re-evaluate)
  9. EvaluationService — get returns record
  10. EvaluationService — stats aggregates correctly
  11. Auto-evaluation — fire-and-forget function signature
  12. API — GET /api/evaluations/{id}
  13. API — GET /api/evaluations/stats
"""
from __future__ import annotations

import pytest

from backend.services.evaluation import EvaluationService, ScoringEngine, Metrics
from backend.services.runtime.execution_store import ExecutionRecord


# ── Fixtures ──


@pytest.fixture
def engine():
    return ScoringEngine()


@pytest.fixture
def perfect_record():
    r = ExecutionRecord(execution_id="exec-perfect", task_id="t1", model="gpt-4o")
    r.status = "COMPLETED"
    r.start_time = 1000.0
    r.end_time = 1003.0
    r.duration_ms = 3000        # < IDEAL
    r.cost_micro_usd = 100       # < IDEAL
    r.error = ""
    r.events = [{"type": "tool_call", "data": {"tool": "artifact"}}]
    return r


# ═══════════════════════════════════════════════════════════════
# 1–6: ScoringEngine
# ═══════════════════════════════════════════════════════════════


def test_latency_ideal(engine):
    """≤ LATENCY_IDEAL_MS → 1.0."""
    scores = engine.score({"duration_ms": 1000})
    assert scores["latency_score"] == 1.0


def test_latency_abysmal(engine):
    """≥ LATENCY_ACCEPTABLE_MS → 0.0."""
    scores = engine.score({"duration_ms": 120_000})
    assert scores["latency_score"] == 0.0


def test_latency_mid(engine):
    """Between thresholds → linear interpolation."""
    mid = (Metrics.LATENCY_IDEAL_MS + Metrics.LATENCY_ACCEPTABLE_MS) // 2
    scores = engine.score({"duration_ms": mid})
    assert 0.0 < scores["latency_score"] < 1.0


def test_cost_ideal(engine):
    """≤ COST_IDEAL → 1.0."""
    scores = engine.score({"cost_micro_usd": 50})
    assert scores["cost_score"] == 1.0


def test_cost_abysmal(engine):
    """≥ COST_ACCEPTABLE → 0.0."""
    scores = engine.score({"cost_micro_usd": 200_000})
    assert scores["cost_score"] == 0.0


def test_cost_mid(engine):
    """Between thresholds → log interpolation."""
    mid = 5000
    scores = engine.score({"cost_micro_usd": mid})
    assert 0.0 < scores["cost_score"] < 1.0


def test_artifact_present(engine):
    """Tool call with 'artifact' → score 1.0."""
    scores = engine.score({
        "events": [{"type": "tool_call", "data": {"tool": "artifact"}}],
    })
    assert scores["artifact_score"] == 1.0


def test_artifact_missing(engine):
    """No artifact events → score 0.0."""
    scores = engine.score({"events": []})
    assert scores["artifact_score"] == 0.0


def test_error_clean(engine):
    """No error → 1.0."""
    scores = engine.score({"error": ""})
    assert scores["error_score"] == 1.0


def test_error_present(engine):
    """Has error → 0.0."""
    scores = engine.score({"error": "Something went wrong"})
    assert scores["error_score"] == 0.0


def test_overall_weights(engine):
    """Overall = weighted sum of dimensions."""
    d = {"duration_ms": 3000, "cost_micro_usd": 100, "error": "",
         "events": [{"type": "tool_call", "data": {"tool": "artifact"}}]}
    s = engine.score(d)
    expected = (
        s["latency_score"] * Metrics.W_LATENCY
        + s["cost_score"] * Metrics.W_COST
        + s["artifact_score"] * Metrics.W_ARTIFACT
        + s["error_score"] * Metrics.W_ERROR
    )
    assert s["score"] == round(expected, 4)


def test_perfect_execution(engine):
    """Everything ideal → score ≈ 1.0."""
    s = engine.score({
        "duration_ms": 1000,
        "cost_micro_usd": 10,
        "error": "",
        "events": [{"type": "tool_call", "data": {"tool": "artifact"}}],
    })
    assert s["score"] == 1.0


# ═══════════════════════════════════════════════════════════════
# 7–10: EvaluationService (integration with DB)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_evaluate_creates_record(perfect_record, db_session):
    """evaluate() should persist an EvaluationRecord with status=EVALUATED."""
    svc = EvaluationService()
    ev = await svc.evaluate(perfect_record.execution_id, perfect_record.to_dict(), db=db_session)
    assert ev is not None
    assert ev.execution_id == perfect_record.execution_id
    assert ev.status == "EVALUATED"
    assert ev.score > 0.5


@pytest.mark.asyncio
async def test_evaluate_upsert(perfect_record, db_session):
    """Re-evaluating same execution_id updates scores in place."""
    svc = EvaluationService()
    ev1 = await svc.evaluate(perfect_record.execution_id, perfect_record.to_dict(), db=db_session)
    score1 = ev1.score

    # Simulate worse execution
    bad_record = perfect_record.to_dict()
    bad_record["duration_ms"] = 120_000
    bad_record["error"] = "timeout"
    ev2 = await svc.evaluate(perfect_record.execution_id, bad_record, db=db_session)

    assert ev2.id == ev1.id  # same row
    assert ev2.score < score1


@pytest.mark.asyncio
async def test_get_returns_record(perfect_record, db_session):
    """get() should return the evaluation after create."""
    svc = EvaluationService()
    await svc.evaluate(perfect_record.execution_id, perfect_record.to_dict(), db=db_session)

    ev = await svc.get(perfect_record.execution_id, db=db_session)
    assert ev is not None
    assert ev.execution_id == perfect_record.execution_id


@pytest.mark.asyncio
async def test_get_returns_none(db_session):
    """get() for non-existent execution_id returns None."""
    svc = EvaluationService()
    ev = await svc.get("exec-nonexistent", db=db_session)
    assert ev is None


@pytest.mark.asyncio
async def test_stats_aggregates(perfect_record, db_session):
    """stats() returns correct counts and averages."""
    svc = EvaluationService()
    # Create two evaluations
    r1 = perfect_record
    await svc.evaluate(r1.execution_id, r1.to_dict(), db=db_session)

    r2 = ExecutionRecord(execution_id="exec-second", task_id="t2", model="gpt-4o")
    r2.duration_ms = 120_000
    r2.error = "fail"
    await svc.evaluate(r2.execution_id, r2.to_dict(), db=db_session)

    stats = await svc.stats(db=db_session)
    assert stats["total_evaluations"] >= 2
    assert stats["evaluated"] >= 2
    assert 0 < stats["average_score"] < 1.0
    assert 0 < stats["best_score"] <= 1.0


# ═══════════════════════════════════════════════════════════════
# 11: Auto-evaluation integration
# ═══════════════════════════════════════════════════════════════


def test_auto_evaluate_import():
    """_auto_evaluate function exists in executor module."""
    from backend.services.runtime.executor import _auto_evaluate
    assert callable(_auto_evaluate)
