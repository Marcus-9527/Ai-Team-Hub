"""DAGValidator — validates a DAGDefinition for structural correctness.

Checks:
  - Cycle detection
  - Empty nodes (no description)
  - Nodes without required_skills
  - Illegal dependencies (dangling refs, self-refs)
"""

from __future__ import annotations

from backend.services.dag.core import DAGDefinition, detect_cycle


class ValidationResult:
    """Result of DAG validation."""

    __slots__ = ("valid", "errors")

    def __init__(self, valid: bool = True, errors: list[str] | None = None):
        self.valid = valid
        self.errors = errors or []

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": list(self.errors)}


class DAGValidator:
    """Validate a DAGDefinition for planning correctness."""

    def validate(self, dag: DAGDefinition) -> ValidationResult:
        """Run all validation checks. Returns result with error list."""
        errors: list[str] = []

        # 1. Cycle detection
        if detect_cycle(dag):
            errors.append("DAG contains a cycle")

        # 2. Empty nodes
        for node in dag.nodes.values():
            if not node.description.strip():
                errors.append(f"Node '{node.id}' has empty description")

        # 3. Missing required_skills
        for node in dag.nodes.values():
            if not node.required_skills:
                errors.append(
                    f"Node '{node.id}' ('{node.description[:40]}') "
                    f"has no required_skills"
                )

        # 4. Illegal deps
        for node in dag.nodes.values():
            for dep_id in node.deps:
                if dep_id == node.id:
                    errors.append(
                        f"Node '{node.id}' depends on itself"
                    )
                elif dep_id not in dag.nodes:
                    errors.append(
                        f"Node '{node.id}' depends on non-existent "
                        f"node '{dep_id}'"
                    )

        return ValidationResult(valid=len(errors) == 0, errors=errors)
