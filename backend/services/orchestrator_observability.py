"""
orchestrator_observability.py — Simple request logging.

FSM trace recording has been removed. This module provides basic request-level
logging for monitoring and debugging.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("orchestrator.observability")


@dataclass
class RequestLog:
    """Simple log entry for a single request."""
    timestamp: float
    channel_id: str
    response_time_ms: int = 0
    response_length: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "channel_id": self.channel_id,
            "response_time_ms": self.response_time_ms,
            "response_length": self.response_length,
            "error": self.error,
        }


class Observability:
    """Simple in-memory request log store."""
    
    def __init__(self):
        self._logs: list[RequestLog] = []

    def log_request(self, channel_id: str, response_time_ms: int = 0,
                    response_length: int = 0, error: str = ""):
        entry = RequestLog(
            timestamp=time.time(),
            channel_id=channel_id,
            response_time_ms=response_time_ms,
            response_length=response_length,
            error=error,
        )
        self._logs.append(entry)
        if error:
            logger.warning(f"Request failed: channel={channel_id[:8]}... error={error}")
        else:
            logger.info(f"Request ok: channel={channel_id[:8]}... time={response_time_ms}ms len={response_length}")

    def list_logs(self, limit: int = 20) -> list[dict]:
        return [entry.to_dict() for entry in self._logs[-limit:]]

    def get_logs_for_channel(self, channel_id: str) -> list[dict]:
        return [e.to_dict() for e in self._logs if e.channel_id == channel_id]


# ── Singleton ──

_OBSERVABILITY_INSTANCE: Optional[Observability] = None


def get_observability() -> Observability:
    """Get or create the singleton observability instance."""
    global _OBSERVABILITY_INSTANCE
    if _OBSERVABILITY_INSTANCE is None:
        _OBSERVABILITY_INSTANCE = Observability()
    return _OBSERVABILITY_INSTANCE
