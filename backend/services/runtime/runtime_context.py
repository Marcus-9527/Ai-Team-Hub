"""runtime_context.py — TeammateRuntimeContext (Phase 4)

Bundles teammate identity, model, prompt, tool permission, and workspace scope
into a single dataclass used by ExecutionRuntime._run_task().

Reduces ad-hoc dict field extraction across executor.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("runtime.context")


@dataclass
class TeammateRuntimeContext:
    """Unified execution context for a single teammate invocation.

    Created once at the start of _run_task() and passed through to the
    workflow function (engineer/reviewer/chat), avoiding repeated field
    extraction from a loose dict.
    """

    # ── Identity ──
    teammate_id: str = ""
    name: str = ""
    role: str = ""            # engineer | reviewer | techlead | etc.

    # ── Model ──
    model_provider: str = ""
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""

    # ── Prompt ──
    system_prompt: str = "You are a helpful AI assistant."

    # ── Workspace ──
    workspace_id: str = ""

    # ── Memory scope (for future filtering; not consumed yet) ──
    memory_scope: str = "teammate"

    @classmethod
    def from_teammate(
        cls,
        teammate: dict,
        workspace_id: str = "",
        api_key: str = "",
        base_url: str = "",
    ) -> TeammateRuntimeContext:
        """Factory: build context from the dict returned by _load_teammate()."""
        return cls(
            teammate_id=teammate.get("id", ""),
            name=teammate.get("name", ""),
            role=teammate.get("role", ""),
            model_provider=teammate.get("model_provider", ""),
            model_name=teammate.get("model_name", ""),
            api_key=api_key or teammate.get("api_key", ""),
            base_url=base_url or teammate.get("base_url", ""),
            system_prompt=teammate.get("system_prompt", ""),
            workspace_id=workspace_id,
        )

    @property
    def is_loaded(self) -> bool:
        return bool(self.teammate_id and self.name)
