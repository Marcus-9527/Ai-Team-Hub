"""
runtime/trace.py — Execution Trace System (Observability)

Structured JSON logging for every execution step.
Captures: state transition, input snapshot, output snapshot,
validation result, retry count, latency, failure classification.

Output: structured JSON lines (one per event) + aggregate report.
"""

import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from enum import Enum

logger = logging.getLogger("runtime.trace")


# ── Trace Event Types ──

class TraceEventType(str, Enum):
    STATE_TRANSITION = "STATE_TRANSITION"
    AGENT_DISPATCH = "AGENT_DISPATCH"
    AGENT_RESULT = "AGENT_RESULT"
    VALIDATION_RESULT = "VALIDATION_RESULT"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILURE_CLASSIFIED = "FAILURE_CLASSIFIED"
    CONTEXT_ISOLATED = "CONTEXT_ISOLATED"
    FLOW_CONTROL_ENFORCED = "FLOW_CONTROL_ENFORCED"
    WORKFLOW_COMPLETE = "WORKFLOW_COMPLETE"
    ERROR = "ERROR"


# ── Trace Event ──

@dataclass
class TraceEvent:
    """Single structured trace event."""
    event_type: str
    trace_id: str
    task_id: str
    timestamp: float = 0.0
    state: str = ""
    agent_id: str = ""
    attempt: int = 0
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_json(self) -> str:
        return json.dumps({
            "event_type": self.event_type,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "state": self.state,
            "agent_id": self.agent_id,
            "attempt": self.attempt,
            "data": self.data,
        }, ensure_ascii=False, default=str)


# ── Trace Logger ──

class TraceLogger:
    """
    Structured execution trace logger.

    Usage:
        trace = TraceLogger(trace_id="abc123", task_id="task456")
        trace.log_state_transition("PLAN", "EXECUTE")
        trace.log_agent_dispatch("planner", input_snapshot={"task": "..."})
        trace.log_agent_result("planner", output_snapshot={"result": "..."}, latency_ms=1200)
        trace.log_validation({"is_valid": True, "reason": "ok"})
        report = trace.build_report()
    """

    def __init__(self, trace_id: str, task_id: str):
        self.trace_id = trace_id
        self.task_id = task_id
        self._events: list[TraceEvent] = []
        self._start_time = time.time()

    def _emit(self, event_type: str, state: str = "", agent_id: str = "",
              attempt: int = 0, data: dict = None) -> TraceEvent:
        """Emit a structured trace event."""
        event = TraceEvent(
            event_type=event_type,
            trace_id=self.trace_id,
            task_id=self.task_id,
            state=state,
            agent_id=agent_id,
            attempt=attempt,
            data=data or {},
        )
        self._events.append(event)
        # Also log as JSON line
        logger.info(f"[TRACE] {event.to_json()}")
        return event

    def log_state_transition(self, from_state: str, to_state: str, reason: str = "") -> TraceEvent:
        return self._emit(
            TraceEventType.STATE_TRANSITION,
            state=to_state,
            data={"from": from_state, "to": to_state, "reason": reason},
        )

    def log_agent_dispatch(self, agent_id: str, state: str, input_snapshot: dict,
                           attempt: int = 1) -> TraceEvent:
        return self._emit(
            TraceEventType.AGENT_DISPATCH,
            state=state,
            agent_id=agent_id,
            attempt=attempt,
            data={"input": _safe_snapshot(input_snapshot)},
        )

    def log_agent_result(self, agent_id: str, state: str, output_snapshot: dict,
                         latency_ms: int, attempt: int = 1) -> TraceEvent:
        return self._emit(
            TraceEventType.AGENT_RESULT,
            state=state,
            agent_id=agent_id,
            attempt=attempt,
            data={
                "output": _safe_snapshot(output_snapshot),
                "latency_ms": latency_ms,
            },
        )

    def log_validation(self, agent_id: str, state: str, validation_result: dict,
                       attempt: int = 1) -> TraceEvent:
        return self._emit(
            TraceEventType.VALIDATION_RESULT,
            state=state,
            agent_id=agent_id,
            attempt=attempt,
            data={"validation": validation_result},
        )

    def log_retry_scheduled(self, agent_id: str, state: str, attempt: int,
                            delay_ms: int, reason: str) -> TraceEvent:
        return self._emit(
            TraceEventType.RETRY_SCHEDULED,
            state=state,
            agent_id=agent_id,
            attempt=attempt,
            data={"delay_ms": delay_ms, "reason": reason},
        )

    def log_failure_classified(self, agent_id: str, state: str, failure_type: str,
                               error: str, action: str) -> TraceEvent:
        return self._emit(
            TraceEventType.FAILURE_CLASSIFIED,
            state=state,
            agent_id=agent_id,
            data={"failure_type": failure_type, "error": error[:200], "action": action},
        )

    def log_context_isolated(self, agent_id: str, state: str,
                             input_keys: list[str]) -> TraceEvent:
        return self._emit(
            TraceEventType.CONTEXT_ISOLATED,
            state=state,
            agent_id=agent_id,
            data={"input_keys": input_keys},
        )

    def log_flow_control(self, agent_id: str, state: str, rule: str,
                         enforced: bool) -> TraceEvent:
        return self._emit(
            TraceEventType.FLOW_CONTROL_ENFORCED,
            state=state,
            agent_id=agent_id,
            data={"rule": rule, "enforced": enforced},
        )

    def log_workflow_complete(self, final_state: str, total_latency_ms: int,
                              total_retries: int, result_length: int) -> TraceEvent:
        return self._emit(
            TraceEventType.WORKFLOW_COMPLETE,
            state=final_state,
            data={
                "total_latency_ms": total_latency_ms,
                "total_retries": total_retries,
                "result_length": result_length,
            },
        )

    def log_error(self, state: str, error: str, agent_id: str = "") -> TraceEvent:
        return self._emit(
            TraceEventType.ERROR,
            state=state,
            agent_id=agent_id,
            data={"error": error[:500]},
        )

    def build_report(self) -> dict:
        """Build aggregate trace report."""
        total_latency = sum(
            e.data.get("latency_ms", 0) for e in self._events
            if e.event_type == TraceEventType.AGENT_RESULT
        )
        total_retries = sum(
            1 for e in self._events
            if e.event_type == TraceEventType.RETRY_SCHEDULED
        )
        failures = [
            e for e in self._events
            if e.event_type == TraceEventType.FAILURE_CLASSIFIED
        ]

        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "total_events": len(self._events),
            "total_latency_ms": total_latency,
            "total_retries": total_retries,
            "failures": [e.data for e in failures],
            "events": [json.loads(e.to_json()) for e in self._events],
            "wall_time_ms": int((time.time() - self._start_time) * 1000),
        }


def _safe_snapshot(data: dict, max_value_len: int = 500) -> dict:
    """Create a safe snapshot — truncate long values, skip sensitive keys."""
    safe = {}
    skip_keys = {"api_key", "password", "secret", "token", "authorization"}
    for k, v in data.items():
        if k.lower() in skip_keys:
            safe[k] = "***REDACTED***"
        elif isinstance(v, str) and len(v) > max_value_len:
            safe[k] = v[:max_value_len] + "...[truncated]"
        else:
            safe[k] = v
    return safe
