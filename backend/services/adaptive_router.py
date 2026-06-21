"""
adaptive_router.py — Adaptive Execution Mode Router

Routes tasks to the appropriate execution pipeline based on complexity:

  SIMPLE   → Single executor agent, no planner, no reviewer
  STANDARD → Executor + validation gate only
  COMPLEX  → Full FSM pipeline (planner → executor → reviewer)

Also implements cost/latency optimization:
  - Minimize LLM calls for SIMPLE/STANDARD
  - Skip unnecessary agent hops
  - Fast-path for trivial queries
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

from backend.services.complexity_classifier import (
    classify_task,
    Classification,
    Complexity,
)
from backend.services.agent_functions import (
    planner_fn,
    executor_fn,
    reviewer_fn,
    AgentOutput,
)
from backend.services.validation_gate import validate_output, ValidationResult
from backend.services.runtime import (
    Scheduler,
    RetryPolicy,
    TraceLogger,
    ContextIsolation,
    FlowControlEnforcer,
    BackoffStrategy,
)

logger = logging.getLogger("adaptive_router")


class ExecutionMode(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


@dataclass
class ExecutionMetrics:
    """Track cost/latency metrics for each execution."""
    mode: str = ""
    llm_calls: int = 0
    agents_used: list[str] = field(default_factory=list)
    total_latency_ms: int = 0
    validation_gates_passed: int = 0
    validation_gates_failed: int = 0
    skipped_stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "llm_calls": self.llm_calls,
            "agents_used": self.agents_used,
            "total_latency_ms": self.total_latency_ms,
            "validation_gates_passed": self.validation_gates_passed,
            "validation_gates_failed": self.validation_gates_failed,
            "skipped_stages": self.skipped_stages,
        }


@dataclass
class AdaptiveResult:
    """Result from adaptive execution pipeline."""
    task_id: str
    mode: ExecutionMode
    classification: Classification
    final_result: str
    execution_result: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    review_result: dict = field(default_factory=dict)
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "mode": self.mode.value,
            "classification": self.classification.to_dict(),
            "final_result": self.final_result,
            "execution_result": self.execution_result,
            "plan": self.plan,
            "review_result": self.review_result,
            "metrics": self.metrics.to_dict(),
            "error": self.error,
        }


# ── Adaptive Execution Router ──

class AdaptiveRouter:
    """
    Routes tasks to the right execution pipeline based on complexity.

    Cost optimization:
      SIMPLE:   1 LLM call (executor only)
      STANDARD: 1-2 LLM calls (executor + optional validation)
      COMPLEX:  3+ LLM calls (planner + executor + reviewer)
    """

    def __init__(
        self,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        api_key: str = "",
        base_url: str = None,
        max_retries: int = 3,
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_retries = max_retries

        # Runtime subsystems
        self.scheduler = Scheduler(max_concurrency=1)
        self.retry_policy = RetryPolicy(
            max_retries=max_retries,
            backoff_strategy=BackoffStrategy.LINEAR,
            base_delay_ms=1000,
        )
        self.context_isolation = ContextIsolation()
        self.flow_control = FlowControlEnforcer(mode="strict")

    async def execute(self, task: str, task_id: str = None) -> AdaptiveResult:
        """
        Main entry: classify → route → execute.

        Flow:
          Task → Complexity Classifier → Mode Router → Execution Pipeline
        """
        import uuid
        task_id = task_id or str(uuid.uuid4())[:12]
        metrics = ExecutionMetrics()
        start_time = time.monotonic()

        # ── Step 1: Classify complexity ──
        classification = classify_task(task)
        mode = self._route_mode(classification)
        metrics.mode = mode.value

        logger.info(
            f"[{task_id}] Classification: {classification.level.value} "
            f"(confidence={classification.confidence}) → Mode: {mode.value}"
        )

        # ── Step 2: Execute based on mode ──
        if mode == ExecutionMode.SIMPLE:
            result = await self._execute_simple(task, task_id, metrics)
        elif mode == ExecutionMode.STANDARD:
            result = await self._execute_standard(task, task_id, metrics)
        else:  # COMPLEX
            result = await self._execute_complex(task, task_id, metrics)

        # ── Step 3: Build result ──
        metrics.total_latency_ms = int((time.monotonic() - start_time) * 1000)

        return AdaptiveResult(
            task_id=task_id,
            mode=mode,
            classification=classification,
            final_result=result.get("result", ""),
            execution_result=result.get("execution_result", {}),
            plan=result.get("plan", {}),
            review_result=result.get("review_result", {}),
            metrics=metrics,
            error=result.get("error", ""),
        )

    # ── Mode Router ──

    def _route_mode(self, classification: Classification) -> ExecutionMode:
        """Map complexity classification to execution mode."""
        level = classification.level
        if level == Complexity.SIMPLE:
            return ExecutionMode.SIMPLE
        elif level == Complexity.STANDARD:
            return ExecutionMode.STANDARD
        else:
            return ExecutionMode.COMPLEX

    # ── SIMPLE Mode: Executor only ──

    async def _execute_simple(
        self, task: str, task_id: str, metrics: ExecutionMetrics
    ) -> dict:
        """
        SINGLE AGENT: executor only.
        No planner, no reviewer, no validation gate.
        Minimizes LLM calls (1 call total).
        """
        logger.info(f"[{task_id}] SIMPLE mode: executor only")
        metrics.skipped_stages = ["planner", "reviewer", "validation_gate"]
        metrics.agents_used = ["executor"]

        # Direct executor call — no plan needed
        output = await self._call_executor(
            plan={"task": task, "mode": "simple"},
            original_task=task,
        )
        metrics.llm_calls += 1

        if output.status == "error":
            return {"error": output.reasoning or "Executor failed", "result": ""}

        return {
            "result": output.result,
            "execution_result": {"result": output.result, "reasoning": output.reasoning},
        }

    # ── STANDARD Mode: Executor + Validation Gate ──

    async def _execute_standard(
        self, task: str, task_id: str, metrics: ExecutionMetrics
    ) -> dict:
        """
        EXECUTOR + VALIDATION: run executor, then validate output.
        No planner, no reviewer.
        Cost: 1 LLM call + 1 validation (no LLM).
        """
        logger.info(f"[{task_id}] STANDARD mode: executor + validation gate")
        metrics.skipped_stages = ["planner", "reviewer"]
        metrics.agents_used = ["executor"]

        # Execute
        output = await self._call_executor(
            plan={"task": task, "mode": "standard"},
            original_task=task,
        )
        metrics.llm_calls += 1

        if output.status == "error":
            return {"error": output.reasoning or "Executor failed", "result": ""}

        # Validation gate (deterministic, no LLM call)
        validation = validate_output(output, "executor")
        if validation.is_valid:
            metrics.validation_gates_passed += 1
        else:
            metrics.validation_gates_failed += 1
            logger.warning(f"[{task_id}] Validation failed: {validation.reason}")
            # In STANDARD mode, we still accept the result but log the issue

        return {
            "result": output.result,
            "execution_result": {"result": output.result, "reasoning": output.reasoning},
        }

    # ── COMPLEX Mode: Full FSM Pipeline ──

    async def _execute_complex(
        self, task: str, task_id: str, metrics: ExecutionMetrics
    ) -> dict:
        """
        FULL FSM PIPELINE: planner → executor → reviewer.
        Cost: 3+ LLM calls.
        Only used when complexity requires multi-step planning + validation.
        """
        logger.info(f"[{task_id}] COMPLEX mode: planner → executor → reviewer")
        metrics.agents_used = ["planner", "executor", "reviewer"]

        # ── Plan ──
        plan_output = await self._call_planner(task)
        metrics.llm_calls += 1

        if plan_output.status == "error":
            return {"error": f"Planner failed: {plan_output.reasoning}"}

        plan = {"result": plan_output.result, "reasoning": plan_output.reasoning}

        # Validate plan
        plan_validation = validate_output(plan_output, "planner")
        if not plan_validation.is_valid:
            metrics.validation_gates_failed += 1
            logger.warning(f"[{task_id}] Plan validation failed: {plan_validation.reason}")
        else:
            metrics.validation_gates_passed += 1

        # ── Execute ──
        exec_output = await self._call_executor(
            plan=plan,
            original_task=task,
        )
        metrics.llm_calls += 1

        if exec_output.status == "error":
            return {
                "error": f"Executor failed: {exec_output.reasoning}",
                "plan": plan,
            }

        # Validate execution
        exec_validation = validate_output(exec_output, "executor")
        if exec_validation.is_valid:
            metrics.validation_gates_passed += 1
        else:
            metrics.validation_gates_failed += 1

        # ── Review ──
        review_output = await self._call_reviewer(
            result=exec_output.result,
            original_task=task,
        )
        metrics.llm_calls += 1

        review_passed = _parse_review_pass(review_output.result)
        metrics.validation_gates_passed += 1 if review_passed else 0
        metrics.validation_gates_failed += 0 if review_passed else 1

        return {
            "result": exec_output.result,
            "plan": plan,
            "execution_result": {
                "result": exec_output.result,
                "reasoning": exec_output.reasoning,
            },
            "review_result": {
                "result": review_output.result,
                "reasoning": review_output.reasoning,
                "pass": review_passed,
            },
        }

    # ── Agent Call Helpers (with scheduler + retry) ──

    async def _call_planner(self, task: str) -> AgentOutput:
        """Call planner through scheduler with retry."""
        isolated = self.context_isolation.isolate(
            agent_id="planner",
            state="PLAN",
            global_context={"task": task},
        )
        unit = self.scheduler.submit(
            fn=planner_fn,
            agent_id="planner",
            state="PLAN",
            kwargs={
                "task": isolated.get("task", task),
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        if unit.status != "SUCCESS" or unit.result is None:
            return AgentOutput(
                status="error",
                result="",
                reasoning=f"Planner execution failed: {unit.error}",
            )
        return unit.result

    async def _call_executor(self, plan: dict, original_task: str) -> AgentOutput:
        """Call executor through scheduler with retry."""
        isolated = self.context_isolation.isolate(
            agent_id="executor",
            state="EXECUTE",
            global_context={"plan": plan, "original_task": original_task},
        )
        unit = self.scheduler.submit(
            fn=executor_fn,
            agent_id="executor",
            state="EXECUTE",
            kwargs={
                "plan": isolated.get("plan", plan),
                "original_task": isolated.get("original_task", original_task),
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        if unit.status != "SUCCESS" or unit.result is None:
            return AgentOutput(
                status="error",
                result="",
                reasoning=f"Executor execution failed: {unit.error}",
            )
        return unit.result

    async def _call_reviewer(self, result: str, original_task: str) -> AgentOutput:
        """Call reviewer through scheduler with retry."""
        isolated = self.context_isolation.isolate(
            agent_id="reviewer",
            state="REVIEW",
            global_context={"result": result, "original_task": original_task},
        )
        unit = self.scheduler.submit(
            fn=reviewer_fn,
            agent_id="reviewer",
            state="REVIEW",
            kwargs={
                "result": isolated.get("result", result),
                "original_task": isolated.get("original_task", original_task),
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        if unit.status != "SUCCESS" or unit.result is None:
            return AgentOutput(
                status="error",
                result="",
                reasoning=f"Reviewer execution failed: {unit.error}",
            )
        return unit.result


def _parse_review_pass(raw: str) -> bool:
    """Parse review agent output to determine pass/fail."""
    import json
    text = raw.lower()
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            if "pass" in data:
                return bool(data["pass"])
            if "passed" in data:
                return bool(data["passed"])
    except (json.JSONDecodeError, Exception):
        pass
    fail_keywords = ["fail", "不通过", "失败", "reject", "rejected"]
    return not any(kw in text for kw in fail_keywords)
