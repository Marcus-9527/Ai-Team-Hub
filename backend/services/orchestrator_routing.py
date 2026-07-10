"""
orchestrator/routing.py — Task routing, cost engine, model router, circuit breaker.

Replaces scattered routing/cost/circuit-breaker logic in orchestrator_core.py.
All model selection is configurable — no hardcoded model names.
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("orchestrator.routing")


# ═══════════════════════════════════════════════════════════════
# Execution Mode
# ═══════════════════════════════════════════════════════════════

class ExecutionMode(str, Enum):
    SIMPLE = "SIMPLE"       # 1 LLM call, no review
    STANDARD = "STANDARD"   # 1 LLM call + validation
    COMPLEX = "COMPLEX"     # Plan → Execute → Review


# ═══════════════════════════════════════════════════════════════
# Model Router (Phase 8 — Never hardcode model)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ModelConfig:
    """Configuration for a single model."""
    name: str
    provider: str = "openrouter"
    base_url: Optional[str] = None
    max_tokens: int = 4096
    cost_per_1k_tokens: float = 0.0       # cost per 1K input tokens
    cost_per_1k_output: float = 0.0       # cost per 1K output tokens
    capabilities: list = field(default_factory=lambda: ["chat"])
    speed_tier: str = "standard"          # fast | standard | slow


@dataclass
class ModelRouter:
    """
    Routes tasks to appropriate models based on complexity and budget.
    
    Routing policy:
    - SIMPLE → cheapest model with 'chat' capability
    - STANDARD → balanced model
    - COMPLEX → best model available (coding/reasoning)
    - review → fastest model (cheap, quick validation)
    """
    models: dict = field(default_factory=dict)
    _default_model: str = "openrouter/auto"
    _default_provider: str = "openrouter"
    
    def add_model(self, model_id: str, config: ModelConfig):
        self.models[model_id] = config
    
    def route(self, execution_mode: ExecutionMode, budget_remaining: float = None) -> ModelConfig:
        """Select best model for the given execution mode and budget."""
        candidates = list(self.models.values())
        
        if execution_mode == ExecutionMode.SIMPLE:
            # Pick cheapest model
            candidates.sort(key=lambda m: m.cost_per_1k_tokens)
        elif execution_mode == ExecutionMode.COMPLEX:
            # Pick best coding model within budget
            coding = [m for m in candidates if "coding" in m.capabilities] or candidates
            if budget_remaining is not None:
                coding = [m for m in coding if m.cost_per_1k_tokens * 15 < budget_remaining] or coding
            coding.sort(key=lambda m: m.cost_per_1k_tokens, reverse=True)
            candidates = coding
        elif execution_mode == ExecutionMode.STANDARD:
            # Balanced: mid-range
            candidates.sort(key=lambda m: m.cost_per_1k_tokens, reverse=True)
            candidates = candidates[max(0, len(candidates)//2):]
        else:
            # Review: fastest/cheapest
            candidates.sort(key=lambda m: (m.speed_tier, m.cost_per_1k_tokens))
        
        return candidates[0] if candidates else self._fallback()
    
    def route_for_review(self) -> ModelConfig:
        """Review uses the fastest model available."""
        candidates = sorted(self.models.values(), key=lambda m: (m.speed_tier, m.cost_per_1k_tokens))
        return candidates[0] if candidates else self._fallback()
    
    def _fallback(self) -> ModelConfig:
        if self._default_model in self.models:
            return self.models[self._default_model]
        return ModelConfig(name=self._default_model, provider=self._default_provider)


# ═══════════════════════════════════════════════════════════════
# Cost Engine (Phase 7 — Execution Budget)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ExecutionBudget:
    """Hard limits for a single task execution."""
    max_teammates: int = 3
    max_tokens: int = 50000
    max_cost: float = 1.0              # in USD
    max_latency_ms: int = 30000
    max_llm_calls: int = 8
    
    # Current state
    tokens_used: int = 0
    cost_incurred: float = 0.0
    teammate_calls: int = 0
    llm_calls: int = 0
    start_time: float = field(default_factory=time.time)
    
    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.tokens_used)
    
    @property
    def remaining_cost(self) -> float:
        return max(0.0, self.max_cost - self.cost_incurred)
    
    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)
    
    @property
    def is_exhausted(self) -> bool:
        return (self.tokens_used >= self.max_tokens or
                self.cost_incurred >= self.max_cost or
                self.llm_calls >= self.max_llm_calls or
                self.elapsed_ms >= self.max_latency_ms)
    
    def record_call(self, tokens: int, cost: float):
        self.tokens_used += tokens
        self.cost_incurred += cost
        self.llm_calls += 1
        self.teammate_calls += 1
    
    def should_skip_reviewer(self) -> bool:
        """Determine if we should skip the reviewer to save budget."""
        return (self.llm_calls >= self.max_llm_calls - 1 or
                self.tokens_used > self.max_tokens * 0.8 or
                self.cost_incurred > self.max_cost * 0.8)
    
    def should_collapse_to_single_teammate(self) -> bool:
        """Downgrade to single teammate if budget is tight."""
        return (self.llm_calls >= 2 or
                self.tokens_used > self.max_tokens * 0.5)
    
    def to_dict(self) -> dict:
        return {
            "tokens_used": self.tokens_used,
            "tokens_remaining": self.remaining_tokens,
            "cost_incurred": round(self.cost_incurred, 4),
            "cost_remaining": round(self.remaining_cost, 4),
            "llm_calls": self.llm_calls,
            "elapsed_ms": self.elapsed_ms,
            "exhausted": self.is_exhausted,
        }


# ═══════════════════════════════════════════════════════════════
# Circuit Breaker (Phase 10 — Reliability)
# ═══════════════════════════════════════════════════════════════

class CircuitBreakerState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject calls
    HALF_OPEN = "half_open" # Testing if service recovered


class CircuitBreaker:
    """
    Prevents cascading failures by opening circuit after N consecutive failures.
    
    States:
    - CLOSED: Normal, track failures
    - OPEN: Reject calls immediately, wait for recovery time
    - HALF_OPEN: Allow one test call, if success → CLOSED, if fail → OPEN
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_time: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0
    
    @property
    def state(self) -> CircuitBreakerState:
        if self._state == CircuitBreakerState.OPEN:
            # Check if recovery time has passed
            if time.time() - self._last_failure_time >= self.recovery_time:
                self._state = CircuitBreakerState.HALF_OPEN
        return self._state
    
    def is_open(self) -> bool:
        return self.state == CircuitBreakerState.OPEN
    
    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitBreakerState.OPEN
            logger.warning(f"Circuit breaker OPEN after {self._failure_count} failures")
    
    def record_success(self):
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count += 1
    
    def reset(self):
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
    
    @property
    def stats(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
        }


# ═══════════════════════════════════════════════════════════════
# Global Bounds (combines all limits)
# ═══════════════════════════════════════════════════════════════

@dataclass
class GlobalBounds:
    """System-wide execution limits."""
    max_teammate_calls: int = 5
    max_diversity_retries: int = 2
    max_total_latency_ms: int = 30000
    max_single_teammate_ms: int = 10000
    max_tokens_per_task: int = 50000
    max_tokens_per_teammate: int = 20000
    max_cost_per_task: float = 1.0
    latency_degradation_ms: int = 20000
    token_degradation_threshold: int = 40000


# ═══════════════════════════════════════════════════════════════
# Complexity Classifier (zero-LLM)
# ═══════════════════════════════════════════════════════════════

class Complexity(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


@dataclass
class Classification:
    level: Complexity
    reasoning: str = ""


def classify_task(task: str) -> Classification:
    """Deterministic complexity classification (no LLM call)."""
    t = task.lower()
    char_count = len(task)
    
    # Short/factual queries → SIMPLE
    if char_count <= 8:
        return Classification(Complexity.SIMPLE, "short_query")
    
    # Code-related with clear scope → STANDARD
    code_keywords = ["代码", "code", "编程", "函数", "class", "debug", "修复", "implement", "write"]
    analysis_keywords = ["分析", "analyze", "数据", "趋势", "统计", "compare", "对比"]
    complex_keywords = ["设计", "架构", "design", "architect", "系统", "system", "完整", "complete"]
    
    if any(kw in t for kw in complex_keywords) or char_count > 200:
        return Classification(Complexity.COMPLEX, "complex_task")
    if any(kw in t for kw in analysis_keywords):
        return Classification(Complexity.STANDARD, "analysis_task")
    if any(kw in t for kw in code_keywords):
        return Classification(Complexity.STANDARD, "code_task")
    
    return Classification(Complexity.SIMPLE, "general_query")
