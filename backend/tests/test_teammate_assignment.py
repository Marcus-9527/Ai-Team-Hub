"""
Phase 12 — Teammate Auto Assignment Tests.

Coverage:
  1. recommend_by_skills — exact skill match
  2. recommend_by_skills — multi-candidate scoring order
  3. recommend_by_skills — no match fallback
  4. DAG auto-assignment via DagExecutor — teammate set
  5. DAG auto-assignment — selected_teammate_id + assigned_at
  6. DAG auto-assignment — empty DB → no teammate (resilient fallback)
  7. DAGNode field serialisation
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import Teammate, gen_uuid
from backend.services.dag.core import DAGDefinition, DAGNode, NodeStatus
from backend.services.planner.dag_executor import DagExecutor, DAGStore, reset_dag_store
from backend.services.teammate_intelligence import TeammateSelector, TeammateProfile


# ═══════════════════════════════════════════════════════════════
# 1-3: recommend_by_skills
# ═══════════════════════════════════════════════════════════════


class TestRecommendBySkills:
    @pytest.mark.asyncio
    async def test_exact_skill_match(self, db_session):
        """Candidate with all required skills ranks first."""
        t = Teammate(
            id=gen_uuid(), name="SkillBot", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "go", "coding"],
            success_rate=0.9, average_score=0.85, execution_count=20,
        )
        db_session.add(t)
        await db_session.commit()

        profiles = await TeammateSelector.recommend_by_skills(
            ["python", "go", "coding"], top_n=1, db=db_session,
        )
        assert len(profiles) == 1
        assert profiles[0].name == "SkillBot"

    @pytest.mark.asyncio
    async def test_multi_candidate_ranking(self, db_session):
        """Better skill + experience match should rank first."""
        t1 = Teammate(
            id=gen_uuid(), name="PythonMaster", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "coding", "debugging"],
            success_rate=0.9, average_score=0.88, execution_count=50,
        )
        t2 = Teammate(
            id=gen_uuid(), name="DesignerJane", role="designer",
            model_provider="openrouter", model_name="auto",
            skills=["ui_design", "ux", "frontend"],
            success_rate=0.7, average_score=0.6, execution_count=5,
        )
        db_session.add_all([t1, t2])
        await db_session.commit()

        # Phase 22: DB filtering excludes DesignerJane (no python/coding skill)
        profiles = await TeammateSelector.recommend_by_skills(
            ["python", "coding"], top_n=2, db=db_session,
        )
        assert len(profiles) == 1  # DesignerJane filtered at DB level
        assert profiles[0].name == "PythonMaster"  # higher skill match + experience

    @pytest.mark.asyncio
    async def test_no_match_fallback(self, db_session):
        """When no teammate has the required skills, returns empty (DB filter)."""
        t = Teammate(
            id=gen_uuid(), name="DesignBot", role="designer",
            model_provider="openrouter", model_name="auto",
            skills=["ui_design", "ux"],
            success_rate=0.5, average_score=0.5, execution_count=3,
        )
        db_session.add(t)
        await db_session.commit()

        profiles = await TeammateSelector.recommend_by_skills(
            ["quantum_physics", "fusion"], top_n=1, db=db_session,
        )
        assert len(profiles) == 0  # DB filtered, no row matches

    @pytest.mark.asyncio
    async def test_scoring_weights(self, db_session):
        """Sanity: skill(0.6) + experience(0.3) + availability(0.1) produces valid score."""
        t = Teammate(
            id=gen_uuid(), name="ScoredBot", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python"], average_score=0.8, execution_count=10,
        )
        db_session.add(t)
        await db_session.commit()

        profiles = await TeammateSelector.recommend_by_skills(
            ["python"], top_n=1, db=db_session,
        )
        assert len(profiles) == 1
        assert 0.0 <= profiles[0].average_score <= 1.0
        assert profiles[0].name == "ScoredBot"


# ═══════════════════════════════════════════════════════════════
# 4-6: DAG auto-assignment via DagExecutor
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def _store_in_memory():
    reset_dag_store()
    store = DAGStore(db_url="sqlite:///:memory:")
    import backend.services.planner.dag_executor as _de
    _de._dag_store = store
    yield
    reset_dag_store()


@pytest.fixture
def mock_runtime():
    """ExecutionRuntime that instantly completes tasks."""
    rt = MagicMock()

    async def fake_execute(description="", priority=2, intent="",
                            provider=None, model=None,
                            api_key=None, base_url=None, teammate=None, wait=False):
        task = MagicMock()
        task.id = "mock_exec"
        task.status = "COMPLETED"
        task.result = f"Result: {description[:50]}"
        task.error = ""
        task.teammate = teammate or ""
        return task

    rt.execute = AsyncMock(side_effect=fake_execute)
    return rt


class TestDagAutoAssignment:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_store_in_memory")
    async def test_auto_assigns_teammate(self, db_session, mock_runtime):
        """Node with required_skills gets teammate auto-assigned via TeammateSelector."""
        t = Teammate(
            id=gen_uuid(), name="AutoBot", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "coding"],
            success_rate=0.9, average_score=0.85, execution_count=10,
        )
        db_session.add(t)
        await db_session.commit()

        # Patch TeammateSelector.recommend_by_skills to use our real DB
        orig = TeammateSelector.recommend_by_skills

        async def patched_recommend(required_skills, top_n=1, db=None, **kwargs):
            return await orig(required_skills, top_n=top_n, db=db_session, **kwargs)

        with patch.object(TeammateSelector, "recommend_by_skills", side_effect=patched_recommend):
            node = DAGNode(description="Build API", required_skills=["python", "coding"])
            dag = DAGDefinition(name="test-dag")
            dag.add_node(node)
            executor = DagExecutor(mock_runtime)
            await executor.execute_dag(dag)

        assert node.teammate == "AutoBot"
        assert node.selected_teammate_id == t.id
        assert node.assigned_at > 0

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_store_in_memory")
    async def test_skips_assignment_when_teammate_set(self, db_session, mock_runtime):
        """Node with pre-set teammate is not auto-assigned."""
        node = DAGNode(description="Manual", teammate="PreExistingBot",
                       required_skills=["python"])
        dag = DAGDefinition(name="test-dag")
        dag.add_node(node)

        assign_spy = AsyncMock()
        with patch.object(TeammateSelector, "recommend_by_skills", assign_spy):
            executor = DagExecutor(mock_runtime)
            await executor.execute_dag(dag)

        assert node.teammate == "PreExistingBot"
        assign_spy.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_store_in_memory")
    async def test_skips_when_no_required_skills(self, db_session, mock_runtime):
        """Node without required_skills does not trigger auto-assignment."""
        node = DAGNode(description="No skills required")
        dag = DAGDefinition(name="test-dag")
        dag.add_node(node)

        assign_spy = AsyncMock()
        with patch.object(TeammateSelector, "recommend_by_skills", assign_spy):
            executor = DagExecutor(mock_runtime)
            await executor.execute_dag(dag)

        assert node.teammate == ""
        assert node.selected_teammate_id == ""
        assign_spy.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_store_in_memory")
    async def test_fallback_when_no_teammates(self, mock_runtime):
        """Empty DB → auto-assignment fails gracefully, node has empty teammate."""
        node = DAGNode(description="Lonely node", required_skills=["python"])
        dag = DAGDefinition(name="test-dag")
        dag.add_node(node)
        executor = DagExecutor(mock_runtime)
        with patch.object(TeammateSelector, "recommend_by_skills", AsyncMock(return_value=[])):
            await executor.execute_dag(dag)

        # teammate stays empty (no teammates found)
        assert node.teammate == ""
        assert node.selected_teammate_id == ""


# ═══════════════════════════════════════════════════════════════
# 7: DAGNode field serialisation
# ═══════════════════════════════════════════════════════════════


class TestDAGNodeNewFields:
    def test_new_fields_in_to_dict(self):
        node = DAGNode(description="Test", required_skills=["python"])
        node.teammate = "AutoAssigned"
        node.selected_teammate_id = "tm-42"
        node.assigned_at = 1234567890.0
        d = node.to_dict()
        assert d["selected_teammate_id"] == "tm-42"
        assert d["assigned_at"] == 1234567890.0
        assert d["teammate"] == "AutoAssigned"
        assert "python" in d["required_skills"]

    def test_default_values_empty(self):
        node = DAGNode(description="Empty")
        assert node.selected_teammate_id == ""
        assert node.assigned_at == 0.0


# ═══════════════════════════════════════════════════════════════
# Phase 22 — TeammateSelector Reliability Patch
# ═══════════════════════════════════════════════════════════════


class TestChineseTaskMatching:
    def test_chinese_keyword_coding(self):
        """Chinese keyword '后端' triggers coding type."""
        from backend.services.planner.task_analyzer import TaskAnalyzer, TASK_TYPE_PATTERNS
        assert "后端" in TASK_TYPE_PATTERNS["coding"]
        assert "数据库" in TASK_TYPE_PATTERNS["coding"]

        ta = TaskAnalyzer()
        r = ta.analyze("写一个后端接口")
        assert r.task_type == "coding"

    def test_chinese_keyword_design(self):
        """Chinese keyword '前端' triggers design type."""
        from backend.services.planner.task_analyzer import TaskAnalyzer
        ta = TaskAnalyzer()
        r = ta.analyze("设计一个用户页面")
        assert r.task_type == "design"

    def test_chinese_keyword_devops(self):
        """Chinese keyword '部署' triggers devops type."""
        from backend.services.planner.task_analyzer import TaskAnalyzer
        ta = TaskAnalyzer()
        r = ta.analyze("配置服务器部署 docker 容器")
        assert r.task_type == "devops"

    def test_chinese_testing_keyword(self):
        """New 'testing' type matches Chinese '测试' keyword."""
        from backend.services.planner.task_analyzer import TaskAnalyzer, TASK_TYPE_PATTERNS
        assert "testing" in TASK_TYPE_PATTERNS
        ta = TaskAnalyzer()
        r = ta.analyze("跑回归测试验证覆盖率")
        assert r.task_type == "testing"

    def test_english_still_works(self):
        """English keywords still match after CJK additions."""
        from backend.services.planner.task_analyzer import TaskAnalyzer
        ta = TaskAnalyzer()
        assert ta.analyze("fix login api bug").task_type == "coding"
        assert ta.analyze("docker compose ci pipeline").task_type == "devops"


class TestDagDuplicateAssignment:
    """Multi-node DAG where nodes share required_skills should get different teammates."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_store_in_memory")
    async def test_different_teammates_per_node(self, db_session):
        """Two nodes needing python+coding get different teammates when 2 available."""
        t1 = Teammate(
            id=gen_uuid(), name="Alice", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "go", "coding"],
            success_rate=0.9, average_score=0.85, execution_count=20,
        )
        t2 = Teammate(
            id=gen_uuid(), name="Bob", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "coding", "debugging"],
            success_rate=0.8, average_score=0.75, execution_count=10,
        )
        db_session.add_all([t1, t2])
        await db_session.commit()

        node_a = DAGNode(description="Build API", required_skills=["python", "coding"])
        node_b = DAGNode(description="Write tests", required_skills=["python", "coding"])
        dag = DAGDefinition(name="multi-dag")
        dag.add_node(node_a)
        dag.add_node(node_b)

        from backend.services.planner.dag_executor import DagExecutor
        from backend.services.runtime.executor import ExecutionRuntime
        rt = AsyncMock(spec=ExecutionRuntime)
        rt.execute = AsyncMock(return_value=MagicMock(
            id="mock", status="COMPLETED", result="ok", error="", teammate="",
        ))

        orig = TeammateSelector.recommend_by_skills
        async def patched(rs, top_n=1, db=None, **kwargs):
            return await orig(rs, top_n=top_n, db=db_session, **kwargs)

        with patch.object(TeammateSelector, "recommend_by_skills", side_effect=patched):
            executor = DagExecutor(rt)
            await executor.execute_dag(dag)

        assert node_a.teammate, "node_a should have a teammate"
        assert node_b.teammate, "node_b should have a teammate"
        assert node_a.teammate != node_b.teammate, (
            f"nodes should have different teammates, got {node_a.teammate} and {node_b.teammate}"
        )

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_store_in_memory")
    async def test_fallback_when_one_teammate(self, db_session):
        """Only one teammate available → first node gets it, second gets none."""
        t = Teammate(
            id=gen_uuid(), name="SoloBot", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "coding"],
            success_rate=0.9, average_score=0.85, execution_count=10,
        )
        db_session.add(t)
        await db_session.commit()

        node_a = DAGNode(description="Build API", required_skills=["python", "coding"])
        node_b = DAGNode(description="Fix bug", required_skills=["python"])
        dag = DAGDefinition(name="single-tm-dag")
        dag.add_node(node_a)
        dag.add_node(node_b)

        from backend.services.planner.dag_executor import DagExecutor
        from backend.services.runtime.executor import ExecutionRuntime
        rt = AsyncMock(spec=ExecutionRuntime)
        rt.execute = AsyncMock(return_value=MagicMock(
            id="mock", status="COMPLETED", result="ok", error="", teammate="",
        ))

        orig = TeammateSelector.recommend_by_skills
        async def patched(rs, top_n=1, db=None, **kwargs):
            return await orig(rs, top_n=top_n, db=db_session, **kwargs)

        with patch.object(TeammateSelector, "recommend_by_skills", side_effect=patched):
            executor = DagExecutor(rt)
            await executor.execute_dag(dag)

        # First node gets SoloBot; second has no available teammate
        assert node_a.teammate == "SoloBot"
        assert node_b.teammate == ""  # SoloBot already assigned

    @pytest.mark.asyncio
    async def test_exclude_teammate_names_filter(self, db_session):
        """exclude_teammate_names excludes named teammates from results."""
        t1 = Teammate(
            id=gen_uuid(), name="KeepBot", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "coding"],
            success_rate=0.9, average_score=0.85, execution_count=10,
        )
        t2 = Teammate(
            id=gen_uuid(), name="SkipBot", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "coding"],
            success_rate=0.9, average_score=0.85, execution_count=10,
        )
        db_session.add_all([t1, t2])
        await db_session.commit()

        profiles = await TeammateSelector.recommend_by_skills(
            ["python", "coding"], top_n=2,
            exclude_teammate_names={"SkipBot"}, db=db_session,
        )
        names = [p.name for p in profiles]
        assert "SkipBot" not in names
        assert "KeepBot" in names


class TestNoSuitableTeammateFallback:
    """When no teammate matches the required skills, gracefully fall back."""

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, db_session):
        """No teammate with matching skills → empty list (no DB rows to consider)."""
        profiles = await TeammateSelector.recommend_by_skills(
            ["quantum_physics", "fusion"], top_n=1, db=db_session,
        )
        assert len(profiles) == 0

    @pytest.mark.asyncio
    async def test_mismatched_skills_no_rows(self, db_session):
        """Teammates exist but with wrong skills → no recommendations."""
        t = Teammate(
            id=gen_uuid(), name="DesignBot", role="designer",
            model_provider="openrouter", model_name="auto",
            skills=["ui_design", "ux"],
            success_rate=0.5, average_score=0.5, execution_count=3,
        )
        db_session.add(t)
        await db_session.commit()

        profiles = await TeammateSelector.recommend_by_skills(
            ["python", "go"], top_n=1, db=db_session,
        )
        # DB filtering should exclude DesignBot (no python/go in skills)
        assert len(profiles) == 0


class TestQueryFiltering:
    """Verify recommend_by_skills issues DB-level filters, not full table scans."""

    @pytest.mark.asyncio
    async def test_filter_by_skills(self, db_session):
        """DB query only returns teammates with overlapping skills."""
        t_match = Teammate(
            id=gen_uuid(), name="MatchBot", role="engineer",
            model_provider="openrouter", model_name="auto",
            skills=["python", "go", "coding"],
            success_rate=0.9, average_score=0.85, execution_count=10,
        )
        t_mismatch = Teammate(
            id=gen_uuid(), name="MismatchBot", role="designer",
            model_provider="openrouter", model_name="auto",
            skills=["ui_design", "ux"],
            success_rate=0.5, average_score=0.5, execution_count=5,
        )
        db_session.add_all([t_match, t_mismatch])
        await db_session.commit()

        profiles = await TeammateSelector.recommend_by_skills(
            ["python"], top_n=10, db=db_session,
        )
        names = [p.name for p in profiles]
        assert "MatchBot" in names
        assert "MismatchBot" not in names  # filtered at DB level
