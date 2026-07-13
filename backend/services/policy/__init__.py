"""Policy Service — checks execution policies for DAG nodes.

Evaluates teammate permission, tool permission, and task-type restrictions.
Policies are supplied per-evaluation (from DB TaskPolicyModel or overrides).
"""
import logging

logger = logging.getLogger("policy")


class PolicyResult:
    """Outcome of a single policy check."""

    __slots__ = ("allowed", "reason")

    def __init__(self, allowed: bool = True, reason: str = ""):
        self.allowed = allowed
        self.reason = reason

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason}

    def __bool__(self) -> bool:
        return self.allowed


# ── Individual checks ──


def check_teammate_permission(teammate: str,
                              allowed_teammates: list[str]) -> PolicyResult:
    """Check if a teammate is allowed to execute."""
    if not allowed_teammates:
        return PolicyResult(True)
    if teammate in allowed_teammates:
        return PolicyResult(True)
    return PolicyResult(
        False, f"Teammate '{teammate}' not in allowed list"
    )


def check_tool_permission(tool: str, allowed_tools: list[str]) -> PolicyResult:
    """Check if a tool is allowed."""
    if not allowed_tools:
        return PolicyResult(True)
    if tool in allowed_tools:
        return PolicyResult(True)
    return PolicyResult(False, f"Tool '{tool}' not in allowed list")


def check_task_type(task_type: str,
                    allowed_types: list[str]) -> PolicyResult:
    """Check if a task type / strategy is allowed."""
    if not allowed_types:
        return PolicyResult(True)
    if task_type in allowed_types:
        return PolicyResult(True)
    return PolicyResult(False, f"Task type '{task_type}' not in allowed list")


# ── Aggregate service ──


class PolicyService:
    """Aggregate policy evaluations for a DAG execution context."""

    def evaluate_node(
        self,
        *,
        teammate: str = "",
        strategy: str = "linear",
        allowed_teammates: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        allowed_task_types: list[str] | None = None,
    ) -> PolicyResult:
        """Run all relevant policy checks for a node."""
        # Teammate permission
        if teammate:
            result = check_teammate_permission(
                teammate, allowed_teammates or [])
            if not result.allowed:
                return result

        # Task type restriction (from strategy)
        result = check_task_type(strategy, allowed_task_types or [])
        if not result.allowed:
            return result

        return PolicyResult(True)


# ── Singleton ──

_policy_service: PolicyService | None = None


def get_policy_service() -> PolicyService:
    global _policy_service
    if _policy_service is None:
        _policy_service = PolicyService()
    return _policy_service


def reset_policy_service() -> None:
    global _policy_service
    _policy_service = None
