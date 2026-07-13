"""
test_teammate_intelligence.py — Phase 7: Teammate Intelligence System Tests

Coverage:
  1. TeammateProfile.from_orm — correct field mapping
  2. TeammateProfile.to_dict — round-trip
  3. SkillRegistry — built-in mappings
  4. SkillRegistry — custom registration
  5. SkillRegistry — fallback to general
  6. TeammateSelector._compute_match — exact match
  7. TeammateSelector._compute_match — partial match
  8. TeammateSelector._compute_match — no match
  9. TeammateSelector.recommend — returns top N
  10. ExperienceStore.update_from_evaluation — updates teammate stats
  11. ExperienceStore.get_profile — returns enriched profile
  12. Model: Teammate new fields default values
  13. Model: Teammate new fields accept values on create
  14. API: serialize includes new fields
  15. API: recommend endpoint returns sorted results
"""
from __future__ import annotations

import pytest

from backend.models import Teammate, gen_uuid
from backend.services.teammate_intelligence import (
    SkillRegistry,
    TeammateProfile,
    ExperienceStore,
    TeammateSelector,
)
from backend.services.evaluation import EvaluationService
from backend.services.runtime.execution_store import ExecutionRecord


# ═══════════════════════════════════════════════════════════════
# 1-2: TeammateProfile
# ═══════════════════════════════════════════════════════════════


def test_profile_from_orm():
    t = Teammate(
        id="tm-1",
        name="Bob",
        role="engineer",
        avatar_emoji="🦊",
        skills=["python", "go"],
        capabilities=["coding", "code_review"],
        success_rate=0.85,
        average_score=0.78,
        execution_count=42,
    )
    p = TeammateProfile.from_orm(t)
    assert p.id == "tm-1"
    assert p.name == "Bob"
    assert p.skills == ["python", "go"]
    assert p.success_rate == 0.85
    assert p.average_score == 0.78
    assert p.execution_count == 42


def test_profile_to_dict():
    p = TeammateProfile(
        id="tm-2", name="Alice", role="analyst", avatar_emoji="🔍",
        skills=["data_analysis"], capabilities=["analysis"], success_rate=0.9,
        average_score=0.85, execution_count=10,
    )
    d = p.to_dict()
    assert d["name"] == "Alice"
    assert d["skills"] == ["data_analysis"]
    assert d["success_rate"] == 0.9


# ═══════════════════════════════════════════════════════════════
# 3-5: SkillRegistry
# ═══════════════════════════════════════════════════════════════


def test_registry_builtin():
    skills = SkillRegistry.get_skills("coding")
    assert "python" in skills
    assert "javascript" in skills


def test_registry_custom():
    SkillRegistry.register("ml", ["pytorch", "tensorflow", "mlops"])
    skills = SkillRegistry.get_skills("ml")
    assert "pytorch" in skills
    SkillRegistry.reset()  # cleanup


def test_registry_fallback():
    skills = SkillRegistry.get_skills("nonexistent_task_type")
    assert skills == []


# ═══════════════════════════════════════════════════════════════
# 6-8: TeammateSelector._compute_match
# ═══════════════════════════════════════════════════════════════


def test_compute_match_exact():
    s = TeammateSelector._compute_match(
        ["python", "go", "debugging"], ["python", "go", "debugging"]
    )
    assert s == 1.0


def test_compute_match_partial():
    s = TeammateSelector._compute_match(
        ["python", "design"], ["python", "go", "debugging"]
    )
    assert s == pytest.approx(1 / 3)


def test_compute_match_none():
    s = TeammateSelector._compute_match(
        ["design", "ux"], ["python", "go", "debugging"]
    )
    assert s == 0.0


# ═══════════════════════════════════════════════════════════════
# 9: TeammateSelector.recommend (integration with DB)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_recommend_returns_top_n(db_session):
    # Create teammates with different skills
    t1 = Teammate(
        id=gen_uuid(), name="Engineer A", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python", "go", "coding"],
        success_rate=0.9, average_score=0.85, execution_count=20,
    )
    t2 = Teammate(
        id=gen_uuid(), name="Designer B", role="designer",
        model_provider="openrouter", model_name="auto",
        skills=["ui_design", "ux", "frontend"],
        success_rate=0.7, average_score=0.6, execution_count=5,
    )
    db_session.add_all([t1, t2])
    await db_session.commit()

    # Recommend for coding
    profiles = await TeammateSelector.recommend("coding", top_n=2, db=db_session)
    # Phase 22: DB filter excludes Designer B (no coding skills overlap)
    assert len(profiles) == 1  # only Engineer A matches coding skills
    assert profiles[0].name == "Engineer A"


# ═══════════════════════════════════════════════════════════════
# 10: ExperienceStore.update_from_evaluation (integration)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_from_evaluation_updates_stats(db_session):
    # Create a teammate
    t = Teammate(
        id=gen_uuid(), name="TestBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python"], execution_count=0,
        success_rate=0.0, average_score=0.0,
    )
    db_session.add(t)
    await db_session.commit()

    # Create execution records for this teammate
    from backend.models import ExecutionRecordModel, EvaluationRecordModel

    for i, (exec_id, score) in enumerate([
        ("exec-good-1", 0.9),
        ("exec-good-2", 0.8),
        ("exec-bad-1", 0.3),
    ]):
        exec_rec = ExecutionRecordModel(
            execution_id=exec_id,
            task_id=f"task-{i}",
            teammate="TestBot",
            model="gpt-4o",
            status="COMPLETED",
        )
        db_session.add(exec_rec)
        eval_rec = EvaluationRecordModel(
            id=gen_uuid(),
            execution_id=exec_id,
            status="EVALUATED",
            score=score,
        )
        db_session.add(eval_rec)

    await db_session.commit()

    # Trigger update
    await ExperienceStore.update_from_evaluation("exec-good-1", db=db_session)

    # Verify stats updated on Teammate
    await db_session.refresh(t)
    assert t.execution_count == 3
    assert t.success_rate == pytest.approx(2 / 3, abs=0.001)  # 2 successes (≥0.5) out of 3
    assert t.average_score == pytest.approx((0.9 + 0.8 + 0.3) / 3, abs=0.001)


# ═══════════════════════════════════════════════════════════════
# 11: ExperienceStore.get_profile
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_profile_returns_enriched(db_session):
    t = Teammate(
        id=gen_uuid(), name="Profiler", role="analyst",
        model_provider="openrouter", model_name="auto",
        skills=["data_analysis", "statistics"],
        success_rate=0.95, average_score=0.9, execution_count=50,
    )
    db_session.add(t)
    await db_session.commit()

    profile = await ExperienceStore.get_profile(t.id, db=db_session)
    assert profile is not None
    assert profile.name == "Profiler"
    assert profile.skills == ["data_analysis", "statistics"]
    assert profile.execution_count == 50


# ═══════════════════════════════════════════════════════════════
# 12-13: Model new fields
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_model_defaults(db_session):
    t = Teammate(
        id=gen_uuid(), name="DefaultBot", role="assistant",
        model_provider="openrouter", model_name="auto",
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    assert t.skills == []
    assert t.capabilities == []
    assert t.success_rate == 0.0
    assert t.average_score == 0.0
    assert t.execution_count == 0


@pytest.mark.asyncio
async def test_model_custom_values(db_session):
    t = Teammate(
        id=gen_uuid(), name="CustomBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python", "go"],
        capabilities=["coding", "review"],
        success_rate=0.75, average_score=0.7, execution_count=10,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    assert t.skills == ["python", "go"]
    assert t.success_rate == 0.75
    assert t.execution_count == 10


# ═══════════════════════════════════════════════════════════════
# Phase 14: Teammate Evolution Memory
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_memory_populated_after_evaluation(db_session):
    """ExperienceStore updates memory fields after evaluation."""
    t = Teammate(
        id=gen_uuid(), name="MemoryBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python"], execution_count=0,
        success_rate=0.0, average_score=0.0,
    )
    db_session.add(t)
    await db_session.commit()

    from backend.models import ExecutionRecordModel, EvaluationRecordModel

    exec_rec = ExecutionRecordModel(
        execution_id="mem-exec-1",
        task_id="task-mem-1",
        teammate="MemoryBot",
        model="gpt-4o",
        status="COMPLETED",
        dag_node_id="coding",
    )
    db_session.add(exec_rec)
    # High-score evaluation
    eval_rec = EvaluationRecordModel(
        id=gen_uuid(),
        execution_id="mem-exec-1",
        status="EVALUATED",
        score=0.92,
    )
    db_session.add(eval_rec)
    await db_session.commit()

    await ExperienceStore.update_from_evaluation("mem-exec-1", db=db_session)
    await db_session.refresh(t)

    assert len(t.strengths) >= 1
    assert len(t.learned_patterns) >= 1
    assert any("coding" in s for s in t.strengths)


@pytest.mark.asyncio
async def test_failed_patterns_recorded(db_session):
    """Evaluations with low score + error add to failed_patterns."""
    t = Teammate(
        id=gen_uuid(), name="FailBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python"], execution_count=0,
    )
    db_session.add(t)
    await db_session.commit()

    from backend.models import ExecutionRecordModel, EvaluationRecordModel

    exec_rec = ExecutionRecordModel(
        execution_id="fail-exec-1",
        task_id="task-fail-1",
        teammate="FailBot",
        model="gpt-4o",
        status="FAILED",
        error="Timeout after 30s",
        dag_node_id="deployment",
    )
    db_session.add(exec_rec)
    eval_rec = EvaluationRecordModel(
        id=gen_uuid(),
        execution_id="fail-exec-1",
        status="EVALUATED",
        score=0.15,
    )
    db_session.add(eval_rec)
    await db_session.commit()

    await ExperienceStore.update_from_evaluation("fail-exec-1", db=db_session)
    await db_session.refresh(t)

    assert any("deployment" in f for f in t.failed_patterns), f"got {t.failed_patterns}"
    assert any("deployment" in w for w in t.weaknesses), f"got {t.weaknesses}"


@pytest.mark.asyncio
async def test_selector_memory_score_changes(db_session):
    """TeammateSelector._memory_score reflects learned vs failed ratio."""
    # Teammate with all successes
    t_good = Teammate(
        id=gen_uuid(), name="GoodBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python"], learned_patterns=["Completed coding successfully"],
        failed_patterns=[],
    )
    # Teammate with all failures
    t_bad = Teammate(
        id=gen_uuid(), name="BadBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python"], learned_patterns=[],
        failed_patterns=["Failed on deployment"],
    )
    # Teammate with no memory
    t_neutral = Teammate(
        id=gen_uuid(), name="NeutralBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python"],
    )
    db_session.add_all([t_good, t_bad, t_neutral])
    await db_session.commit()

    p_good = TeammateProfile.from_orm(t_good)
    p_bad = TeammateProfile.from_orm(t_bad)
    p_neutral = TeammateProfile.from_orm(t_neutral)

    assert TeammateSelector._memory_score(p_good) == 1.0
    assert TeammateSelector._memory_score(p_bad) == 0.0
    assert TeammateSelector._memory_score(p_neutral) == 0.5


@pytest.mark.asyncio
async def test_selector_weighted_scoring(db_session):
    """New weights: skill 40%, experience 30%, memory 20%, availability 10%."""
    # Same skills, different memory → memory determines order
    t_learned = Teammate(
        id=gen_uuid(), name="LearnedBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python", "go"], average_score=0.8, execution_count=10,
        learned_patterns=["Completed coding successfully"],
        failed_patterns=[],
    )
    t_failed = Teammate(
        id=gen_uuid(), name="FailedBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        skills=["python", "go"], average_score=0.8, execution_count=10,
        learned_patterns=[],
        failed_patterns=["Failed on coding"],
    )
    db_session.add_all([t_learned, t_failed])
    await db_session.commit()

    profiles = await TeammateSelector.recommend("coding", top_n=2, db=db_session)
    assert len(profiles) == 2
    # LearnedBot should rank higher (same skill+exp but better memory)
    assert profiles[0].name == "LearnedBot"


@pytest.mark.asyncio
async def test_memory_api_endpoint(db_session):
    """GET /api/teammates/{id}/memory returns memory fields."""
    t = Teammate(
        id=gen_uuid(), name="APIBot", role="engineer",
        model_provider="openrouter", model_name="auto",
        strengths=["Excels at coding"],
        weaknesses=["Struggles with design"],
        learned_patterns=["Completed coding successfully"],
        failed_patterns=["Failed on deployment"],
        preferred_tools=["artifact", "web_search"],
    )
    db_session.add(t)
    await db_session.commit()

    # Simulate the route directly
    from backend.routes.teammates import get_teammate_memory

    result = await get_teammate_memory(t.id, db=db_session)
    assert result["teammate_id"] == t.id
    assert "Excels at coding" in result["strengths"]
    assert "Failed on deployment" in result["failed_patterns"]
    assert "artifact" in result["preferred_tools"]
