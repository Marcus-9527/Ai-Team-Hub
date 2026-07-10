"""
test_task_planner.py — Phase A: Planner Core tests.

Coverage:
  1. Schema — TaskPlan / TaskStepProposal creation + dict round-trip
  2. Parser — valid JSON parsing (raw / code fences / embedded)
  3. Parser — invalid / empty / malformed output
  4. Parser — order validation (gaps, duplicates, non-1 start)
  5. Parser — dependency validation (missing refs, self-ref, cycles)
  6. Parser — confidence field (valid range, types)
  7. Driver — generate_plan with mock MAEOS (success, retry, failure)
  8. Driver — validate_plan warnings
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.task.task_planner_schema import (
    TaskPlan,
    TaskStepProposal,
    TaskPlannerInput,
)
from backend.services.task.task_planner_parser import (
    parse_plan,
    PlannerJSONError,
    PlannerSchemaError,
    PlannerEmptyPlanError,
    PlannerOrderError,
    PlannerDependencyError,
    validate_plan as parser_validate_plan,
)
from backend.services.task.task_planner_driver import (
    generate_plan,
    validate_plan,
    PlanningError,
)


# ═══════════════════════════════════════════════════════════════
# 1. Schema Tests
# ═══════════════════════════════════════════════════════════════

class TestTaskStepProposal:
    def test_minimal(self):
        """Step with only required fields."""
        step = TaskStepProposal(order=1, teammate_id="teammate_b", objective="Write code")
        assert step.order == 1
        assert step.teammate_id == "teammate_b"
        assert step.objective == "Write code"
        assert step.depends_on == []
        assert step.risk_level == "LOW"
        assert step.confidence == 0.0

    def test_full(self):
        """Step with all fields."""
        step = TaskStepProposal(
            order=1,
            teammate_id="teammate_b",
            objective="Write auth module",
            expected_output="auth.py with JWT",
            input_context_hint="Use FastAPI",
            depends_on=[2],
            risk_level="HIGH",
            estimated_cost=200.0,
            estimated_tokens=4096,
            requires_approval=True,
            validation_criteria="All endpoints return 200",
            confidence=0.85,
            rationale="Auth is critical path",
        )
        assert step.risk_level == "HIGH"
        assert step.confidence == 0.85
        assert step.requires_approval is True

    def test_to_dict_round_trip(self):
        """Step serializes and deserializes correctly."""
        original = TaskStepProposal(
            order=1,
            teammate_id="teammate_b",
            objective="Write code",
            confidence=0.9,
            rationale="Core step",
        )
        d = original.to_dict()
        restored = TaskStepProposal.from_dict(d)
        assert restored.order == original.order
        assert restored.teammate_id == original.teammate_id
        assert restored.confidence == original.confidence
        assert restored.rationale == original.rationale


class TestTaskPlan:
    def test_minimal(self):
        """Plan with only required fields."""
        steps = [TaskStepProposal(order=1, teammate_id="teammate_b", objective="Code")]
        plan = TaskPlan(
            task_id="task-001",
            title="Test Plan",
            description="A test",
            steps=steps,
        )
        assert plan.task_id == "task-001"
        assert len(plan.steps) == 1
        assert plan.created_at > 0  # auto-set

    def test_full(self):
        """Plan with all fields."""
        steps = [
            TaskStepProposal(order=1, teammate_id="teammate_a", objective="Analyze"),
            TaskStepProposal(order=2, teammate_id="teammate_b", objective="Implement"),
        ]
        plan = TaskPlan(
            task_id="task-001",
            title="Full Plan",
            description="Description",
            steps=steps,
            confidence=0.88,
            rationale="Standard approach",
            estimated_total_cost=500.0,
            risk_level="MEDIUM",
        )
        assert plan.confidence == 0.88
        assert plan.rationale == "Standard approach"
        assert plan.risk_level == "MEDIUM"

    def test_to_dict_round_trip(self):
        """Plan serializes and deserializes correctly."""
        steps = [
            TaskStepProposal(order=1, teammate_id="teammate_a", objective="Analyze",
                             confidence=0.9, rationale="First step"),
            TaskStepProposal(order=2, teammate_id="teammate_b", objective="Implement",
                             depends_on=[1], confidence=0.8, rationale="Build it"),
        ]
        original = TaskPlan(
            task_id="task-001",
            title="R-T Plan",
            description="Round trip test",
            steps=steps,
            confidence=0.85,
            rationale="Chosen approach",
        )
        d = original.to_dict()
        restored = TaskPlan.from_dict(d)
        assert restored.task_id == original.task_id
        assert restored.confidence == original.confidence
        assert restored.rationale == original.rationale
        assert len(restored.steps) == 2
        assert restored.steps[0].confidence == 0.9
        assert restored.steps[1].depends_on == [1]

    def test_auto_timestamp(self):
        """Plan auto-sets created_at on init."""
        plan = TaskPlan(
            task_id="t",
            title="T",
            description="D",
            steps=[],
        )
        assert plan.created_at > 0


class TestTaskPlannerInput:
    def test_to_prompt_basic(self):
        """Input serialization includes goal."""
        inp = TaskPlannerInput(goal="Build auth")
        prompt = inp.to_prompt()
        assert "Build auth" in prompt

    def test_to_prompt_with_context(self):
        """Input serialization includes context sections."""
        inp = TaskPlannerInput(
            goal="Build auth",
            context={
                "global_rules": ["Use async/await"],
                "workspace_decisions": [
                    {"decision": "Use FastAPI", "reasoning": "Team preference"}
                ],
                "channel_history": [
                    {"role": "user", "content": "We need auth"}
                ],
            },
        )
        prompt = inp.to_prompt()
        assert "Use async/await" in prompt
        assert "Use FastAPI" in prompt
        assert "We need auth" in prompt


# ═══════════════════════════════════════════════════════════════
# Helpers: valid/invalid plan JSON strings
# ═══════════════════════════════════════════════════════════════

def _valid_plan_json(task_id="task-001", steps_count=3) -> str:
    """Generate a valid plan JSON with given step count."""
    steps = []
    for i in range(1, steps_count + 1):
        steps.append({
            "order": i,
            "teammate_id": "teammate_b" if i % 2 == 0 else "teammate_a",
            "objective": f"Step {i} objective",
            "expected_output": f"Output {i}",
            "input_context_hint": f"Context {i}",
            "depends_on": [i - 1] if i > 1 else [],
            "risk_level": "LOW",
            "estimated_cost": 50.0,
            "estimated_tokens": 1024,
            "requires_approval": False,
            "validation_criteria": "Passes review",
            "confidence": 0.9,
            "rationale": f"Reason for step {i}",
        })
    plan = {
        "task_id": task_id,
        "title": "Test Plan",
        "description": "A valid test plan",
        "steps": steps,
        "confidence": 0.85,
        "rationale": "Standard plan",
        "estimated_total_cost": 150.0,
        "risk_level": "LOW",
    }
    return json.dumps(plan, indent=2)


# ═══════════════════════════════════════════════════════════════
# 2 & 3. Parser — JSON extraction and schema validation
# ═══════════════════════════════════════════════════════════════

class TestParserJsonExtraction:
    def test_parse_raw_json(self):
        """Parse a plain JSON string."""
        plan = parse_plan(_valid_plan_json())
        assert len(plan.steps) == 3
        assert plan.task_id == "task-001"

    def test_parse_with_code_fences(self):
        """Parse JSON inside ```json ... ``` fences."""
        raw = f"```json\n{_valid_plan_json()}\n```"
        plan = parse_plan(raw)
        assert len(plan.steps) == 3

    def test_parse_with_extra_text(self):
        """Parse JSON with leading/trailing text."""
        raw = f"Here is the plan:\n\n{_valid_plan_json()}\n\nEnd."
        plan = parse_plan(raw)
        assert len(plan.steps) == 3

    def test_parse_no_json(self):
        """Raise PlannerJSONError when no JSON in output."""
        with pytest.raises(PlannerJSONError, match="No valid JSON"):
            parse_plan("This is not JSON at all")

    def test_parse_invalid_json(self):
        """Raise PlannerJSONError on malformed JSON."""
        with pytest.raises(PlannerJSONError):
            parse_plan("{this is not json}")

    def test_parse_empty_string(self):
        """Raise PlannerJSONError on empty string."""
        with pytest.raises(PlannerJSONError):
            parse_plan("")

    def test_parse_non_dict_root(self):
        """Raise PlannerSchemaError when root is a list."""
        with pytest.raises(PlannerSchemaError, match="Root value must be a dict"):
            parse_plan('[{"task_id": "x"}]')


# ═══════════════════════════════════════════════════════════════
# 3. Parser — Schema validation errors
# ═══════════════════════════════════════════════════════════════

class TestParserSchemaValidation:
    def test_missing_task_id(self):
        """Missing task_id field."""
        data = json.loads(_valid_plan_json())
        del data["task_id"]
        with pytest.raises(PlannerSchemaError, match="task_id"):
            parse_plan(json.dumps(data))

    def test_missing_steps(self):
        """Missing steps field."""
        data = json.loads(_valid_plan_json())
        del data["steps"]
        with pytest.raises(PlannerSchemaError, match="steps"):
            parse_plan(json.dumps(data))

    def test_empty_steps(self):
        """Zero steps raises PlannerEmptyPlanError."""
        data = json.loads(_valid_plan_json(steps_count=3))
        data["steps"] = []
        with pytest.raises(PlannerEmptyPlanError, match="zero steps"):
            parse_plan(json.dumps(data))

    def test_step_missing_order(self):
        """Step missing order field."""
        data = json.loads(_valid_plan_json(steps_count=1))
        del data["steps"][0]["order"]
        with pytest.raises(PlannerSchemaError, match="order"):
            parse_plan(json.dumps(data))

    def test_step_missing_teammate_id(self):
        """Step missing teammate_id field."""
        data = json.loads(_valid_plan_json(steps_count=1))
        del data["steps"][0]["teammate_id"]
        with pytest.raises(PlannerSchemaError, match="teammate_id"):
            parse_plan(json.dumps(data))

    def test_step_order_not_int(self):
        """Step order must be int."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["order"] = "one"
        with pytest.raises(PlannerSchemaError, match="'order' must be int"):
            parse_plan(json.dumps(data))

    def test_invalid_risk_level(self):
        """Invalid risk_level raises error."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["risk_level"] = "CRITICAL"
        with pytest.raises(PlannerSchemaError, match="risk_level"):
            parse_plan(json.dumps(data))

    def test_step_invalid_risk_level(self):
        """Invalid step risk_level raises error."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["risk_level"] = "EXTREME"
        with pytest.raises(PlannerSchemaError, match="risk_level"):
            parse_plan(json.dumps(data))

    def test_step_depends_on_not_list(self):
        """depends_on must be a list."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["depends_on"] = "not-a-list"
        with pytest.raises(PlannerSchemaError, match="depends_on"):
            parse_plan(json.dumps(data))

    def test_step_depends_on_non_int(self):
        """depends_on entries must be int."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["depends_on"] = ["a", "b"]
        with pytest.raises(PlannerSchemaError, match="depends_on"):
            parse_plan(json.dumps(data))


# ═══════════════════════════════════════════════════════════════
# 4. Parser — Order validation
# ═══════════════════════════════════════════════════════════════

class TestParserOrderValidation:
    def test_non_contiguous_order(self):
        """Gap in step order raises PlannerOrderError."""
        data = json.loads(_valid_plan_json(steps_count=3))
        data["steps"][1]["order"] = 3  # now orders are 1, 3, 3
        data["steps"][2]["order"] = 4  # 1, 3, 4
        with pytest.raises(PlannerOrderError, match="Non-contiguous"):
            parse_plan(json.dumps(data))

    def test_duplicate_order(self):
        """Duplicate order raises PlannerOrderError."""
        data = json.loads(_valid_plan_json(steps_count=3))
        data["steps"][1]["order"] = 1  # 1, 1, 3
        with pytest.raises(PlannerOrderError, match="Duplicate"):
            parse_plan(json.dumps(data))

    def test_order_not_starting_at_1(self):
        """Order must start at 1."""
        data = json.loads(_valid_plan_json(steps_count=3))
        data["steps"][0]["order"] = 2
        data["steps"][1]["order"] = 3
        data["steps"][2]["order"] = 4
        with pytest.raises(PlannerOrderError, match="must start at 1"):
            parse_plan(json.dumps(data))


# ═══════════════════════════════════════════════════════════════
# 5. Parser — Dependency validation
# ═══════════════════════════════════════════════════════════════

class TestParserDependencyValidation:
    def test_valid_dependencies(self):
        """Valid dependency chain passes."""
        data = json.loads(_valid_plan_json(steps_count=3))
        plan = parse_plan(json.dumps(data))
        assert plan.steps[1].depends_on == [1]
        assert plan.steps[2].depends_on == [2]  # default from helper

    def test_missing_dependency_ref(self):
        """Reference to non-existent order raises PlannerDependencyError."""
        data = json.loads(_valid_plan_json(steps_count=2))
        data["steps"][1]["depends_on"] = [99]
        with pytest.raises(PlannerDependencyError, match="non-existent"):
            parse_plan(json.dumps(data))

    def test_self_dependency(self):
        """Step depends on itself raises PlannerDependencyError."""
        data = json.loads(_valid_plan_json(steps_count=2))
        data["steps"][1]["depends_on"] = [2]  # step order 2 depends on 2
        with pytest.raises(PlannerDependencyError, match="depends on itself"):
            parse_plan(json.dumps(data))

    def test_circular_dependency_direct(self):
        """Two-step cycle raises PlannerDependencyError."""
        data = json.loads(_valid_plan_json(steps_count=2))
        data["steps"][0]["depends_on"] = [2]  # step 1 → 2
        data["steps"][1]["depends_on"] = [1]  # step 2 → 1 (cycle)
        with pytest.raises(PlannerDependencyError, match="Circular"):
            parse_plan(json.dumps(data))

    def test_circular_dependency_indirect(self):
        """Three-step cycle raises PlannerDependencyError."""
        data = json.loads(_valid_plan_json(steps_count=3))
        data["steps"][0]["depends_on"] = [2]  # 1 → 2
        data["steps"][1]["depends_on"] = [3]  # 2 → 3
        data["steps"][2]["depends_on"] = [1]  # 3 → 1 (cycle)
        with pytest.raises(PlannerDependencyError, match="Circular"):
            parse_plan(json.dumps(data))

    def test_no_dependencies(self):
        """All steps empty depends_on passes."""
        data = json.loads(_valid_plan_json(steps_count=3))
        for s in data["steps"]:
            s["depends_on"] = []
        plan = parse_plan(json.dumps(data))
        assert all(s.depends_on == [] for s in plan.steps)


# ═══════════════════════════════════════════════════════════════
# 6. Parser — Confidence field
# ═══════════════════════════════════════════════════════════════

class TestParserConfidence:
    def test_confidence_in_range(self):
        """Confidence between 0.0 and 1.0 passes."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["confidence"] = 0.5
        plan = parse_plan(json.dumps(data))
        assert plan.steps[0].confidence == 0.5

    def test_confidence_zero(self):
        """Confidence 0.0 is valid."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["confidence"] = 0.0
        plan = parse_plan(json.dumps(data))
        assert plan.steps[0].confidence == 0.0

    def test_confidence_one(self):
        """Confidence 1.0 is valid."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["confidence"] = 1.0
        plan = parse_plan(json.dumps(data))
        assert plan.steps[0].confidence == 1.0

    def test_confidence_negative(self):
        """Negative confidence raises error."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["confidence"] = -0.1
        with pytest.raises(PlannerSchemaError, match="out of range"):
            parse_plan(json.dumps(data))

    def test_confidence_over_one(self):
        """Confidence > 1.0 raises error."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["confidence"] = 1.5
        with pytest.raises(PlannerSchemaError, match="out of range"):
            parse_plan(json.dumps(data))

    def test_confidence_non_numeric(self):
        """Non-numeric confidence raises error."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["steps"][0]["confidence"] = "high"
        with pytest.raises(PlannerSchemaError, match="'confidence' must be numeric"):
            parse_plan(json.dumps(data))

    def test_plan_level_confidence(self):
        """Plan-level confidence works."""
        data = json.loads(_valid_plan_json(steps_count=1))
        data["confidence"] = 0.75
        plan = parse_plan(json.dumps(data))
        assert plan.confidence == 0.75


# ═══════════════════════════════════════════════════════════════
# Helper: Mock MAEOS for driver tests
# ═══════════════════════════════════════════════════════════════

class FakeMAEOSTask:
    """Mock MAEOS task result."""
    def __init__(self, task_id: str = "maeos-001", status: str = "COMPLETED",
                 result: str = "", error: str = ""):
        self.id = task_id
        self.task_id = task_id
        self.status = status
        self.result = result
        self.error = error


class FakeMAEOS:
    """Mock MAEOS for planner driver testing."""
    def __init__(self, result_text: str = "", fail: bool = False):
        self.result_text = result_text
        self.fail = fail
        self._started = True
        self.submitted_tasks: list[str] = []

    async def submit(self, description: str, priority: int = 2,
                     intent: str = "", wait: bool = False, **kwargs) -> str:
        task_id = f"maeos-{len(self.submitted_tasks) + 1:04d}"
        self.submitted_tasks.append(task_id)
        return task_id

    async def wait(self, task_id: str, timeout: float = 300.0):
        if self.fail:
            return FakeMAEOSTask(task_id, status="FAILED", error="Simulated failure")
        return FakeMAEOSTask(task_id, status="COMPLETED", result=self.result_text)


# ═══════════════════════════════════════════════════════════════
# 7. Driver — generate_plan with mock MAEOS
# ═══════════════════════════════════════════════════════════════

class TestDriverGeneratePlan:
    """All tests in this class are async — mock MAEOS usage."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Successful plan generation returns parsed TaskPlan."""
        maeos = FakeMAEOS(result_text=_valid_plan_json(task_id="task-001"))
        plan = await generate_plan(maeos, goal="Build auth system", task_id="task-001")
        assert isinstance(plan, TaskPlan)
        assert plan.task_id == "task-001"
        assert len(plan.steps) == 3
        assert plan.steps[0].confidence == 0.9

    @pytest.mark.asyncio
    async def test_retry_on_parse_failure(self):
        """Retries on invalid JSON, eventually succeeds."""
        maeos = FakeMAEOS(result_text=_valid_plan_json())
        plan = await generate_plan(maeos, goal="Build auth")
        assert isinstance(plan, TaskPlan)

    @pytest.mark.asyncio
    async def test_failure_after_all_retries(self):
        """Raises PlanningError after exhausting retries."""
        maeos = FakeMAEOS(result_text="not valid json at all")
        with pytest.raises(PlanningError, match="failed after"):
            await generate_plan(maeos, goal="Build auth")

    @pytest.mark.asyncio
    async def test_maeos_task_failure(self):
        """Raises PlanningError when MAEOS task fails."""
        maeos = FakeMAEOS(fail=True)
        with pytest.raises(PlanningError, match="failed"):
            await generate_plan(maeos, goal="Build auth")

    @pytest.mark.asyncio
    async def test_with_context(self):
        """Context gets included in the prompt."""
        maeos = FakeMAEOS(result_text=_valid_plan_json())
        plan = await generate_plan(
            maeos,
            goal="Build auth",
            context={"global_rules": ["Use async/await"]},
        )
        assert isinstance(plan, TaskPlan)

    @pytest.mark.asyncio
    async def test_task_id_override(self):
        """task_id from parameter overrides parsed one."""
        maeos = FakeMAEOS(result_text=_valid_plan_json(task_id="parsed-id"))
        plan = await generate_plan(maeos, goal="Build auth", task_id="actual-id")
        assert plan.task_id == "actual-id"


# ═══════════════════════════════════════════════════════════════
# 8. Driver — validate_plan warnings
# ═══════════════════════════════════════════════════════════════

class TestDriverValidatePlan:
    def test_no_warnings_valid_plan(self):
        """A well-formed plan produces no warnings."""
        steps = [
            TaskStepProposal(order=1, teammate_id="teammate_a", objective="A",
                             confidence=0.9),
            TaskStepProposal(order=2, teammate_id="teammate_b", objective="B",
                             confidence=0.8),
        ]
        plan = TaskPlan(
            task_id="t1", title="T", description="D",
            steps=steps, confidence=0.85, risk_level="LOW",
        )
        warnings = validate_plan(plan)
        assert warnings == []

    def test_warning_low_confidence(self):
        """Plan with low confidence produces warning."""
        steps = [
            TaskStepProposal(order=1, teammate_id="teammate_a", objective="A",
                             confidence=0.9),
        ]
        plan = TaskPlan(
            task_id="t1", title="T", description="D",
            steps=steps, confidence=0.2,  # low!
        )
        warnings = validate_plan(plan)
        assert any("Low planner confidence" in w for w in warnings)

    def test_warning_low_confidence_step(self):
        """Steps with low confidence produce warning."""
        steps = [
            TaskStepProposal(order=1, teammate_id="teammate_a", objective="A",
                             confidence=0.1),
            TaskStepProposal(order=2, teammate_id="teammate_b", objective="B",
                             confidence=0.9),
        ]
        plan = TaskPlan(
            task_id="t1", title="T", description="D",
            steps=steps, confidence=0.85,
        )
        warnings = validate_plan(plan)
        assert any("Low-confidence steps" in w for w in warnings)

    def test_warning_many_steps(self):
        """Plan with > 20 steps produces warning."""
        steps = [
            TaskStepProposal(order=i, teammate_id="teammate_a", objective=f"S{i}",
                             confidence=0.9)
            for i in range(1, 22)
        ]
        plan = TaskPlan(
            task_id="t1", title="T", description="D",
            steps=steps, confidence=0.85,
        )
        warnings = validate_plan(plan)
        assert any("consider splitting" in w for w in warnings)

    def test_warning_negative_cost(self):
        """Negative cost produces warning."""
        steps = [
            TaskStepProposal(order=1, teammate_id="teammate_a", objective="A",
                             confidence=0.9),
        ]
        plan = TaskPlan(
            task_id="t1", title="T", description="D",
            steps=steps, confidence=0.85,
            estimated_total_cost=-1.0,
        )
        warnings = validate_plan(plan)
        assert any("Negative" in w for w in warnings)
