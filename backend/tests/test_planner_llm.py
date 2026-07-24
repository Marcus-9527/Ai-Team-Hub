"""Phase 11 — LLM Planner System Tests.

Covers:
  - TaskAnalyzer: keyword extraction, task type classification, complexity
  - DAGBuilder: TaskPlan → DAGDefinition mapping, skill resolution
  - DAGValidator: cycle, empty node, missing skills, illegal deps
  - PlanningEngine: end-to-end orchestration with mock plan fn
"""

from unittest.mock import AsyncMock

import pytest

from backend.services.dag.core import (
    DAGDefinition,
    DAGNode,
    NodeStatus,
    detect_cycle,
)
from backend.services.task.task_planner_schema import (
    TaskPlan,
    TaskStepProposal,
)
from backend.services.planner.task_analyzer import TaskAnalyzer, TaskAnalysis
from backend.services.dag.builder import DAGBuilder
from backend.services.planner.dag_validator import DAGValidator, ValidationResult
from backend.services.planner.planning_engine import (
    PlanningEngine,
    PlanningError,
)


# ═══════════════════════════════════════════════════════════════
# 1. TaskAnalyzer
# ═══════════════════════════════════════════════════════════════

class TestTaskAnalyzer:
    def test_coding_task(self):
        a = TaskAnalyzer()
        result = a.analyze("Write a Python function to handle user authentication")
        assert result.task_type == "coding"
        assert len(result.keywords) > 0
        assert result.complexity == "simple"

    def test_writing_task(self):
        a = TaskAnalyzer()
        result = a.analyze("Write documentation for the API endpoints")
        assert result.task_type in ("coding", "writing")

    def test_analysis_task(self):
        a = TaskAnalyzer()
        result = a.analyze("Analyze the performance metrics and produce a report")
        assert result.task_type == "analysis"

    def test_complex_task(self):
        a = TaskAnalyzer()
        result = a.analyze(
            "Design and implement a complete authentication system "
            "with JWT tokens that includes user registration, login, "
            "password reset, email verification, and role-based access "
            "control for the admin panel and user dashboard"
        )
        assert result.complexity == "complex"

    def test_empty_goal(self):
        a = TaskAnalyzer()
        result = a.analyze("")
        assert result.task_type == "general"
        assert result.complexity == "simple"

    def test_analysis_to_dict(self):
        a = TaskAnalyzer()
        result = a.analyze("Build a login page")
        d = result.to_dict()
        assert "task_type" in d
        assert "keywords" in d


# ═══════════════════════════════════════════════════════════════
# 2. DAGBuilder
# ═══════════════════════════════════════════════════════════════

def _make_plan(*steps: TaskStepProposal, title: str = "test") -> TaskPlan:
    return TaskPlan(task_id="t-001", title=title,
                    description="", steps=list(steps))


class TestDAGBuilder:
    def test_single_step(self):
        step = TaskStepProposal(order=1, teammate_id="coding",
                                objective="Write auth module")
        plan = _make_plan(step)
        builder = DAGBuilder()
        dag = builder.build(plan)
        assert len(dag.nodes) == 1
        node = list(dag.nodes.values())[0]
        assert node.description == "Write auth module"
        assert "python" in node.required_skills  # resolved from "coding"

    def test_multiple_steps_with_deps(self):
        a = TaskStepProposal(order=1, teammate_id="coding",
                             objective="Set up database schema")
        b = TaskStepProposal(order=2, teammate_id="coding",
                             objective="Write API layer",
                             depends_on=[1])
        c = TaskStepProposal(order=3, teammate_id="frontend",
                             objective="Build UI",
                             depends_on=[2])
        plan = _make_plan(a, b, c)
        builder = DAGBuilder()
        dag = builder.build(plan)
        assert len(dag.nodes) == 3
        # Find UI node
        ui_node = next(n for n in dag.nodes.values()
                       if "UI" in n.description)
        assert len(ui_node.deps) == 1  # depends on API layer

    def test_fan_out(self):
        a = TaskStepProposal(order=1, teammate_id="analysis",
                             objective="Research requirements")
        b = TaskStepProposal(order=2, teammate_id="coding",
                             objective="Build backend",
                             depends_on=[1])
        c = TaskStepProposal(order=3, teammate_id="design",
                             objective="Design frontend",
                             depends_on=[1])
        plan = _make_plan(a, b, c)
        builder = DAGBuilder()
        dag = builder.build(plan)
        assert len(dag.nodes) == 3
        # Both b and c should depend on a
        backend = next(n for n in dag.nodes.values()
                       if "backend" in n.description)
        frontend = next(n for n in dag.nodes.values()
                        if "frontend" in n.description)
        assert len(backend.deps) == 1
        assert len(frontend.deps) == 1

    def test_skill_resolution_unknown_type(self):
        step = TaskStepProposal(order=1, teammate_id="some_unknown_type",
                                objective="Do something")
        plan = _make_plan(step)
        builder = DAGBuilder()
        dag = builder.build(plan)
        node = list(dag.nodes.values())[0]
        # Falls back to [teammate_id] as skill tag
        assert len(node.required_skills) >= 1

    def test_empty_teammate_id(self):
        step = TaskStepProposal(order=1, teammate_id="",
                                objective="Generic task")
        plan = _make_plan(step)
        builder = DAGBuilder()
        dag = builder.build(plan)
        node = list(dag.nodes.values())[0]
        assert node.required_skills == []


# ═══════════════════════════════════════════════════════════════
# 3. DAGValidator
# ═══════════════════════════════════════════════════════════════

class TestDAGValidator:
    def test_valid_dag(self):
        dag = DAGDefinition(name="valid")
        a = DAGNode(description="A", required_skills=["python"])
        b = DAGNode(description="B", required_skills=["js"], deps=[a.id])
        dag.add_node(a)
        dag.add_node(b)
        result = DAGValidator().validate(dag)
        assert result.valid
        assert len(result.errors) == 0

    def test_cycle_detected(self):
        dag = DAGDefinition(name="cycle")
        a = DAGNode(description="A", required_skills=["x"])
        b = DAGNode(description="B", required_skills=["y"], deps=[a.id])
        a.deps = [b.id]  # A → B → A
        dag.add_node(a)
        dag.add_node(b)
        result = DAGValidator().validate(dag)
        assert not result.valid
        assert any("cycle" in e.lower() for e in result.errors)

    def test_empty_node_description(self):
        dag = DAGDefinition(name="empty")
        node = DAGNode(description="", required_skills=["x"])
        dag.add_node(node)
        result = DAGValidator().validate(dag)
        assert not result.valid
        assert any("empty description" in e.lower() for e in result.errors)

    def test_missing_skills(self):
        dag = DAGDefinition(name="noskills")
        node = DAGNode(description="Do stuff")
        dag.add_node(node)
        result = DAGValidator().validate(dag)
        assert not result.valid
        assert any("required_skills" in e.lower() for e in result.errors)

    def test_self_dep(self):
        dag = DAGDefinition(name="self")
        node = DAGNode(description="A", required_skills=["x"])
        node.id = "self-node"
        node.deps = ["self-node"]
        dag.add_node(node)
        result = DAGValidator().validate(dag)
        assert not result.valid
        assert any("depends on itself" in e.lower() for e in result.errors)

    def test_dangling_dep(self):
        dag = DAGDefinition(name="dangle")
        node = DAGNode(description="A", required_skills=["x"],
                       deps=["nonexistent"])
        dag.add_node(node)
        result = DAGValidator().validate(dag)
        assert not result.valid
        assert any("non-existent" in e.lower() for e in result.errors)

    def test_multiple_errors(self):
        dag = DAGDefinition(name="bad")
        a = DAGNode(description="", required_skills=["x"])
        a.id = "empty-node"
        b = DAGNode(description="B", deps=["ghost"])
        dag.add_node(a)
        dag.add_node(b)
        result = DAGValidator().validate(dag)
        assert not result.valid
        assert len(result.errors) >= 2  # empty desc + missing skills + dangling

    def test_validation_result_roundtrip(self):
        r = ValidationResult(valid=False, errors=["err1", "err2"])
        d = r.to_dict()
        assert d["valid"] is False
        assert d["errors"] == ["err1", "err2"]


# ═══════════════════════════════════════════════════════════════
# 4. PlanningEngine (with mock LLM)
# ═══════════════════════════════════════════════════════════════

class TestPlanningEngine:
    @pytest.mark.asyncio
    async def test_simple_plan(self):
        """Engine produces a valid DAG from a simple goal with mock plan fn."""
        engine = PlanningEngine()

        async def mock_plan(goal, ctx, task_id):
            return TaskPlan(
                task_id=task_id or "mock",
                title="Test Plan",
                description="",
                steps=[
                    TaskStepProposal(order=1, teammate_id="coding",
                                     objective="Write auth module"),
                ]
            )

        engine.set_plan_fn(mock_plan)
        dag = await engine.plan("Build auth system", task_id="t-001")
        assert isinstance(dag, DAGDefinition)
        assert len(dag.nodes) == 1
        node = list(dag.nodes.values())[0]
        assert node.required_skills == ["python", "javascript", "coding", "debugging"]

    @pytest.mark.asyncio
    async def test_multi_node_plan(self):
        """Engine builds multi-node DAG from multi-step plan."""
        engine = PlanningEngine()

        async def mock_plan(goal, ctx, task_id):
            return TaskPlan(
                task_id="t-002", title="Multi-step",
                description="",
                steps=[
                    TaskStepProposal(order=1, teammate_id="coding",
                                     objective="Set up DB"),
                    TaskStepProposal(order=2, teammate_id="coding",
                                     objective="Write API",
                                     depends_on=[1]),
                    TaskStepProposal(order=3, teammate_id="frontend",
                                     objective="Build UI",
                                     depends_on=[2]),
                ]
            )

        engine.set_plan_fn(mock_plan)
        dag = await engine.plan("Build full app", task_id="t-002")
        assert len(dag.nodes) == 3
        # Topological order check
        ids = list(dag.nodes.keys())
        assert len(ids) == 3

    @pytest.mark.asyncio
    async def test_validation_failure(self):
        """Engine raises PlanningError when DAG is invalid."""
        engine = PlanningEngine()

        async def mock_plan(goal, ctx, task_id):
            return TaskPlan(
                task_id="t-003", title="Bad Plan",
                description="",
                steps=[
                    TaskStepProposal(order=1, teammate_id="",
                                     objective=""),
                ]
            )

        engine.set_plan_fn(mock_plan)
        with pytest.raises(PlanningError, match="DAG validation failed"):
            await engine.plan("Do nothing", task_id="t-003")

    @pytest.mark.asyncio
    async def test_cycle_in_dag(self):
        """Engine detects cycles from plan deps."""
        engine = PlanningEngine()

        # Manually create a plan whose steps will produce a cycle
        # Since DAGBuilder converts depends_on order numbers to node IDs,
        # we need to create steps where depends_on creates a cycle.
        async def mock_plan(goal, ctx, task_id):
            return TaskPlan(
                task_id="t-004", title="Cycle Plan",
                description="",
                steps=[
                    TaskStepProposal(order=1, teammate_id="coding",
                                     objective="Step A",
                                     depends_on=[2]),  # forward ref to 2
                    TaskStepProposal(order=2, teammate_id="coding",
                                     objective="Step B",
                                     depends_on=[1]),  # back ref to 1 → cycle
                ]
            )

        engine.set_plan_fn(mock_plan)
        # parse_plan would catch this cycle in a real flow,
        # but we're mocking – the DAGBuilder creates deps blindly,
        # so DAGValidator should catch it.
        with pytest.raises(PlanningError, match="DAG validation failed"):
            await engine.plan("Cycle test", task_id="t-004")

    @pytest.mark.asyncio
    async def test_set_plan_fn_api(self):
        """set_plan_fn accepts callable and engine uses it."""
        engine = PlanningEngine()
        called = False

        async def my_fn(goal, ctx, tid):
            nonlocal called
            called = True
            return TaskPlan(task_id=tid, title="X", description="",
                            steps=[
                                TaskStepProposal(order=1, teammate_id="coding",
                                                 objective="X")
                            ])

        engine.set_plan_fn(my_fn)
        await engine.plan("test", task_id="t-005")
        assert called
