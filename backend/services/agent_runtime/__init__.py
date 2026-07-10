"""agent_runtime — Hermes Long Running Agent Runtime

A self-contained runtime that drives a task through a 4-stage pipeline:

  1. 🤖 ChatGPT Commander  — interpret the request, decompose into a plan
  2. 🧠 Hermes Planner     — build an ordered execution plan
  3. ⚙️  Executor          — run the steps
  4. 📄 File Changes       — collect / diff the resulting file changes

Features:
  - In-memory task queue (FIFO)
  - Single Worker loop that pulls from the queue and drives stages
  - Pause / Resume / Cancel control (state stored per run)
  - Observability integration via backend.services.observability.get_observability()
"""

from backend.services.agent_runtime.runtime import (
    AgentRuntime,
    get_runtime,
)
from backend.services.agent_runtime.stages import (
    STAGE_COMMANDER,
    STAGE_PLANNER,
    STAGE_EXECUTOR,
    STAGE_FILE_CHANGES,
    STAGE_ORDER,
)

__all__ = [
    "AgentRuntime",
    "get_runtime",
    "STAGE_COMMANDER",
    "STAGE_PLANNER",
    "STAGE_EXECUTOR",
    "STAGE_FILE_CHANGES",
    "STAGE_ORDER",
]
