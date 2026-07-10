"""
task_planner_schema.py — Planner data models.

Defines TaskPlan (Planner output) and TaskStepProposal (single step).
Uses dataclasses for type safety and serialization.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# TaskStepProposal — single step in a plan
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskStepProposal:
    """Planner's proposal for a single execution step."""

    order: int                       # execution order (1-based)
    teammate_id: str                 # recommended teammate for this step
    objective: str                   # step goal / instruction
    expected_output: str = ""        # description of expected output
    input_context_hint: str = ""     # context hint to inject

    # Dependency
    depends_on: list[int] = field(default_factory=list)  # order refs this step depends on

    # Risk & cost
    risk_level: str = "LOW"          # LOW / MEDIUM / HIGH
    estimated_cost: float = 0.0      # estimated cost in µ$
    estimated_tokens: int = 0        # estimated token consumption

    # Quality gate
    requires_approval: bool = False
    validation_criteria: str = ""

    # Planner metadata
    confidence: float = 0.0          # planner's confidence in this step (0.0–1.0)
    rationale: str = ""              # why this step exists

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TaskStepProposal:
        return cls(
            order=int(data.get("order", 0)),
            teammate_id=str(data.get("teammate_id", "")),
            objective=str(data.get("objective", "")),
            expected_output=str(data.get("expected_output", "")),
            input_context_hint=str(data.get("input_context_hint", "")),
            depends_on=[int(i) for i in data.get("depends_on", [])],
            risk_level=str(data.get("risk_level", "LOW")),
            estimated_cost=float(data.get("estimated_cost", 0.0)),
            estimated_tokens=int(data.get("estimated_tokens", 0)),
            requires_approval=bool(data.get("requires_approval", False)),
            validation_criteria=str(data.get("validation_criteria", "")),
            confidence=float(data.get("confidence", 0.0)),
            rationale=str(data.get("rationale", "")),
        )


# ═══════════════════════════════════════════════════════════════
# TaskPlan — complete planner output
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskPlan:
    """Complete plan output by the Planner Teammate."""

    task_id: str                      # associated Task.id
    title: str                        # plan title
    description: str                  # plan description / summary
    steps: list[TaskStepProposal]     # ordered step proposals

    # Overall metadata
    confidence: float = 0.0           # overall planner confidence (0.0–1.0)
    rationale: str = ""               # overall planning rationale

    # Risk & cost
    estimated_total_cost: float = 0.0  # estimated total cost in µ$
    risk_level: str = "LOW"            # LOW / MEDIUM / HIGH

    # Timing
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "confidence": self.confidence,
            "rationale": self.rationale,
            "estimated_total_cost": self.estimated_total_cost,
            "risk_level": self.risk_level,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskPlan:
        steps_data = data.get("steps", [])
        steps = [TaskStepProposal.from_dict(s) for s in steps_data]
        return cls(
            task_id=str(data.get("task_id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            steps=steps,
            confidence=float(data.get("confidence", 0.0)),
            rationale=str(data.get("rationale", "")),
            estimated_total_cost=float(data.get("estimated_total_cost", 0.0)),
            risk_level=str(data.get("risk_level", "LOW")),
            created_at=float(data.get("created_at", 0.0)),
        )


# ═══════════════════════════════════════════════════════════════
# TaskPlannerInput — input structure fed to the Planner LLM
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskPlannerInput:
    """Structured input passed to the Planner Teammate via MAEOS."""

    goal: str
    context: dict = field(default_factory=dict)

    def to_prompt(self) -> str:
        """Serialize to a prompt for the Planner LLM."""
        parts = [f"# User Goal\n\n{self.goal}"]
        ctx = self.context
        if ctx.get("global_rules"):
            rules = "\n".join(f"- {r}" for r in ctx["global_rules"])
            parts.append(f"## Global Rules\n\n{rules}")
        if ctx.get("workspace_decisions"):
            decs = "\n".join(
                f"- {d.get('decision', '')}: {d.get('reasoning', '')}"
                for d in ctx["workspace_decisions"]
            )
            parts.append(f"## Workspace Decisions\n\n{decs}")
        if ctx.get("channel_history"):
            history = "\n".join(
                f"[{m.get('role', 'user')}]: {m.get('content', '')}"
                for m in ctx["channel_history"][-20:]
            )
            parts.append(f"## Conversation History\n\n{history}")
        return "\n\n".join(parts)
