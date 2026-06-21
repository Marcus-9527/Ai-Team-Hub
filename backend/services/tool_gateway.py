"""
tool_gateway.py — Tool execution gateway.
"""

import logging
from typing import Optional

logger = logging.getLogger("tool_gateway")


class ToolGateway:
    """Tool execution gateway (stub for FSM orchestrator)."""

    def __init__(self):
        self._tools: dict[str, callable] = {}

    def register(self, name: str, fn: callable) -> None:
        self._tools[name] = fn

    async def execute(self, name: str, **kwargs):
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return await self._tools[name](**kwargs)


_gateway: Optional[ToolGateway] = None


def get_tool_gateway() -> ToolGateway:
    global _gateway
    if _gateway is None:
        _gateway = ToolGateway()
    return _gateway


def init_tool_gateway() -> None:
    global _gateway
    _gateway = ToolGateway()
