"""
orchestrator_observability.py — [V1.0 STUB]

Previous content removed during v1.0 Architecture Consolidation.
This stub preserves the public API so that maeos.py, traces.py, and
v1_observability.py continue to import without error.

The original Observability class was a simple in-memory request logger.
All callers that used .replay() got empty results (method never existed).
"""

import logging
from typing import Optional

logger = logging.getLogger("orchestrator.observability")


class Observability:
    """Minimal stub — preserves import compatibility only."""
    _logs: list = []

    def log_request(self, channel_id: str = "", response_time_ms: int = 0,
                    response_length: int = 0, error: str = ""):
        pass

    def list_logs(self, limit: int = 20) -> list:
        return []

    def get_logs_for_channel(self, channel_id: str) -> list:
        return []


_OBSERVABILITY_INSTANCE: Optional[Observability] = None


def get_observability() -> Observability:
    """Stub — always returns a no-op instance."""
    global _OBSERVABILITY_INSTANCE
    if _OBSERVABILITY_INSTANCE is None:
        _OBSERVABILITY_INSTANCE = Observability()
    return _OBSERVABILITY_INSTANCE
