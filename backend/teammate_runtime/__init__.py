"""teammate_runtime — Teammate Runtime v1.

Standalone, single-teammate autonomous execution loop.
Every module delegates to existing services (ExecutionRuntime, PlanningEngine,
MemoryService, ReflectionService) — no duplicated logic.

Usage:
    result = await run_teammate_goal(teammate_id="tm-xxx", goal="Add login API")
"""

from .runtime import run_teammate_goal, TeammateRuntime, TeammateResult

__all__ = ["run_teammate_goal", "TeammateRuntime", "TeammateResult"]
