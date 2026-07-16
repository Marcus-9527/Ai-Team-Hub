"""
task_planner_driver.py — Planner Teammate orchestration driver.

Responsibilities:
  - generate_plan(): assemble planner input, submit via MAEOS, parse result
  - validate_plan(): post-parse validation of a TaskPlan

Flow (Phase B):
  1. Caller builds context with PlannerContextBuilder (task_planner_context.py)
  2. Pass PlannerContext.to_dict() as the `context` parameter
  3. generate_plan() embeds context into planner prompt
  4. MAEOS.submit() → parse → validate

Constraints (Phase A + B):
  ✅ Must use MAEOS.submit() for all LLM interaction
  ❌ No direct LLM calls
  ❌ No auto-execution (context building is explicit)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from backend.services.maeos import MAEOS, TaskPriority
from backend.services.task.task_planner_schema import TaskPlan, TaskPlannerInput
from backend.services.task.task_planner_parser import (
    parse_plan,
    validate_plan as parser_validate_plan,
    PlannerParseError,
    PlannerJSONError,
    PlannerSchemaError,
    PlannerEmptyPlanError,
    PlannerOrderError,
    PlannerDependencyError,
)
from backend.services.task.planner_prompts import (
    PLANNER_SYSTEM_PROMPT,
    PLANNER_DEFAULT_MAX_TOKENS,
)

logger = logging.getLogger("task.planner.driver")

# ── Retry constants ──
MAX_PLAN_RETRIES = 2
PLANNER_TIMEOUT = 120.0  # seconds


class PlanningError(Exception):
    """Raised when planning fails after exhausting retries."""
    pass


# ═══════════════════════════════════════════════════════════════
# Prompt builder
# ═══════════════════════════════════════════════════════════════

def _build_planner_prompt(goal: str, context: dict | None = None) -> str:
    """
    Build the user message for Planner MAEOS submission.

    Phase A: embeds the planner system prompt + goal as the user message,
    because the runtime uses a generic system_prompt.
    This approach works without modifying the runtime.
    """
    parts = [
        PLANNER_SYSTEM_PROMPT.strip(),
        "",
        "## User Goal",
        "",
        goal,
    ]

    if context:
        ctx_json = json.dumps(context, indent=2, ensure_ascii=False)
        parts.extend([
            "",
            "## Context",
            "",
            ctx_json,
        ])

    parts.extend([
        "",
        "Output ONLY the JSON TaskPlan object. No explanation, no markdown, no code fences.",
    ])

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

async def generate_plan(
    maeos: MAEOS,
    goal: str,
    task_id: str = "",
    context: dict | None = None,
    priority: int = TaskPriority.HIGH,
    api_key: str = "",
    provider: str = "openrouter",
) -> TaskPlan:
    """
    Generate a TaskPlan for a user goal via Planner Teammate.

    Flow:
      1. Build planner prompt from goal + context
      2. Submit to MAEOS (with retries on parse failure)
      3. Parse and validate the response
      4. Return TaskPlan

    Args:
        maeos: MAEOS instance (must be started).
        goal: User's goal description.
        task_id: Associated Task.id (for correlation).
        context: Optional context dict. In Phase B, build this with
            PlannerContextBuilder.build().to_dict() for rich context
            including task history, channel messages, workspace memory,
            and file references.
        priority: MAEOS task priority.
        api_key: Pre-resolved API key for this workspace (caller's
            responsibility to resolve using the parent DB session).
        provider: LLM provider name.

    Returns:
        A validated TaskPlan.

    Raises:
        PlanningError: After exhausting retries.
    """
    planner_prompt = _build_planner_prompt(goal, context)

    logger.info("[PLAN] using key_len=%d provider=%s",
                 len(api_key) if api_key else 0, provider)

    last_error: Exception | None = None

    for attempt in range(1, MAX_PLAN_RETRIES + 1):
        logger.info(f"Planning attempt {attempt}/{MAX_PLAN_RETRIES} for goal: {goal[:60]}...")

        try:
            # Step 1: Submit to MAEOS (this goes through the worker pipeline)
            maeos_task_id = await maeos.submit(
                description=planner_prompt,
                priority=priority,
                intent=f"planner:{task_id}" if task_id else "planner",
                wait=True,
                api_key=api_key or None,
                provider=provider,
            )

            # Step 2: Wait for completion
            completed_task = await maeos.wait(maeos_task_id, timeout=PLANNER_TIMEOUT)
            if completed_task is None:
                logger.warning(f"Planning attempt {attempt}: MAEOS timeout")
                if attempt < MAX_PLAN_RETRIES:
                    continue
                raise PlanningError(
                    f"Planner timed out after {PLANNER_TIMEOUT}s "
                    f"and {MAX_PLAN_RETRIES} attempts"
                )

            if completed_task.status == "FAILED":
                error_msg = completed_task.error or "Unknown error"
                logger.warning(f"Planning attempt {attempt}: MAEOS failed: {error_msg}")
                if attempt < MAX_PLAN_RETRIES:
                    continue
                raise PlanningError(f"Planner MAEOS task failed: {error_msg}")

            # Step 3: Get result
            result_text = completed_task.result or ""

            if not result_text.strip():
                logger.warning(f"Planning attempt {attempt}: empty result")
                if attempt < MAX_PLAN_RETRIES:
                    continue
                raise PlanningError("Planner returned empty result")

            # Step 4: Parse
            plan = parse_plan(result_text)

            # Override task_id if provided
            if task_id:
                plan.task_id = task_id

            # Post-parse validation (warnings only)
            warnings = parser_validate_plan(plan)
            if warnings:
                for w in warnings:
                    logger.warning(f"Plan validation: {w}")

            logger.info(
                f"Plan generated: {len(plan.steps)} steps, "
                f"risk={plan.risk_level}, confidence={plan.confidence}"
            )
            return plan

        except (PlannerJSONError, PlannerSchemaError, PlannerEmptyPlanError,
                PlannerOrderError, PlannerDependencyError) as e:
            last_error = e
            logger.warning(f"Planning attempt {attempt}: parse error: {e}")
            if attempt < MAX_PLAN_RETRIES:
                logger.info(f"Retrying planning (attempt {attempt + 1})...")
                continue
            raise PlanningError(
                f"Planning failed after {MAX_PLAN_RETRIES} attempts. "
                f"Last error: {e}"
            ) from e

        except PlanningError:
            raise

        except Exception as e:
            last_error = e
            logger.error(f"Planning attempt {attempt}: unexpected error: {e}")
            if attempt < MAX_PLAN_RETRIES:
                continue
            raise PlanningError(
                f"Planning failed after {MAX_PLAN_RETRIES} attempts. "
                f"Last error: {e}"
            ) from e

    # Should not reach here, but safety net
    raise PlanningError(
        f"Planning failed after {MAX_PLAN_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


async def generate_plan_sync_wrapper(
    maeos: MAEOS,
    goal: str,
    task_id: str = "",
    context: dict | None = None,
) -> TaskPlan:
    """
    Synchronous wrapper for generate_plan.

    Use in contexts where async/await is not available.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await generate_plan(
        maeos=maeos,
        goal=goal,
        task_id=task_id,
        context=context,
    )


def validate_plan(plan: TaskPlan) -> list[str]:
    """
    Validate a parsed TaskPlan, returning a list of warning strings.

    Unlike the parser's validate_plan (which is low-level), this wraps it
    for external consumers. Same semantics — never raises, returns list of
    warnings or empty list.
    """
    return parser_validate_plan(plan)
