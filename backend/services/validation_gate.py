"""
validation_gate.py — Mandatory Output Validation Gate

Validates every agent output before passing to next state.
Runs AFTER every agent execution.

Checks:
  1. Schema correctness (status, result, reasoning fields present)
  2. Non-empty output (result field not empty on success)
  3. Structural compliance (status is valid enum value)

On failure:
  - Do NOT pass to next state
  - Trigger retry or fallback in orchestrator
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from backend.services.agent_functions import AgentOutput

logger = logging.getLogger("validation_gate")


# ── Validation Result ──

@dataclass
class ValidationResult:
    is_valid: bool
    reason: str
    check_schema: bool = True
    check_nonempty: bool = True
    check_structural: bool = True

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "reason": self.reason,
            "checks": {
                "schema": self.check_schema,
                "nonempty": self.check_nonempty,
                "structural": self.check_structural,
            },
        }


# ── Valid Status Values ──

VALID_STATUSES = {"success", "error"}


# ── Main Validation Entry ──

def validate_output(output: Optional[AgentOutput], agent_role: str) -> ValidationResult:
    """
    Validate agent output. All checks must pass.

    Args:
        output: AgentOutput from agent execution
        agent_role: "planner" | "executor" | "reviewer"

    Returns:
        ValidationResult with is_valid=True only if ALL checks pass
    """
    # Check 1: Output exists
    if output is None:
        return ValidationResult(
            is_valid=False,
            reason="Output is None",
            check_schema=False,
            check_nonempty=False,
            check_structural=False,
        )

    # Check 2: Schema correctness
    schema_ok = _check_schema(output)
    if not schema_ok:
        return ValidationResult(
            is_valid=False,
            reason="Schema validation failed: missing required fields",
            check_schema=False,
        )

    # Check 3: Status value valid
    structural_ok = _check_structural(output)
    if not structural_ok:
        return ValidationResult(
            is_valid=False,
            reason=f"Invalid status value: '{output.status}'",
            check_structural=False,
        )

    # Check 4: Non-empty result on success
    if output.status == "success":
        nonempty_ok = _check_nonempty(output, agent_role)
        if not nonempty_ok:
            return ValidationResult(
                is_valid=False,
                reason=f"Empty result from {agent_role} on success status",
                check_nonempty=False,
            )

    # Check 5: Role-specific structural compliance
    role_ok = _check_role_compliance(output, agent_role)
    if not role_ok:
        return ValidationResult(
            is_valid=False,
            reason=f"Role compliance check failed for {agent_role}",
        )

    return ValidationResult(is_valid=True, reason="All checks passed")


# ── Individual Checks ──

def _check_schema(output: AgentOutput) -> bool:
    """Check that all required fields exist and are strings."""
    try:
        if not isinstance(output.status, str):
            return False
        if not isinstance(output.result, str):
            return False
        if not isinstance(output.reasoning, str):
            return False
        return True
    except Exception:
        return False


def _check_structural(output: AgentOutput) -> bool:
    """Check that status is a valid enum value."""
    return output.status in VALID_STATUSES


def _check_nonempty(output: AgentOutput, agent_role: str) -> bool:
    """Check that result is not empty when status is success."""
    if output.status != "success":
        return True  # Only check on success
    result = output.result.strip()
    if not result:
        return False
    # Role-specific minimum lengths
    min_lengths = {
        "planner": 10,    # Plan should have some substance
        "executor": 10,   # Code/output should have some substance
        "reviewer": 5,    # Review can be short
    }
    min_len = min_lengths.get(agent_role, 5)
    return len(result) >= min_len


def _check_role_compliance(output: AgentOutput, agent_role: str) -> bool:
    """Check role-specific output structure."""
    if output.status != "success":
        return True  # Only check on success

    if agent_role == "planner":
        # Planner output should be parseable as JSON (plan structure)
        return _is_valid_plan(output.result)
    elif agent_role == "executor":
        # Executor output should not be pure error text
        return not output.result.strip().startswith("Error:")
    elif agent_role == "reviewer":
        # Reviewer output should contain pass/fail indication
        return _contains_review_decision(output.result)
    return True


def _is_valid_plan(result: str) -> bool:
    """Check if result contains a valid plan structure."""
    text = result.strip()
    # Try JSON parse
    try:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            items = json.loads(text[start:end + 1])
            if isinstance(items, list) and len(items) > 0:
                return True
    except (json.JSONDecodeError, Exception):
        pass
    # Also accept object with subtasks
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict) and len(obj) > 0:
                return True
    except (json.JSONDecodeError, Exception):
        pass
    # Fallback: must have some structured content (not just prose)
    return len(text) > 20


def _contains_review_decision(result: str) -> bool:
    """Check if review output contains a pass/fail decision."""
    text = result.lower()
    # JSON with pass field
    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(result[start:end])
            if "pass" in data or "passed" in data:
                return True
    except (json.JSONDecodeError, Exception):
        pass
    # Keyword check
    decision_words = ["pass", "fail", "通过", "不通过", "approved", "rejected"]
    return any(w in text for w in decision_words)
