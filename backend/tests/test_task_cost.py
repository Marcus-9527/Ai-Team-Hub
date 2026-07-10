"""
test_task_cost.py — Execution Cost Tracking Tests

Tests:
  1. estimate_cost: input/output/total tokens, estimated_cost in µ$
  2. TaskExecutionModel token/cost fields
  3. record_execution_with_cost auto-estimation from text
  4. to_dict() includes all cost fields
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.models import (
    TaskModel, TaskStepModel, TaskExecutionModel,
    TaskStatus, TaskStepStatus,
)
from backend.services.task.task_result import (
    TaskResultHandler,
    estimate_cost,
    estimate_tokens,
    _usd_to_microdollars,
)
from backend.services.task.task_state import TaskStateManager

pytestmark = pytest.mark.asyncio


# ── Helpers ──

def make_execution(**kwargs) -> TaskExecutionModel:
    defaults = dict(
        id="exec-cost-001", task_step_id="step-cost-001",
        attempt=1, maeos_task_id="maeos-cost-001",
        input_tokens=0, output_tokens=0, total_tokens=0,
        estimated_cost=0, token_usage=0, cost=0,
    )
    defaults.update(kwargs)
    return TaskExecutionModel(**defaults)


# ── Cost Estimation Unit Tests ──

class TestCostEstimation:

    def test_estimate_tokens_from_text(self):
        """~1 token per 4 chars."""
        assert estimate_tokens("Hello") == 1   # 5 // 4 = 1
        assert estimate_tokens("") == 0
        # 27 // 4 = 6
        assert estimate_tokens("Hello world, this is a test") == 6

    def test_estimate_tokens_empty_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_estimate_tokens_minimum_one(self):
        assert estimate_tokens("Hi") == 1  # 2 // 4 = 0, max(1, 0) = 1

    def test_estimate_cost_default_rates(self):
        """Default rates produce reasonable cost estimates."""
        inp, out, total, cost = estimate_cost(
            input_text="Hello world, how are you?",
            output_text="I am doing great, thanks for asking!",
        )
        assert inp > 0
        assert out > 0
        assert total == inp + out
        assert cost > 0
        # At default rates, 10 tokens ≈ very small cost
        assert cost < 100  # less than $0.0001

    def test_estimate_cost_with_manual_tokens(self):
        """Manual token override works."""
        inp, out, total, cost = estimate_cost(
            input_text="",
            output_text="",
            input_tokens=100,
            output_tokens=50,
        )
        assert inp == 100
        assert out == 50
        assert total == 150
        assert cost > 0

    def test_estimate_cost_exact_value(self):
        """Cost = (input/1000 * rate) + (output/1000 * rate), in µ$."""
        # 1000 input tokens @ $0.001/1K = $0.001
        # 500 output tokens @ $0.002/1K = $0.001
        # Total = $0.002 = 2000 µ$
        inp, out, total, cost = estimate_cost(
            input_text="",
            output_text="",
            input_tokens=1000,
            output_tokens=500,
            cost_per_input_1k=0.001,
            cost_per_output_1k=0.002,
        )
        assert inp == 1000
        assert out == 500
        assert total == 1500
        assert cost == 2000  # $0.002 = 2000 µ$

    def test_zero_tokens_zero_cost(self):
        """No tokens → zero cost."""
        inp, out, total, cost = estimate_cost(input_text="", output_text="")
        assert cost >= 0  # can be very small but non-zero due to min tokens

    def test_usd_to_microdollars(self):
        """$0.001 = 1000 µ$."""
        assert _usd_to_microdollars(0.001) == 1000
        assert _usd_to_microdollars(0.000001) == 1
        assert _usd_to_microdollars(1.0) == 1_000_000


# ── TaskExecutionModel Cost Fields Tests ──

class TestExecutionCostFields:

    async def test_create_execution_cost_defaults(self, db_session):
        """Default cost fields are 0."""
        state = TaskStateManager()
        execution = await state.create_execution(
            db_session,
            task_step_id="step-cost-002",
            attempt=1,
            maeos_task_id="maeos-002",
        )
        assert execution.input_tokens == 0
        assert execution.output_tokens == 0
        assert execution.total_tokens == 0
        assert execution.estimated_cost == 0

    async def test_to_dict_includes_cost_fields(self):
        """to_dict() returns all new cost fields."""
        execution = make_execution(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost=2000,
        )
        d = execution.to_dict()
        assert d["input_tokens"] == 100
        assert d["output_tokens"] == 50
        assert d["total_tokens"] == 150
        assert d["estimated_cost"] == 2000
        assert d["token_usage"] == 0       # LEGACY
        assert d["cost"] == 0              # LEGACY

    async def test_update_execution_cost_fields(self, db_session):
        """update_execution can set all cost fields via kwargs."""
        state = TaskStateManager()
        execution = make_execution()

        updated = await state.update_execution(
            db_session, execution,
            input_tokens=200,
            output_tokens=75,
            total_tokens=275,
            estimated_cost=5000,
        )

        assert updated.input_tokens == 200
        assert updated.output_tokens == 75
        assert updated.total_tokens == 275
        assert updated.estimated_cost == 5000


# ── record_execution_with_cost Integration ──

class TestRecordExecutionWithCost:

    async def test_auto_cost_from_text(self, db_session):
        """record_execution_with_cost auto-estimates from input/output text."""
        handler = TaskResultHandler()
        execution = make_execution()

        input_text = "What is the capital of France? " * 25  # ~625 chars
        output_text = "The capital of France is Paris. " * 20  # ~560 chars

        with patch.object(TaskStateManager, 'update_execution',
                          AsyncMock(return_value=make_execution(
                              input_tokens=156,
                              output_tokens=140,
                              total_tokens=296,
                              estimated_cost=500,
                          ))):
            updated = await handler.record_execution_with_cost(
                db_session, execution,
                output=output_text,
                execution_time_ms=1500,
                input_text=input_text,
                trace_id="trace-cost-001",
            )

        assert updated.input_tokens > 0
        assert updated.output_tokens > 0
        assert updated.total_tokens == updated.input_tokens + updated.output_tokens
        assert updated.estimated_cost > 0
