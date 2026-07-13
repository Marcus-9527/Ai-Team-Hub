"""DAGBuilder — converts a TaskPlan into a DAGDefinition.

Maps TaskStepProposal fields to DAGNode:
  - objective      → description
  - teammate_id    → mapped to required_skills via SkillRegistry
  - depends_on     → deps (order numbers → node IDs)
  - requires_approval → require_approval
"""

from __future__ import annotations

from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.task.task_planner_schema import TaskPlan


class DAGBuilder:
    """Build a DAGDefinition from a validated TaskPlan."""

    # ponytail: simple type→skills mapping, extend with SkillRegistry query
    # when teammate profiles are needed at build time.
    TYPE_SKILL_MAP: dict[str, list[str]] = {
        "coding":       ["python", "javascript", "coding", "debugging"],
        "writing":      ["writing", "editing", "content"],
        "analysis":     ["data_analysis", "research", "analytics"],
        "design":       ["ui_design", "ux", "frontend", "visual_design"],
        "devops":       ["devops", "ci_cd", "infrastructure"],
        "general":      [],
        # Common aliases
        "frontend":     ["ui_design", "frontend", "javascript"],
        "backend":      ["python", "backend", "api"],
        "fullstack":    ["javascript", "python", "frontend", "backend"],
        "python":       ["python", "coding"],
        "javascript":   ["javascript", "coding", "frontend"],
    }

    def build(self, plan: TaskPlan) -> DAGDefinition:
        """Convert a TaskPlan to a DAGDefinition.

        Two-pass:
          1. Create all DAGNodes, build order→node_id mapping.
          2. Wire dependency edges using order numbers.
        """
        dag = DAGDefinition(name=plan.title)
        order_to_id: dict[int, str] = {}

        # Pass 1 — create nodes
        for step in plan.steps:
            skills = self._resolve_skills(step.teammate_id)
            node = DAGNode(
                description=step.objective,
                required_skills=skills,
                require_approval=step.requires_approval,
            )
            dag.add_node(node)
            order_to_id[step.order] = node.id

        # Pass 2 — wire deps
        for step in plan.steps:
            node = dag.nodes[order_to_id[step.order]]
            node.deps = [order_to_id[d] for d in step.depends_on
                         if d in order_to_id]

        return dag

    def _resolve_skills(self, teammate_id: str) -> list[str]:
        """Map a teammate_id or task_type hint to required skills."""
        if not teammate_id:
            return []
        tid = teammate_id.strip().lower()
        # 1. Exact match in TYPE_SKILL_MAP
        if tid in self.TYPE_SKILL_MAP:
            return list(self.TYPE_SKILL_MAP[tid])
        # 2. Partial match (key is substring of tid or vice versa)
        for key, skills in self.TYPE_SKILL_MAP.items():
            if key in tid or tid in key:
                return list(skills)
        # 3. Try SkillRegistry (may return empty list for unknown types)
        try:
            from backend.services.teammate_intelligence import SkillRegistry
            registry_skills = SkillRegistry.get_skills(tid)
            if registry_skills:
                return list(registry_skills)
        except Exception:
            pass
        # 4. Fallback: use teammate_id as a skill tag (at least passes validation)
        return [tid]
