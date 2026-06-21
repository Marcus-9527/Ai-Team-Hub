"""
runtime/flow_control.py — Flow Control Hard Rules Enforcement

Enforces at runtime:
  1. No agent can decide next step
  2. No prompt-based flow control allowed
  3. No conversational chaining allowed
  4. Only Scheduler can change state

This is the enforcement layer. It inspects agent outputs and
rejects any that try to control flow.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("runtime.flow_control")


# ── Flow Control Violations ──

class ViolationType:
    NEXT_STEP_DECISION = "NEXT_STEP_DECISION"
    PROMPT_FLOW_CONTROL = "PROMPT_FLOW_CONTROL"
    CONVERSATIONAL_CHAINING = "CONVERSATIONAL_CHAINING"
    STATE_MANIPULATION = "STATE_MANIPULATION"


# ── Patterns that indicate flow control attempts ──

FLOW_CONTROL_PATTERNS = [
    # Agent trying to decide next step
    r"next[_\s]?action\s*[:=]",
    r"next[_\s]?step\s*[:=]",
    r"should[_\s]?proceed",
    r"recommend[_\s]?next",
    r"suggest[_\s]?next",
    r"continue[_\s]?to",
    r"move[_\s]?to[_\s]?next",
    r"transition[_\s]?to",
    # Prompt-based flow control
    r"if\s+.*then\s+(proceed|continue|skip|abort)",
    r"based\s+on\s+.*(proceed|continue|skip)",
    r"depending\s+on\s+.*(proceed|continue)",
    # Conversational chaining
    r"handoff[_\s]?to",
    r"pass[_\s]?to\s+\w+",
    r"delegate[_\s]?to",
    r"forward[_\s]?to",
    r"send[_\s]?to\s+\w+",
    # State manipulation
    r"set[_\s]?state\s*[:=]",
    r"change[_\s]?state",
    r"update[_\s]?state",
    r"switch[_\s]?to",
    # JSON-key variants (with quotes and spaces)
    r"\"next_action\"",
    r"\"next_step\"",
    r"\"set_state\"",
    r"\"change_state\"",
    r"\"update_state\"",
    r"\"handoff_to\"",
    r"\"handoff\"",
    r"\"delegate_to\"",
    r"\"forward_to\"",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FLOW_CONTROL_PATTERNS]


# ── Enforcement Result ──

@dataclass
class FlowControlResult:
    enforced: bool           # True if output is clean
    violation_type: str      # empty if clean
    violation_detail: str    # empty if clean
    action: str              # "allow" | "reject" | "sanitize"


# ── Flow Control Enforcer ──

class FlowControlEnforcer:
    """
    Enforces flow control hard rules on agent outputs.

    Usage:
        enforcer = FlowControlEnforcer()
        result = enforcer.check(agent_id="planner", output='{"next_action": "execute"}')
        if not result.enforced:
            # reject output, trigger retry
    """

    def __init__(self, mode: str = "strict"):
        """
        mode: "strict" = reject any flow control attempt
              "log" = log but allow
        """
        self.mode = mode
        self._violation_count: dict[str, int] = {}

    def check(self, agent_id: str, output: str) -> FlowControlResult:
        """
        Check agent output for flow control violations.

        Returns FlowControlResult.
        If enforced=False, the output must be rejected or the agent retried.
        """
        if not output:
            return FlowControlResult(enforced=True, violation_type="", violation_detail="", action="allow")

        # Check against all patterns
        for pattern in _COMPILED_PATTERNS:
            match = pattern.search(output)
            if match:
                violation = self._classify_violation(match.group())
                self._violation_count[agent_id] = self._violation_count.get(agent_id, 0) + 1

                logger.warning(
                    f"[FLOW_CONTROL] Violation by {agent_id}: {violation} "
                    f"pattern='{match.group()}' mode={self.mode}"
                )

                if self.mode == "strict":
                    return FlowControlResult(
                        enforced=False,
                        violation_type=violation,
                        violation_detail=f"Pattern matched: '{match.group()}'",
                        action="reject",
                    )
                else:
                    return FlowControlResult(
                        enforced=True,
                        violation_type=violation,
                        violation_detail=f"Pattern matched: '{match.group()}'",
                        action="log",
                    )

        return FlowControlResult(enforced=True, violation_type="", violation_detail="", action="allow")

    def _classify_violation(self, matched_text: str) -> str:
        """Classify the type of flow control violation."""
        text_lower = matched_text.lower().strip('"')
        if any(kw in text_lower for kw in ["next_action", "next_step", "should_proceed", "recommend_next", "suggest_next"]):
            return ViolationType.NEXT_STEP_DECISION
        if any(kw in text_lower for kw in ["handoff", "pass_to", "delegate", "forward", "send_to"]):
            return ViolationType.CONVERSATIONAL_CHAINING
        if any(kw in text_lower for kw in ["set_state", "change_state", "update_state", "switch_to"]):
            return ViolationType.STATE_MANIPULATION
        return ViolationType.PROMPT_FLOW_CONTROL

    @property
    def violation_counts(self) -> dict[str, int]:
        return dict(self._violation_count)

    def reset(self):
        self._violation_count.clear()


def create_flow_control_enforcer(mode: str = "strict") -> FlowControlEnforcer:
    return FlowControlEnforcer(mode=mode)
