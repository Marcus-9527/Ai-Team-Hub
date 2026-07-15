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
    # ponytail: register tool_runtime functions so the gateway isn't a skeleton.
    # The engineer workflow calls tool_runtime.execute_tool() directly;
    # this makes get_tool_gateway().execute() work for future consumers.
    from backend.services.runtime import tool_runtime

    def _wrap(name: str):
        async def fn(**kwargs):
            ws_id = kwargs.pop("workspace_id", "default")
            return await tool_runtime.execute_tool(
                {"tool": name, "args": kwargs}, ws_id,
            )
        return fn

    for _t in ("file_read", "file_write", "shell_exec", "code_exec"):
        _gateway.register(_t, _wrap(_t))
