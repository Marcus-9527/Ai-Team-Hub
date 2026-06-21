"""
orchestrator_fsm.py — Production FSM Execution Orchestrator (v5 — Adaptive)

Architecture:
  Task → Complexity Classifier → Mode Router → Execution Pipeline
              ↓                        ↓
         SIMPLE/STANDARD/COMPLEX   Agent selection

Key change from v4:
  - Adaptive orchestration: classifier decides execution mode
  - SIMPLE: executor only (1 LLM call)
  - STANDARD: executor + validation gate (1 LLM call)
  - COMPLEX: planner → executor → reviewer (3 LLM calls)
  - Default is NOT full FSM — only COMPLEX tasks use it
  - Cost/latency optimization built into mode selection

Architecture:
  Orchestrator → Scheduler → Agent Functions
                     ↑
              RetryPolicy (failure classification + backoff)
              TraceLogger (structured JSON observability)
              ContextIsolation (anti-leak)
              FlowControlEnforcer (hard rules)
              ComplexityClassifier (zero-LLM-call heuristic)
              AdaptiveRouter (mode-based agent selection)
"""

import json
import time
import uuid
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

from backend.services.agent_functions import (
    planner_fn,
    executor_fn,
    reviewer_fn,
    AgentOutput,
)
from backend.services.validation_gate import validate_output, ValidationResult
from backend.services.complexity_classifier import classify_task, Complexity
from backend.services.adaptive_router import AdaptiveRouter, ExecutionMode
from backend.services.runtime import (
    Scheduler,
    RetryPolicy,
    TraceLogger,
    ContextIsolation,
    FlowControlEnforcer,
    FailureType,
    BackoffStrategy,
)

logger = logging.getLogger("orchestrator_fsm")


# ── State Definitions ──

class FSMState(str, Enum):
    INIT = "INIT"
    CLASSIFY = "CLASSIFY"       # v5: complexity classification
    SIMPLE_EXEC = "SIMPLE_EXEC" # v5: simple mode — executor only
    STD_EXEC = "STD_EXEC"       # v5: standard mode — executor + validation
    PLAN = "PLAN"               # v5: complex mode only
    EXECUTE = "EXECUTE"
    REVIEW = "REVIEW"
    DONE = "DONE"
    FAIL_RETRY = "FAIL_RETRY"


# ── Transition Table (deterministic, adaptive) ──

TRANSITIONS: dict[FSMState, list[FSMState]] = {
    FSMState.INIT:        [FSMState.CLASSIFY],
    FSMState.CLASSIFY:    [FSMState.SIMPLE_EXEC, FSMState.STD_EXEC, FSMState.PLAN, FSMState.FAIL_RETRY],
    FSMState.SIMPLE_EXEC: [FSMState.DONE, FSMState.FAIL_RETRY],
    FSMState.STD_EXEC:    [FSMState.DONE, FSMState.FAIL_RETRY],
    FSMState.PLAN:        [FSMState.EXECUTE, FSMState.FAIL_RETRY],
    FSMState.EXECUTE:     [FSMState.REVIEW, FSMState.FAIL_RETRY],
    FSMState.REVIEW:      [FSMState.DONE, FSMState.EXECUTE],
    FSMState.FAIL_RETRY:  [FSMState.SIMPLE_EXEC, FSMState.STD_EXEC, FSMState.EXECUTE, FSMState.DONE],
    FSMState.DONE:        [],
}


# ── Context (serializable) ──

@dataclass
class FSMContext:
    task_id: str
    user_input: str
    intent: str = ""
    complexity: str = ""       # v5: SIMPLE/STANDARD/COMPLEX
    execution_mode: str = ""   # v5: adaptive mode
    state: str = "INIT"
    plan: dict = field(default_factory=dict)
    execution_result: dict = field(default_factory=dict)
    review_result: dict = field(default_factory=dict)
    final_result: str = ""
    error: str = ""
    retry_count: int = 0
    max_retries: int = 3
    llm_calls: int = 0         # v5: cost tracking
    skipped_stages: list = field(default_factory=list)  # v5
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "user_input": self.user_input,
            "intent": self.intent,
            "complexity": self.complexity,
            "execution_mode": self.execution_mode,
            "state": self.state,
            "plan": self.plan,
            "execution_result": self.execution_result,
            "review_result": self.review_result,
            "final_result": self.final_result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "llm_calls": self.llm_calls,
            "skipped_stages": self.skipped_stages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ── FSM Orchestrator (Production v4) ──

class FSMOrchestrator:
    """
    Production FSM orchestrator — all execution through Scheduler.

    Usage:
        orch = FSMOrchestrator(provider="deepseek", model="deepseek-chat", api_key="...")
        ctx = await orch.run("your task here")
    """

    def __init__(
        self,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        api_key: str = "",
        base_url: str = None,
        max_retries: int = 3,
        max_concurrency: int = 1,
        backoff_strategy: str = BackoffStrategy.LINEAR,
        base_delay_ms: int = 1000,
        flow_control_mode: str = "strict",
        adaptive: bool = True,        # v5: enable adaptive orchestration
        force_mode: str = None,       # v5: force specific mode (SIMPLE/STANDARD/COMPLEX)
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_retries = max_retries
        self.adaptive = adaptive
        self.force_mode = force_mode

        # ── Runtime subsystems ──
        self.scheduler = Scheduler(max_concurrency=max_concurrency)
        self.retry_policy = RetryPolicy(
            max_retries=max_retries,
            backoff_strategy=backoff_strategy,
            base_delay_ms=base_delay_ms,
        )
        self.context_isolation = ContextIsolation()
        self.flow_control = FlowControlEnforcer(mode=flow_control_mode)

        # ── v5: Adaptive subsystems ──
        if adaptive:
            self.adaptive_router = AdaptiveRouter(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                max_retries=max_retries,
            )

        # ── State ──
        self.state = FSMState.INIT
        self.context: Optional[FSMContext] = None
        self.trace: Optional[TraceLogger] = None
        self.trace_id = str(uuid.uuid4())[:12]

    # ── State Transition (orchestrator-only) ──

    def _transition(self, new_state: FSMState, reason: str = "") -> None:
        allowed = TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self.state.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        old = self.state
        self.state = new_state
        if self.context:
            self.context.state = new_state.value
            self.context.updated_at = time.time()
        if self.trace:
            self.trace.log_state_transition(old.value, new_state.value, reason)
        logger.info(f"FSM: {old.value} → {new_state.value} ({reason})")

    # ── Main Entry ──

    async def run(self, task: str, intent: str = None) -> FSMContext:
        """
        Execute task through adaptive FSM.

        v5 Flow: INIT → CLASSIFY → Mode Router → Execution Pipeline → DONE

        Mode Router decides:
          SIMPLE   → SIMPLE_EXEC → DONE (executor only)
          STANDARD → STD_EXEC → DONE (executor + validation)
          COMPLEX  → PLAN → EXECUTE → REVIEW → DONE
        """
        self.context = FSMContext(
            task_id=str(uuid.uuid4())[:12],
            user_input=task,
            intent=intent or _classify_intent(task),
            max_retries=self.max_retries,
        )
        self.trace = TraceLogger(trace_id=self.trace_id, task_id=self.context.task_id)
        self.trace.log_state_transition("", FSMState.INIT.value, "workflow start")

        # FSM main loop
        while self.state != FSMState.DONE:
            if self.state == FSMState.INIT:
                self._transition(FSMState.CLASSIFY, "start classification")

            elif self.state == FSMState.CLASSIFY:
                await self._step_classify()

            elif self.state == FSMState.SIMPLE_EXEC:
                await self._step_simple_exec()

            elif self.state == FSMState.STD_EXEC:
                await self._step_std_exec()

            elif self.state == FSMState.PLAN:
                ok = await self._step_plan()
                if ok:
                    self._transition(FSMState.EXECUTE, "plan valid")
                else:
                    self._transition(FSMState.FAIL_RETRY, "plan failed")

            elif self.state == FSMState.EXECUTE:
                ok = await self._step_execute()
                if ok:
                    self._transition(FSMState.REVIEW, "execution valid")
                else:
                    self._transition(FSMState.FAIL_RETRY, "execution failed")

            elif self.state == FSMState.REVIEW:
                ok = await self._step_review()
                if ok:
                    self._transition(FSMState.DONE, "review passed")
                else:
                    if self.context.retry_count < self.max_retries:
                        self.context.retry_count += 1
                        self._transition(FSMState.EXECUTE, f"review failed, retry {self.context.retry_count}")
                    else:
                        logger.warning("Max review retries reached, accepting result")
                        self._transition(FSMState.DONE, "max retries exhausted, accepting")

            elif self.state == FSMState.FAIL_RETRY:
                if self.context.retry_count < self.max_retries:
                    self.context.retry_count += 1
                    # Retry at the appropriate level based on mode
                    mode = self.context.execution_mode
                    if mode == "SIMPLE":
                        self._transition(FSMState.SIMPLE_EXEC, f"fail retry {self.context.retry_count}/{self.max_retries}")
                    elif mode == "STANDARD":
                        self._transition(FSMState.STD_EXEC, f"fail retry {self.context.retry_count}/{self.max_retries}")
                    else:
                        self._transition(FSMState.EXECUTE, f"fail retry {self.context.retry_count}/{self.max_retries}")
                else:
                    self.context.error = "Max retries exhausted"
                    self._transition(FSMState.DONE, "max retries exhausted")

        # Complete
        self.trace.log_workflow_complete(
            final_state=self.state.value,
            total_latency_ms=0,
            total_retries=self.context.retry_count,
            result_length=len(self.context.final_result),
        )
        return self.context

    # ── CLASSIFY Step (v5: zero-LLM-call heuristic) ──

    async def _step_classify(self) -> None:
        """
        Classify task complexity and route to appropriate mode.
        No LLM calls — deterministic heuristic.
        """
        start = time.monotonic()

        if self.force_mode:
            complexity = self.force_mode
            confidence = 1.0
            reasons = [f"Forced mode: {self.force_mode}"]
        else:
            result = classify_task(self.context.user_input)
            complexity = result.level.value
            confidence = result.confidence
            reasons = result.reasons

        self.context.complexity = complexity

        # Mode routing
        if complexity == "SIMPLE":
            mode = ExecutionMode.SIMPLE
        elif complexity == "STANDARD":
            mode = ExecutionMode.STANDARD
        else:
            mode = ExecutionMode.COMPLEX

        self.context.execution_mode = mode.value

        latency = int((time.monotonic() - start) * 1000)
        self.trace.log_agent_result(
            "classifier", "CLASSIFY",
            {"complexity": complexity, "confidence": confidence, "mode": mode.value, "reasons": reasons},
            latency_ms=latency,
        )
        logger.info(f"[{self.context.task_id}] Classified as {complexity} → {mode.value}")

        # Transition to execution mode
        if mode == ExecutionMode.SIMPLE:
            self._transition(FSMState.SIMPLE_EXEC, f"complexity={complexity}")
        elif mode == ExecutionMode.STANDARD:
            self._transition(FSMState.STD_EXEC, f"complexity={complexity}")
        else:
            self._transition(FSMState.PLAN, f"complexity={complexity}")

    # ── SIMPLE_EXEC Step (v5: executor only, no planner/reviewer) ──

    async def _step_simple_exec(self) -> None:
        """
        SIMPLE mode: single executor agent only.
        No planner, no reviewer, no validation gate.
        Minimizes LLM calls (1 call total).
        """
        start = time.monotonic()
        self.context.skipped_stages = ["planner", "reviewer", "validation_gate"]

        # Direct executor call — no plan needed
        isolated = self.context_isolation.isolate(
            agent_id="executor",
            state="SIMPLE_EXEC",
            global_context={"task": self.context.user_input},
        )

        unit = self.scheduler.submit(
            fn=executor_fn,
            agent_id="executor",
            state="SIMPLE_EXEC",
            kwargs={
                "plan": {"task": self.context.user_input, "mode": "simple"},
                "original_task": self.context.user_input,
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )

        self.trace.log_agent_dispatch("executor", "SIMPLE_EXEC", {"task": self.context.user_input[:200]})
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        latency = int((time.monotonic() - start) * 1000)
        self.context.llm_calls += 1

        if unit.status != "SUCCESS" or unit.result is None:
            self.trace.log_error("SIMPLE_EXEC", f"Execution failed: {unit.error}", "executor")
            self.context.error = f"Simple execution failed: {unit.error}"
            self._transition(FSMState.FAIL_RETRY, "simple execution failed")
            return

        output: AgentOutput = unit.result

        if output.status == "error":
            self.context.error = output.reasoning or "Executor returned error"
            self._transition(FSMState.FAIL_RETRY, "simple execution error")
            return

        self.trace.log_agent_result(
            "executor", "SIMPLE_EXEC",
            {"result": output.result[:300], "reasoning": output.reasoning},
            latency_ms=latency,
        )

        self.context.execution_result = {"result": output.result, "reasoning": output.reasoning}
        self.context.final_result = output.result
        self._transition(FSMState.DONE, "simple execution complete")

    # ── STD_EXEC Step (v5: executor + validation gate) ──

    async def _step_std_exec(self) -> None:
        """
        STANDARD mode: executor + validation gate.
        No planner, no reviewer.
        Cost: 1 LLM call + 1 deterministic validation.
        """
        start = time.monotonic()
        self.context.skipped_stages = ["planner", "reviewer"]

        # Execute
        isolated = self.context_isolation.isolate(
            agent_id="executor",
            state="STD_EXEC",
            global_context={"task": self.context.user_input},
        )

        unit = self.scheduler.submit(
            fn=executor_fn,
            agent_id="executor",
            state="STD_EXEC",
            kwargs={
                "plan": {"task": self.context.user_input, "mode": "standard"},
                "original_task": self.context.user_input,
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )

        self.trace.log_agent_dispatch("executor", "STD_EXEC", {"task": self.context.user_input[:200]})
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        latency = int((time.monotonic() - start) * 1000)
        self.context.llm_calls += 1

        if unit.status != "SUCCESS" or unit.result is None:
            self.trace.log_error("STD_EXEC", f"Execution failed: {unit.error}", "executor")
            self.context.error = f"Standard execution failed: {unit.error}"
            self._transition(FSMState.FAIL_RETRY, "standard execution failed")
            return

        output: AgentOutput = unit.result

        if output.status == "error":
            self.context.error = output.reasoning or "Executor returned error"
            self._transition(FSMState.FAIL_RETRY, "standard execution error")
            return

        # Validation gate (deterministic, no LLM call)
        validation: ValidationResult = validate_output(output, "executor")
        self.trace.log_validation("executor", "STD_EXEC", validation.to_dict())

        self.trace.log_agent_result(
            "executor", "STD_EXEC",
            {"result": output.result[:300], "reasoning": output.reasoning, "validation": validation.is_valid},
            latency_ms=latency,
        )

        self.context.execution_result = {"result": output.result, "reasoning": output.reasoning}
        self.context.final_result = output.result
        self._transition(FSMState.DONE, "standard execution complete")

    # ── PLAN Step (via Scheduler) ──

    async def _step_plan(self) -> bool:
        """Execute planner through Scheduler. Returns True on success."""
        start = time.monotonic()

        # 1. Isolate context (anti-leak)
        isolated = self.context_isolation.isolate(
            agent_id="planner",
            state="PLAN",
            global_context={
                "task": self.context.user_input,
                # These are intentionally NOT included — agents don't need them:
                # "api_key", "provider", "model", "base_url", "retry_count", etc.
            },
        )
        self.trace.log_context_isolated("planner", "PLAN", list(isolated.to_dict().keys()))

        # 2. Submit to scheduler
        unit = self.scheduler.submit(
            fn=planner_fn,
            agent_id="planner",
            state="PLAN",
            kwargs={
                "task": isolated.get("task", ""),
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )

        # 3. Log dispatch
        self.trace.log_agent_dispatch("planner", "PLAN", {"task": self.context.user_input[:200]})

        # 4. Execute via scheduler (with retry)
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        # 5. Process result
        latency = int((time.monotonic() - start) * 1000)

        if unit.status != "SUCCESS" or unit.result is None:
            self.trace.log_error("PLAN", f"Execution failed: {unit.error}", "planner")
            self.context.error = f"Plan execution failed: {unit.error}"
            return False

        output: AgentOutput = unit.result

        # 6. Flow control check
        flow_result = self.flow_control.check("planner", output.result)
        self.trace.log_flow_control("planner", "PLAN", "no_flow_control", flow_result.enforced)
        if not flow_result.enforced:
            self.trace.log_error("PLAN", f"Flow control violation: {flow_result.violation_type}", "planner")
            self.context.error = f"Flow control violation: {flow_result.violation_detail}"
            return False

        # 7. Validation gate
        validation: ValidationResult = validate_output(output, "planner")
        self.trace.log_validation("planner", "PLAN", validation.to_dict())

        # 8. Log result
        self.trace.log_agent_result(
            "planner", "PLAN",
            {"result": output.result[:300], "reasoning": output.reasoning},
            latency_ms=latency,
        )

        if not validation.is_valid:
            self.context.error = f"Plan validation failed: {validation.reason}"
            return False

        # 9. Context isolation: validate no leak in output
        if not self.context_isolation.validate_no_leak(output.result, "planner"):
            self.context.error = "Context leak detected in planner output"
            return False

        self.context.plan = {"result": output.result, "reasoning": output.reasoning}
        return True

    # ── EXECUTE Step (via Scheduler) ──

    async def _step_execute(self) -> bool:
        """Execute executor through Scheduler. Returns True on success."""
        start = time.monotonic()

        # 1. Isolate context
        isolated = self.context_isolation.isolate(
            agent_id="executor",
            state="EXECUTE",
            global_context={
                "plan": self.context.plan,
                "original_task": self.context.user_input,
            },
        )
        self.trace.log_context_isolated("executor", "EXECUTE", list(isolated.to_dict().keys()))

        # 2. Submit to scheduler
        unit = self.scheduler.submit(
            fn=executor_fn,
            agent_id="executor",
            state="EXECUTE",
            kwargs={
                "plan": isolated.get("plan", {}),
                "original_task": isolated.get("original_task", ""),
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )

        # 3. Log dispatch
        self.trace.log_agent_dispatch("executor", "EXECUTE", {"plan": str(self.context.plan)[:200]})

        # 4. Execute via scheduler
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        # 5. Process result
        latency = int((time.monotonic() - start) * 1000)

        if unit.status != "SUCCESS" or unit.result is None:
            self.trace.log_error("EXECUTE", f"Execution failed: {unit.error}", "executor")
            self.context.error = f"Execute execution failed: {unit.error}"
            return False

        output: AgentOutput = unit.result

        # 6. Flow control check
        flow_result = self.flow_control.check("executor", output.result)
        self.trace.log_flow_control("executor", "EXECUTE", "no_flow_control", flow_result.enforced)
        if not flow_result.enforced:
            self.trace.log_error("EXECUTE", f"Flow control violation: {flow_result.violation_type}", "executor")
            self.context.error = f"Flow control violation: {flow_result.violation_detail}"
            return False

        # 7. Validation gate
        validation: ValidationResult = validate_output(output, "executor")
        self.trace.log_validation("executor", "EXECUTE", validation.to_dict())

        # 8. Log result
        self.trace.log_agent_result(
            "executor", "EXECUTE",
            {"result": output.result[:300], "reasoning": output.reasoning},
            latency_ms=latency,
        )

        if not validation.is_valid:
            self.context.error = f"Execute validation failed: {validation.reason}"
            return False

        # 9. Context leak check
        if not self.context_isolation.validate_no_leak(output.result, "executor"):
            self.context.error = "Context leak detected in executor output"
            return False

        self.context.execution_result = {"result": output.result, "reasoning": output.reasoning}
        self.context.final_result = output.result
        return True

    # ── REVIEW Step (via Scheduler) ──

    async def _step_review(self) -> bool:
        """Execute reviewer through Scheduler. Returns True if review passes."""
        start = time.monotonic()

        # 1. Isolate context
        isolated = self.context_isolation.isolate(
            agent_id="reviewer",
            state="REVIEW",
            global_context={
                "result": self.context.final_result,
                "original_task": self.context.user_input,
            },
        )
        self.trace.log_context_isolated("reviewer", "REVIEW", list(isolated.to_dict().keys()))

        # 2. Submit to scheduler
        unit = self.scheduler.submit(
            fn=reviewer_fn,
            agent_id="reviewer",
            state="REVIEW",
            kwargs={
                "result": isolated.get("result", ""),
                "original_task": isolated.get("original_task", ""),
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            },
            max_attempts=self.max_retries,
        )

        # 3. Log dispatch
        self.trace.log_agent_dispatch("reviewer", "REVIEW", {"result_preview": self.context.final_result[:200]})

        # 4. Execute via scheduler
        unit = await self.scheduler.execute_with_retry(unit, self.retry_policy)

        # 5. Process result
        latency = int((time.monotonic() - start) * 1000)

        if unit.status != "SUCCESS" or unit.result is None:
            self.trace.log_error("REVIEW", f"Execution failed: {unit.error}", "reviewer")
            self.context.error = f"Review execution failed: {unit.error}"
            return False

        output: AgentOutput = unit.result

        # 6. Flow control check
        flow_result = self.flow_control.check("reviewer", output.result)
        self.trace.log_flow_control("reviewer", "REVIEW", "no_flow_control", flow_result.enforced)
        if not flow_result.enforced:
            self.trace.log_error("REVIEW", f"Flow control violation: {flow_result.violation_type}", "reviewer")
            self.context.error = f"Flow control violation: {flow_result.violation_detail}"
            return False

        # 7. Validation gate
        validation: ValidationResult = validate_output(output, "reviewer")
        self.trace.log_validation("reviewer", "REVIEW", validation.to_dict())

        # 8. Log result
        self.trace.log_agent_result(
            "reviewer", "REVIEW",
            {"result": output.result[:300], "reasoning": output.reasoning},
            latency_ms=latency,
        )

        if not validation.is_valid:
            self.context.error = f"Review validation failed: {validation.reason}"
            return False

        # 9. Parse review decision
        review_passed = _parse_review_pass(output.result)
        self.context.review_result = {
            "result": output.result,
            "reasoning": output.reasoning,
            "pass": review_passed,
        }
        return review_passed

    # ── Report ──

    def get_trace_report(self) -> dict:
        if self.trace:
            return self.trace.build_report()
        return {"trace_id": self.trace_id, "events": []}


# ── Helpers ──

def _classify_intent(task: str) -> str:
    """Deterministic intent classification (no LLM)."""
    t = task.lower()
    if any(kw in t for kw in ["代码", "code", "编程", "函数", "class", "debug", "修复"]):
        return "code"
    if any(kw in t for kw in ["分析", "analyze", "数据", "趋势", "统计"]):
        return "analysis"
    if any(kw in t for kw in ["推理", "reasoning", "为什么", "原因", "解释"]):
        return "reasoning"
    return "complex"


def _parse_review_pass(raw: str) -> bool:
    """Parse review agent output to determine pass/fail."""
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


# ── Factory ──

def create_fsm_orchestrator(**kwargs) -> FSMOrchestrator:
    return FSMOrchestrator(**kwargs)
