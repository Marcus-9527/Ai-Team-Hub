"""OrganizationPlanRuntime — lifecycle tracker for OrganizationPlan.

Phase 17: in-memory plan lifecycle + event emission.
Ponytail: no ORM, no new tables, no auto-execution.
"""

from __future__ import annotations

from typing import Optional

from backend.services.organization.plan import OrganizationPlan, PlanStep


class PlanStepState:
    """Mutable state for one plan step."""

    def __init__(self, step: PlanStep):
        self.step = step
        self.status: str = "pending"
        self.error: Optional[str] = None


class OrganizationPlanRuntime:
    """Lightweight plan lifecycle manager.

    Holds plan + step states in memory.
    Emits events via existing SessionHooks (no new ORM).
    """

    def __init__(self, hooks: "SessionHooks"):
        self._hooks = hooks
        self._plan: Optional[OrganizationPlan] = None
        self._steps: list[PlanStepState] = []

    # ── read ──

    @property
    def plan(self) -> Optional[OrganizationPlan]:
        return self._plan

    @property
    def status(self) -> str:
        """Aggregate status from step states."""
        if not self._steps:
            return "pending"
        statuses = {s.status for s in self._steps}
        if "running" in statuses:
            return "running"
        if "failed" in statuses:
            return "failed"
        if all(s.status == "completed" for s in self._steps):
            return "completed"
        # At least one step completed or running → in progress
        if any(s.status != "pending" for s in self._steps):
            return "running"
        return "pending"

    @property
    def steps(self) -> list[PlanStepState]:
        return list(self._steps)

    # ── lifecycle ──

    def create(self, plan: OrganizationPlan, *, trigger_id: str = "") -> None:
        """Create in-memory plan state."""
        self._plan = plan
        self._steps = [PlanStepState(s) for s in plan.steps]

    async def start_step(self, idx: int, *, trigger_id: str = "") -> None:
        """Transition step idx → running. Emits plan.step.started."""
        state = self._resolve(idx)
        state.status = "running"
        await self._hooks.emit_event(
            trigger_id,
            event_type="plan.step.started",
            payload={
                "step_index": idx,
                "step_type": state.step.step_type,
                "action": state.step.action.value,
                "role": state.step.role,
            },
        )

    async def complete_step(self, idx: int, *, trigger_id: str = "") -> None:
        """Transition step idx → completed. Emits plan.step.completed."""
        state = self._resolve(idx)
        state.status = "completed"
        await self._hooks.emit_event(
            trigger_id,
            event_type="plan.step.completed",
            payload={
                "step_index": idx,
                "step_type": state.step.step_type,
                "action": state.step.action.value,
            },
        )

    async def fail_step(self, idx: int, error: str, *, trigger_id: str = "") -> None:
        """Transition step idx → failed. Emits plan.step.failed."""
        state = self._resolve(idx)
        state.status = "failed"
        state.error = error
        await self._hooks.emit_event(
            trigger_id,
            event_type="plan.step.failed",
            payload={
                "step_index": idx,
                "step_type": state.step.step_type,
                "action": state.step.action.value,
                "error": error,
            },
        )

    def _resolve(self, idx: int) -> PlanStepState:
        if not self._steps:
            raise RuntimeError("No plan created")
        if idx < 0 or idx >= len(self._steps):
            raise IndexError(
                f"Step index {idx} out of range (0-{len(self._steps) - 1})"
            )
        return self._steps[idx]
