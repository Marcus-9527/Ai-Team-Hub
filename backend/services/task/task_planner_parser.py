"""
task_planner_parser.py — Plan JSON parsing, schema validation, and dependency checking.

Responsibilities:
  - Parse planner LLM output (JSON string) into a validated TaskPlan
  - Validate schema completeness and field types
  - Check step order continuity (1, 2, 3… no gaps)
  - Validate dependency references (all order refs exist, no cycles)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from backend.services.task.task_planner_schema import TaskPlan, TaskStepProposal

logger = logging.getLogger("task.planner.parser")


# ═══════════════════════════════════════════════════════════════
# Custom Errors
# ═══════════════════════════════════════════════════════════════

class PlannerParseError(Exception):
    """Base error for planner parsing failures."""
    pass


class PlannerJSONError(PlannerParseError):
    """Raised when planner output is not valid JSON."""
    pass


class PlannerSchemaError(PlannerParseError):
    """Raised when parsed JSON fails schema validation."""
    pass


class PlannerEmptyPlanError(PlannerParseError):
    """Raised when plan has no steps."""
    pass


class PlannerOrderError(PlannerParseError):
    """Raised when step order is invalid (non-contiguous, duplicate, etc.)."""
    pass


class PlannerDependencyError(PlannerParseError):
    """Raised when dependencies are invalid (missing refs, cycles, self-ref)."""
    pass


# ═══════════════════════════════════════════════════════════════
# JSON Extraction
# ═══════════════════════════════════════════════════════════════

def _extract_json(text: str) -> str:
    """
    Extract a JSON object from LLM output text.

    Handles:
      - Raw JSON
      - JSON inside ```json ... ``` fences
      - Text with embedded JSON
    """
    text = text.strip()

    # Try direct parse first
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # Try code fences
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Try first top-level {…}
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        candidate = brace_match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    raise PlannerJSONError("No valid JSON object found in planner output")


# ═══════════════════════════════════════════════════════════════
# Schema Validation
# ═══════════════════════════════════════════════════════════════

REQUIRED_PLAN_FIELDS = ["task_id", "title", "steps"]
REQUIRED_STEP_FIELDS = ["order", "teammate_id", "objective"]


def _validate_schema(data: dict) -> None:
    """Validate that the parsed JSON has all required fields with correct types."""
    # Plan-level required fields
    for field in REQUIRED_PLAN_FIELDS:
        if field not in data:
            raise PlannerSchemaError(f"Missing required plan field: '{field}'")
        if field == "steps" and not isinstance(data["steps"], list):
            raise PlannerSchemaError(f"Field 'steps' must be a list, got {type(data['steps']).__name__}")

    # Step-level validation
    steps = data["steps"]
    if not isinstance(steps, list):
        raise PlannerSchemaError("'steps' must be a list")

    if len(steps) == 0:
        raise PlannerEmptyPlanError("Plan has zero steps")

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlannerSchemaError(f"Step at index {i} is not a dict, got {type(step).__name__}")
        for field in REQUIRED_STEP_FIELDS:
            if field not in step:
                raise PlannerSchemaError(f"Step {i} missing required field: '{field}'")

        # Type checks
        if not isinstance(step["order"], int):
            raise PlannerSchemaError(f"Step {i} 'order' must be int, got {type(step['order']).__name__}")
        if not isinstance(step["teammate_id"], str):
            raise PlannerSchemaError(f"Step {i} 'teammate_id' must be str, got {type(step['teammate_id']).__name__}")
        if not isinstance(step["objective"], str):
            raise PlannerSchemaError(f"Step {i} 'objective' must be str, got {type(step['objective']).__name__}")

        # depends_on must be list[int]
        depends = step.get("depends_on", [])
        if not isinstance(depends, list):
            raise PlannerSchemaError(f"Step {i} 'depends_on' must be a list, got {type(depends).__name__}")
        for ref in depends:
            if not isinstance(ref, int):
                raise PlannerSchemaError(f"Step {i} depends_on contains non-int: {ref}")

        # risk_level validation
        risk = step.get("risk_level", "LOW")
        if risk not in ("LOW", "MEDIUM", "HIGH"):
            raise PlannerSchemaError(f"Step {i} invalid risk_level '{risk}' — must be LOW/MEDIUM/HIGH")

        # confidence validation
        conf = step.get("confidence", 0.0)
        if not isinstance(conf, (int, float)):
            raise PlannerSchemaError(f"Step {i} 'confidence' must be numeric, got {type(conf).__name__}")
        if conf < 0.0 or conf > 1.0:
            raise PlannerSchemaError(f"Step {i} 'confidence' {conf} out of range [0.0, 1.0]")

    # Plan-level risk_level
    plan_risk = data.get("risk_level", "LOW")
    if plan_risk not in ("LOW", "MEDIUM", "HIGH"):
        raise PlannerSchemaError(f"Plan risk_level '{plan_risk}' invalid — must be LOW/MEDIUM/HIGH")


# ═══════════════════════════════════════════════════════════════
# Order Validation
# ═══════════════════════════════════════════════════════════════

def _validate_order(steps: list[dict]) -> None:
    """Validate step order: 1-based contiguous, no duplicates, increasing."""
    orders = [s["order"] for s in steps]
    if min(orders) != 1:
        raise PlannerOrderError(f"Step orders must start at 1, got min={min(orders)}")
    if len(set(orders)) != len(orders):
        seen = set()
        dups = {o for o in orders if o in seen or (seen.add(o) or False)}  # noqa
        first_dup = next(o for i, o in enumerate(orders) if o in [orders[j] for j in range(i)])
        raise PlannerOrderError(f"Duplicate step order: {first_dup}")

    # Must be contiguous (no gaps)
    expected = list(range(1, len(steps) + 1))
    if sorted(orders) != expected:
        actual = sorted(orders)
        missing = set(expected) - set(actual)
        raise PlannerOrderError(f"Non-contiguous order. Missing orders: {sorted(missing)}")


# ═══════════════════════════════════════════════════════════════
# Dependency Validation
# ═══════════════════════════════════════════════════════════════

def _validate_dependencies(steps: list[dict]) -> None:
    """
    Validate dependency references.

    Checks:
      1. All refs point to existing orders
      2. No self-reference (step depends on itself)
      3. No cycles (via DFS-based cycle detection)
      4. No forward references beyond current step (optional — allows forward refs but warns)
    """
    orders = {s["order"] for s in steps}
    order_map = {s["order"]: s for s in steps}

    # Build adjacency list for cycle detection
    adj: dict[int, list[int]] = {s["order"]: [] for s in steps}

    for s in steps:
        o = s["order"]
        deps = s.get("depends_on", [])

        for ref in deps:
            # Self-reference
            if ref == o:
                raise PlannerDependencyError(f"Step {o} depends on itself")

            # Non-existent order
            if ref not in orders:
                raise PlannerDependencyError(
                    f"Step {o} depends on non-existent order {ref}. "
                    f"Valid orders: {sorted(orders)}"
                )

            # Forward reference allowed but we warn (not an error in Phase A)
            if ref > o:
                logger.warning(f"Step {o} forward-depends on order {ref} (allowed but unusual)")

            adj[o].append(ref)

    # Cycle detection via DFS
    visited: set[int] = set()
    recursion_stack: set[int] = set()

    def _has_cycle(node: int, path: list[int]) -> Optional[list[int]]:
        visited.add(node)
        recursion_stack.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                result = _has_cycle(neighbor, path + [neighbor])
                if result:
                    return result
            elif neighbor in recursion_stack:
                return path + [neighbor]
        recursion_stack.discard(node)
        return None

    for s in steps:
        if s["order"] not in visited:
            cycle = _has_cycle(s["order"], [s["order"]])
            if cycle:
                cycle_str = " → ".join(str(o) for o in cycle)
                raise PlannerDependencyError(f"Circular dependency detected: {cycle_str}")


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def parse_plan(raw_output: str) -> TaskPlan:
    """
    Parse and validate planner LLM output into a TaskPlan.

    Full pipeline:
      1. Extract JSON from LLM output text
      2. Validate schema (required fields, types)
      3. Validate step order (1-based contiguous)
      4. Validate dependencies (refs exist, no cycles)
      5. Construct TaskPlan dataclass

    Args:
        raw_output: Raw string output from the planner LLM.

    Returns:
        A validated TaskPlan instance.

    Raises:
        PlannerJSONError: No valid JSON found.
        PlannerSchemaError: Missing fields or type errors.
        PlannerEmptyPlanError: Zero steps.
        PlannerOrderError: Order violations.
        PlannerDependencyError: Invalid dependencies.
    """
    # Step 1: Extract JSON
    json_str = _extract_json(raw_output)
    logger.debug(f"Extracted JSON ({len(json_str)} chars)")

    # Step 2: Parse to dict
    data = json.loads(json_str)
    if not isinstance(data, dict):
        raise PlannerSchemaError(f"Root value must be a dict, got {type(data).__name__}")

    # Step 3: Validate schema
    _validate_schema(data)
    logger.debug("Schema validation passed")

    # Step 4: Validate order
    _validate_order(data["steps"])
    logger.debug("Order validation passed")

    # Step 5: Validate dependencies
    _validate_dependencies(data["steps"])
    logger.debug("Dependency validation passed")

    # Step 6: Construct TaskPlan
    plan = TaskPlan.from_dict(data)
    logger.info(f"Plan parsed: {len(plan.steps)} steps, risk={plan.risk_level}, conf={plan.confidence}")
    return plan


def validate_plan(plan: TaskPlan) -> list[str]:
    """
    Run post-parse validation on a TaskPlan instance.

    Returns a list of warning strings (empty if no issues).
    Unlike parse_plan(), this does NOT raise — it collects issues.

    Checks:
      - Step count within reasonable bounds
      - Cost estimation sanity
      - Confidence consistency
    """
    warnings: list[str] = []

    if len(plan.steps) > 20:
        warnings.append(f"Plan has {len(plan.steps)} steps — consider splitting into sub-tasks")

    if plan.estimated_total_cost < 0:
        warnings.append(f"Negative estimated_total_cost: {plan.estimated_total_cost}")

    if plan.confidence < 0.3:
        warnings.append(f"Low planner confidence: {plan.confidence} — review plan carefully")

    # Check per-step confidence consistency
    low_conf_steps = [s for s in plan.steps if s.confidence < 0.3]
    if low_conf_steps:
        low_orders = [s.order for s in low_conf_steps]
        warnings.append(f"Low-confidence steps: {low_orders}")

    return warnings
