"""OrganizationAction enum — shared between runtime and action_runtime."""

from __future__ import annotations

from enum import Enum


class OrganizationAction(str, Enum):
    """High-level action types in the organization run lifecycle."""
    RESPOND = "respond"
    DELEGATE = "delegate"
    TOOL_CALL = "tool_call"
    PLAN = "plan"
    REVIEW = "review"
    EXECUTE = "execute"
    VERIFY = "verify"
    COMPLETE = "complete"


# ── Shortcut: all action values for quick lookups ──
ALL_ACTIONS = {a.value for a in OrganizationAction}
