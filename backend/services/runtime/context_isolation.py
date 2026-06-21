"""
runtime/context_isolation.py — Context Isolation Layer (Anti-Leak)

Ensures:
  - No agent receives global runtime state
  - Only minimal required input is passed
  - No cross-agent memory leakage
  - Input is frozen (immutable snapshot) before passing to agent

Each agent gets exactly the fields it needs, nothing more.
"""

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("runtime.context_isolation")


# ── Agent Input Contracts ──

# Each agent declares exactly which input fields it needs.
# The isolation layer strips everything else.

AGENT_INPUT_CONTRACTS: dict[str, list[str]] = {
    "planner": ["task"],
    "executor": ["plan", "original_task"],
    "reviewer": ["result", "original_task"],
}


# ── Isolated Context ──

@dataclass(frozen=True)
class IsolatedContext:
    """
    Immutable, minimal context passed to an agent.
    Frozen dataclass — cannot be modified after creation.
    """
    agent_id: str
    state: str
    data: tuple  # frozen dict as tuple of items

    def to_dict(self) -> dict:
        return dict(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return dict(self.data).get(key, default)


# ── Context Isolation Layer ──

class ContextIsolation:
    """
    Strips global state and passes only minimal required input to agents.

    Usage:
        isolation = ContextIsolation()
        isolated = isolation.isolate(
            agent_id="planner",
            state="PLAN",
            global_context={"task": "...", "api_key": "...", "retry_count": 2, ...},
        )
        # isolated only contains {"task": "..."}
    """

    def isolate(
        self,
        agent_id: str,
        state: str,
        global_context: dict,
    ) -> IsolatedContext:
        """
        Create isolated context for an agent.

        1. Look up the agent's input contract
        2. Extract only the declared fields
        3. Deep-copy to prevent mutation
        4. Return frozen IsolatedContext
        """
        contract = AGENT_INPUT_CONTRACTS.get(agent_id, [])
        if not contract:
            logger.warning(f"[ISOLATION] No contract for agent '{agent_id}', passing empty context")
            return IsolatedContext(agent_id=agent_id, state=state, data=())

        isolated_data = {}
        for key in contract:
            if key in global_context:
                # Deep copy to prevent agent from mutating global state
                isolated_data[key] = copy.deepcopy(global_context[key])
            else:
                logger.warning(f"[ISOLATION] Required field '{key}' missing for agent '{agent_id}'")

        # Log what was stripped
        stripped_keys = set(global_context.keys()) - set(contract) - {"api_key", "password", "secret", "token"}
        if stripped_keys:
            logger.debug(f"[ISOLATION] Stripped keys for {agent_id}: {stripped_keys}")

        # Freeze as tuple of items (immutable)
        frozen_data = tuple(sorted(isolated_data.items()))

        return IsolatedContext(
            agent_id=agent_id,
            state=state,
            data=frozen_data,
        )

    def validate_no_leak(self, agent_output: Any, agent_id: str) -> bool:
        """
        Validate that agent output doesn't contain leaked global state.
        Checks for sensitive keys in output.
        """
        sensitive_keys = {"api_key", "password", "secret", "token", "authorization", "base_url"}

        output_str = str(agent_output).lower()
        for key in sensitive_keys:
            if key in output_str:
                logger.error(f"[ISOLATION] Potential leak: agent '{agent_id}' output contains '{key}'")
                return False
        return True


# ── Convenience function ──

def create_isolation_layer() -> ContextIsolation:
    return ContextIsolation()
