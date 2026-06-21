"""
observability.py — Trace recording and replay.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("observability")


class Observability:
    """Trace recording and replay service."""

    def __init__(self):
        self._traces: dict[str, list[dict]] = {}
        self._states: dict[str, dict] = {}

    def record(
        self,
        trace_id: str,
        task_id: str,
        step: str,
        agent: str,
        input_data: dict,
        output_data: dict,
        latency_ms: int = 0,
        tokens: int = 0,
    ) -> None:
        """Record a trace event."""
        if trace_id not in self._traces:
            self._traces[trace_id] = []
        self._traces[trace_id].append({
            "trace_id": trace_id,
            "task_id": task_id,
            "step": step,
            "agent": agent,
            "input_data": input_data,
            "output_data": output_data,
            "latency_ms": latency_ms,
            "tokens": tokens,
            "timestamp": time.time(),
        })

    def get_trace(self, trace_id: str) -> list[dict]:
        """Get trace events."""
        return self._traces.get(trace_id, [])

    def list_traces(self, limit: int = 20) -> list[dict]:
        """List recent traces."""
        return [
            {"trace_id": tid, "event_count": len(events)}
            for tid, events in list(self._traces.items())[-limit:]
        ]

    def replay(self, trace_id: str) -> dict:
        """Replay a trace."""
        events = self._traces.get(trace_id, [])
        if not events:
            return {"error": "Trace not found"}
        return {"trace_id": trace_id, "events": events}

    def analyze_failures(self, trace_id: str) -> dict:
        """Analyze failures in a trace."""
        events = self._traces.get(trace_id, [])
        if not events:
            return {"error": "Trace not found"}
        failures = [e for e in events if e.get("output_data", {}).get("status") == "error"]
        return {"trace_id": trace_id, "failures": failures}

    def save_state(self, task_id: str, trace_id: str, state: str, context: dict) -> None:
        """Save task state."""
        self._states[task_id] = {
            "task_id": task_id,
            "trace_id": trace_id,
            "state": state,
            "context": context,
        }

    def get_state(self, task_id: str) -> Optional[dict]:
        """Get task state."""
        return self._states.get(task_id)


_obs: Optional[Observability] = None


def get_observability() -> Observability:
    global _obs
    if _obs is None:
        _obs = Observability()
    return _obs
