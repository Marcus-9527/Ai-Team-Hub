"""Phase 17: OrganizationPlan Runtime — tests."""

import pytest
from unittest.mock import AsyncMock

from backend.services.organization.actions import OrganizationAction
from backend.services.organization.plan import OrganizationPlan, PlanStep
from backend.services.organization.plan_runtime import (
    OrganizationPlanRuntime,
    PlanStepState,
)

pytestmark = pytest.mark.asyncio


# ── Fixtures ──

@pytest.fixture
def mock_hooks():
    h = AsyncMock()
    h.emit_event = AsyncMock()
    return h


@pytest.fixture
def dev_plan():
    return OrganizationPlan(
        goal="Build auth",
        steps=[
            PlanStep("plan", OrganizationAction.PLAN, "planner", "plan", 0.85),
            PlanStep("execute", OrganizationAction.EXECUTE, "developer", "do it", 0.80),
            PlanStep("review", OrganizationAction.REVIEW, "reviewer", "check", 0.75),
        ],
        reasoning="Dev task",
    )


@pytest.fixture
def chat_plan():
    return OrganizationPlan(
        goal="Hello",
        steps=[
            PlanStep("respond", OrganizationAction.RESPOND, "communicator", "say hi", 0.80),
        ],
        reasoning="Chat",
    )


# ── PlanStepState ──

class TestPlanStepState:

    def test_default_status_pending(self):
        step = PlanStep("x", OrganizationAction.RESPOND, "r", "why", 0.5)
        s = PlanStepState(step)
        assert s.status == "pending"
        assert s.error is None


# ── create ──

class TestCreate:

    def test_create_stores_plan(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        assert r.plan is dev_plan
        assert r.status == "pending"

    def test_create_populates_step_states(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        assert len(r.steps) == 3
        assert all(s.status == "pending" for s in r.steps)
        assert all(s.error is None for s in r.steps)

    def test_create_single_step(self, mock_hooks, chat_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(chat_plan)
        assert len(r.steps) == 1
        assert r.steps[0].step.step_type == "respond"


# ── step transitions ──

class TestStepLifecycle:

    async def test_start_step_transitions_and_emits(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0)
        assert r.steps[0].status == "running"
        assert r.status == "running"
        mock_hooks.emit_event.assert_awaited_once()
        args = mock_hooks.emit_event.await_args
        assert args.kwargs["event_type"] == "plan.step.started"
        assert args.kwargs["payload"]["step_index"] == 0

    async def test_complete_step_transitions_and_emits(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0)
        mock_hooks.emit_event.reset_mock()
        await r.complete_step(0)
        assert r.steps[0].status == "completed"
        mock_hooks.emit_event.assert_awaited_once()
        args = mock_hooks.emit_event.await_args
        assert args.kwargs["event_type"] == "plan.step.completed"
        assert args.kwargs["payload"]["step_index"] == 0

    async def test_fail_step_transitions_and_emits(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0)
        mock_hooks.emit_event.reset_mock()
        await r.fail_step(0, "Something broke")
        assert r.steps[0].status == "failed"
        assert r.steps[0].error == "Something broke"
        mock_hooks.emit_event.assert_awaited_once()
        args = mock_hooks.emit_event.await_args
        assert args.kwargs["event_type"] == "plan.step.failed"
        assert args.kwargs["payload"]["error"] == "Something broke"

    async def test_full_lifecycle(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        assert r.status == "pending"
        await r.start_step(0)
        assert r.status == "running"
        await r.complete_step(0)
        assert r.status == "running"  # still other steps pending
        await r.start_step(1)
        await r.complete_step(1)
        await r.start_step(2)
        await r.complete_step(2)
        assert r.status == "completed"

    async def test_any_step_failed_aggregates_failed(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0)
        await r.fail_step(0, "Boom")
        assert r.status == "failed"


# ── event payloads ──

class TestEventPayloads:

    async def test_started_payload_shape(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(1)
        p = mock_hooks.emit_event.await_args.kwargs["payload"]
        assert p["step_index"] == 1
        assert p["step_type"] == "execute"
        assert p["action"] == "execute"
        assert p["role"] == "developer"

    async def test_completed_payload_shape(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0)
        mock_hooks.emit_event.reset_mock()
        await r.complete_step(0)
        p = mock_hooks.emit_event.await_args.kwargs["payload"]
        assert p["step_index"] == 0
        assert p["step_type"] == "plan"
        assert p["action"] == "plan"

    async def test_failed_payload_shape(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(2)
        mock_hooks.emit_event.reset_mock()
        await r.fail_step(2, "Timeout")
        p = mock_hooks.emit_event.await_args.kwargs["payload"]
        assert p["step_index"] == 2
        assert p["error"] == "Timeout"


# ── status aggregation ──

class TestStatusAggregation:

    def test_no_plan_is_pending(self, mock_hooks):
        r = OrganizationPlanRuntime(mock_hooks)
        assert r.status == "pending"

    def test_all_completed_is_completed(self, mock_hooks, chat_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(chat_plan)
        # Only one step — we'd need async to complete it
        # Test the aggregate state property directly
        r._steps[0].status = "completed"
        assert r.status == "completed"

    def test_no_steps_after_create(self, mock_hooks):
        """Empty plan → pending."""
        r = OrganizationPlanRuntime(mock_hooks)
        plan = OrganizationPlan(goal="x", steps=[])
        r.create(plan)
        assert r.status == "pending"


# ── error handling ──

class TestErrorHandling:

    def test_start_without_create_raises(self, mock_hooks):
        r = OrganizationPlanRuntime(mock_hooks)
        with pytest.raises(RuntimeError, match="No plan created"):
            r._resolve(0)

    def test_bad_step_index_raises(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        with pytest.raises(IndexError):
            r._resolve(99)

    async def test_fail_preserves_error_text(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0)
        await r.fail_step(0, "Connection lost: timeout after 30s")
        assert "Connection lost" in r.steps[0].error


# ── trigger_id passthrough ──

class TestTriggerId:

    async def test_trigger_id_passed_to_event(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0, trigger_id="tr-42")
        assert mock_hooks.emit_event.await_args.args[0] == "tr-42"

    async def test_empty_trigger_id_default(self, mock_hooks, dev_plan):
        r = OrganizationPlanRuntime(mock_hooks)
        r.create(dev_plan)
        await r.start_step(0)
        assert mock_hooks.emit_event.await_args.args[0] == ""
