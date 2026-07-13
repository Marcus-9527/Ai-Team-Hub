"""
runtime — Production Execution Runtime Package

Modules:
  executor.py           — Unified ExecutionRuntime (single execution chain)
  teammate_runner.py    — Single-teammate call + streaming
  agent.py              — Engineer workflow (real git workspace flow)
  reviewer.py           — Reviewer workflow (reads real git diff + runs tests)
  retry_policy.py       — Retry + failure classification + backoff
  trace.py              — Structured JSON trace logging
  execution_store.py    — Execution observability store (token/cost/SSE)
"""

from backend.services.runtime.retry_policy import RetryPolicy, RetryDecision, FailureType, BackoffStrategy
from backend.services.runtime.trace import TraceLogger, TraceEventType
from backend.services.runtime.executor import ExecutionRuntime, RuntimeTask, ExecStatus as RuntimeExecStatus
from backend.services.runtime.teammate_runner import (
    call_teammate,
    stream_teammate,
    resolve_api_key,
    detect_role,
    build_turn_prompt,
)
from backend.services.runtime.execution_store import (
    ExecutionRecord,
    ExecutionStore,
    MemoryExecutionStore,
    DBExecutionStore,
    get_execution_store,
    get_sse_broadcaster,
    SSEBroadcaster,
    estimate_cost_from_tokens,
)

__all__ = [
    # Retry
    "RetryPolicy", "RetryDecision", "FailureType", "BackoffStrategy",
    # Trace
    "TraceLogger", "TraceEventType",
    # Executor
    "ExecutionRuntime", "RuntimeTask",
    # Teammate
    "call_teammate", "stream_teammate", "resolve_api_key",
    "detect_role", "build_turn_prompt",
    # Execution Store
    "ExecutionRecord", "ExecutionStore", "get_execution_store",
    "get_sse_broadcaster", "SSEBroadcaster", "estimate_cost_from_tokens",
]
