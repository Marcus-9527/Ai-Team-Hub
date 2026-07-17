"""runtime.py — Teammate Runtime loop.

Orchestrates the full autonomous cycle for a single teammate:
    load identity → plan → execute → reflect → write memory → decide → loop

Delegates to existing services; no duplicated runtime logic.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from backend.services.runtime.executor import _load_teammate
from backend.teammate_runtime.planner import call_planner
from backend.teammate_runtime.executor import call_executor
from backend.teammate_runtime.reflection import call_reflection
from backend.teammate_runtime.memory_writer import save_decision, save_execution

logger = logging.getLogger("teammate_runtime")

MAX_ROUNDS = 5


class TeammateRuntimeError(Exception):
    pass


class TeammateResult:
    """Result of a full teammate autonomous run."""

    def __init__(self, *, teammate_id: str, goal: str, status: str,
                 rounds: int, summary: str = "", error: str = ""):
        self.teammate_id = teammate_id
        self.goal = goal
        self.status = status  # "COMPLETED" | "FAILED" | "STOPPED"
        self.rounds = rounds
        self.summary = summary
        self.error = error


class TeammateRuntime:
    """Single-teammate autonomous execution loop.

    One runner per teammate; not thread-safe (teammate-level serialisation).
    """

    def __init__(self, max_rounds: int = MAX_ROUNDS):
        self.max_rounds = max_rounds

    async def run(self, teammate_id: str, goal: str,
                  workspace_id: str = "") -> TeammateResult:
        """Execute a full goal-driven autonomous loop."""
        start_ts = time.time()

        # 1. Load identity
        teammate = await _load_teammate(teammate_id)
        if not teammate:
            return TeammateResult(
                teammate_id=teammate_id, goal=goal, status="FAILED",
                rounds=0, error=f"Teammate {teammate_id} not found",
            )

        wid = workspace_id or f"anon_{teammate_id}"
        summary = ""
        actions_taken: list[str] = []

        for rnd in range(1, self.max_rounds + 1):
            logger.info("[TMR] round %d/%d — %s", rnd, self.max_rounds, goal[:60])

            # 2. Plan next action
            plan = await call_planner(
                teammate=teammate, goal=goal,
                context={"round": rnd, "actions_taken": actions_taken},
            )
            if not plan or not plan.get("action"):
                logger.info("[TMR] planner returned no action — stop")
                break

            # 3. Execute
            exec_result = await call_executor(
                teammate=teammate, plan=plan,
                workspace_id=wid,
            )
            action_label = plan.get("action", "unknown")
            actions_taken.append(action_label)

            # 4. Reflect
            reflection = await call_reflection(
                teammate_id=teammate_id,
                plan=plan, exec_result=exec_result,
            )

            # 5. Save memory (action + result + decision only)
            await save_execution(
                teammate_id=teammate_id,
                action=action_label,
                result=exec_result,
                workspace_id=wid,
            )
            decision_summary = reflection.get("decision", "")
            if decision_summary:
                await save_decision(
                    teammate_id=teammate_id,
                    summary=decision_summary,
                    source_action=action_label,
                    workspace_id=wid,
                )

            # 6. Decide continue / stop
            if reflection.get("should_stop", False):
                summary = reflection.get("summary", exec_result.get("summary", ""))
                elapsed = time.time() - start_ts
                logger.info("[TMR] completed in %d rounds (%.1fs)", rnd, elapsed)
                return TeammateResult(
                    teammate_id=teammate_id, goal=goal,
                    status="COMPLETED", rounds=rnd, summary=summary,
                )

        # Exhausted max_rounds
        elapsed = time.time() - start_ts
        logger.info("[TMR] stopped after %d rounds (%.1fs)", self.max_rounds, elapsed)
        return TeammateResult(
            teammate_id=teammate_id, goal=goal,
            status="STOPPED", rounds=self.max_rounds, summary=summary,
        )


async def run_teammate_goal(teammate_id: str, goal: str,
                            workspace_id: str = "",
                            max_rounds: int = MAX_ROUNDS) -> TeammateResult:
    """Convenience: one-shot teammate autonomous run."""
    runner = TeammateRuntime(max_rounds=max_rounds)
    return await runner.run(teammate_id, goal, workspace_id)
