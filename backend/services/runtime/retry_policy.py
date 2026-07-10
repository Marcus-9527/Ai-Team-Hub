"""
runtime/retry_policy.py — Retry + Failure Policy Engine

Failure classification:
  - VALIDATION_FAIL  → retry same node (output was invalid, try again)
  - LOGIC_FAIL       → fallback node (teammate produced bad logic, try different approach)
  - SYSTEM_FAIL      → abort workflow (infrastructure error, no point retrying)

Backoff strategies:
  - fixed: constant delay
  - linear: delay = base * attempt
  - exponential: delay = base * 2^attempt
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("runtime.retry_policy")


# ── Failure Classification ──

class FailureType(str, Enum):
    VALIDATION_FAIL = "VALIDATION_FAIL"
    LOGIC_FAIL = "LOGIC_FAIL"
    SYSTEM_FAIL = "SYSTEM_FAIL"
    UNKNOWN = "UNKNOWN"


# ── Backoff Strategy ──

class BackoffStrategy(str, Enum):
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


# ── Retry Decision ──

class RetryAction(str, Enum):
    RETRY = "retry"
    FALLBACK = "fallback"
    ABORT = "abort"


@dataclass
class RetryDecision:
    action: str          # RetryAction value
    reason: str
    delay_ms: int = 0
    failure_type: str = ""


# ── Retry Policy ──

@dataclass
class RetryPolicy:
    """
    Configurable retry + failure policy.

    Usage:
        policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.LINEAR,
            base_delay_ms=1000,
        )
        decision = policy.decide(exec_unit)
    """
    max_retries: int = 3
    backoff_strategy: str = BackoffStrategy.LINEAR
    base_delay_ms: int = 1000
    max_delay_ms: int = 30000

    # Failure type → action mapping
    _type_actions: dict = None

    def __post_init__(self):
        if self._type_actions is None:
            self._type_actions = {
                FailureType.VALIDATION_FAIL: RetryAction.RETRY,
                FailureType.LOGIC_FAIL: RetryAction.FALLBACK,
                FailureType.SYSTEM_FAIL: RetryAction.ABORT,
                FailureType.UNKNOWN: RetryAction.RETRY,
            }

    def classify(self, error: str, validation_failed: bool) -> FailureType:
        """Classify failure from error message and validation status."""
        if validation_failed:
            return FailureType.VALIDATION_FAIL

        err_lower = error.lower()
        # System-level errors
        system_keywords = ["timeout", "connection", "network", "dns", "refused", "reset", "502", "503", "504"]
        if any(kw in err_lower for kw in system_keywords):
            return FailureType.SYSTEM_FAIL

        # Logic errors
        logic_keywords = ["json parse", "invalid format", "schema", "logic", "reasoning"]
        if any(kw in err_lower for kw in logic_keywords):
            return FailureType.LOGIC_FAIL

        return FailureType.UNKNOWN

    def decide(self, unit: "ExecUnit") -> RetryDecision:
        """
        Decide what to do after a failed execution.

        Returns RetryDecision with action, reason, and delay.
        """
        failure_type = self.classify(unit.error, validation_failed=False)
        action = self._type_actions.get(failure_type, RetryAction.RETRY)

        # Check retry budget
        if unit.attempt > self.max_retries:
            return RetryDecision(
                action=RetryAction.ABORT,
                reason=f"Max retries ({self.max_retries}) exhausted for {failure_type.value}",
                failure_type=failure_type.value,
            )

        if action == RetryAction.ABORT:
            return RetryDecision(
                action=RetryAction.ABORT,
                reason=f"System failure, aborting: {unit.error[:100]}",
                failure_type=failure_type.value,
            )

        if action == RetryAction.FALLBACK:
            return RetryDecision(
                action=RetryAction.FALLBACK,
                reason=f"Logic failure, switching to fallback: {unit.error[:100]}",
                failure_type=failure_type.value,
            )

        # RETRY — compute backoff delay
        delay = self._compute_delay(unit.attempt)
        return RetryDecision(
            action=RetryAction.RETRY,
            reason=f"Retry {unit.attempt}/{self.max_retries} for {failure_type.value}",
            delay_ms=delay,
            failure_type=failure_type.value,
        )

    def _compute_delay(self, attempt: int) -> int:
        """Compute backoff delay in ms."""
        if self.backoff_strategy == BackoffStrategy.FIXED:
            delay = self.base_delay_ms
        elif self.backoff_strategy == BackoffStrategy.LINEAR:
            delay = self.base_delay_ms * attempt
        elif self.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.base_delay_ms * (2 ** (attempt - 1))
        else:
            delay = self.base_delay_ms
        return min(delay, self.max_delay_ms)
