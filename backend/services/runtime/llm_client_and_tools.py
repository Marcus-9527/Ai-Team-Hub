"""
AgentLoop 的三块拼图实现：
  1. TOOL_SCHEMAS —— 把 agent.py::_TOOL_INSTRUCTIONS 里的纯文本工具说明
     改写成 Anthropic API 的 tools=[{name, description, input_schema}] 格式
  2. AnthropicLLMClient / OpenAICompatLLMClient —— 实现 agent_loop.LLMClient
     协议，走"最懒方案"：不流式，裸调一次性 API，直接从 response 里拿
     tool_use block（Anthropic）或 message.tool_calls（OpenAI 兼容）
  3. ToolExecutorAdapter  + create_llm_client 工厂 —— 包一层现有
     tool_runtime.execute_tool() + resolve_api_key()
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional

import httpx

from backend.services.runtime.agent_loop import LLMClient, LLMResponse, ToolCall, ToolExecutor, ToolResult

logger = logging.getLogger(__name__)


# =====================================================================
# 1. 工具 Schema —— 替代 _TOOL_INSTRUCTIONS 纯文本
#    参数名已对照 tool_runtime.execute_tool() 实际分支验证：
#      file_read(path)       ✓  exact
#      file_write(path, content)  ✓  exact
#      shell_exec(command)   ✓  exact
#      code_exec(code, language, timeout)  ✓  language 有默认值，timeout 可选
# =====================================================================

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "file_read",
        "description": "读取工作区内指定路径的文件内容",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区内的相对文件路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_write",
        "description": "写入或覆盖工作区内指定路径的文件（完整内容覆盖写）",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区内的相对文件路径"},
                "content": {"type": "string", "description": "要写入的完整文件内容"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "shell_exec",
        "description": "在工作区沙箱内执行 shell 命令（支持 pytest、git、npm test 等限定列表）",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "code_exec",
        "description": "执行一段代码（python3/node/bash）并返回输出；30s 超时",
        "input_schema": {
            "type": "object",
            "properties": {
                "language": {"type": "string", "description": "代码语言：python/python3/node/nodejs/bash/sh"},
                "code": {"type": "string", "description": "要执行的代码内容"},
                "timeout": {"type": "number", "description": "超时秒数（默认 30）"},
            },
            "required": ["code"],
        },
    },
]


# =====================================================================
# 2. LLMClient 实现 —— 非流式裸调，不经过 stream_ai_response
# =====================================================================

class AnthropicLLMClient:
    """实现 agent_loop.LLMClient 协议，走 Anthropic Messages API 非流式调用。"""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": _to_anthropic_messages(messages),
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                t = block.get("text", "")
                text_parts.append(t)
                if on_chunk:
                    await on_chunk(t)
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(id=block["id"], name=block["name"], arguments=block.get("input", {}))
                )

        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=data.get("stop_reason", "end_turn"),
        )


class OpenAICompatLLMClient:
    """实现 agent_loop.LLMClient 协议，走 OpenAI 兼容 /chat/completions 非流式调用。"""

    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        # 确保 endpoint 是 /chat/completions
        base = base_url.rstrip("/")
        self.endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LLMResponse:
        oa_messages = [{"role": "system", "content": system_prompt}] + _to_openai_messages(messages)
        payload: dict[str, Any] = {"model": self.model, "messages": oa_messages}
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                for t in tools
            ]

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]
        text = message.get("content") or ""
        if on_chunk:
            await on_chunk(text)
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"] or "{}"),
                )
            )

        return LLMResponse(
            text=message.get("content") or "",
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason", "stop"),
        )


# =====================================================================
# 工厂：根据 provider 创建对应的 LLMClient
# =====================================================================

def create_llm_client(
    api_key: str, model: str, provider: str, base_url: str = "",
) -> LLMClient:
    """根据 provider 创建 LLMClient 实例。
    provider == "anthropic" → AnthropicLLMClient
    其余（openrouter/openai/opencode/google/...） → OpenAICompatLLMClient
    """
    if provider == "anthropic":
        return AnthropicLLMClient(api_key=api_key, model=model, base_url=base_url or "https://api.anthropic.com")
    return OpenAICompatLLMClient(api_key=api_key, model=model, base_url=base_url)


# =====================================================================
# StreamingLLMClient — 包装 stream_ai_response 为 LLMClient 协议
# =====================================================================

class StreamingLLMClient:
    """LLMClient 实现，底层走 stream_ai_response 流式调用。

    传给 on_chunk 的每个 chunk 都是 LLM 返回的文本 delta，
    非工程角色（analyst/designer/pm/…）的 SSE 聊天流即靠此实现逐 token 输出。
    """

    def __init__(self, api_key: str, model: str, provider: str, base_url: str = "",
                 max_tokens: int = 1024):
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.base_url = base_url
        self.max_tokens = max_tokens

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LLMResponse:
        from backend.services.ai_service import stream_ai_response

        chunks: list[str] = []
        async for chunk in stream_ai_response(
            system_prompt=system_prompt,
            messages=messages,
            provider=self.provider,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url or None,
            max_tokens=self.max_tokens,
        ):
            chunks.append(chunk)
            if on_chunk:
                await on_chunk(chunk)

        text = "".join(chunks)
        # 流式接口不返回 tool_calls（工具角色走单独的非流式客户端）
        return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn")


def create_streaming_llm_client(
    api_key: str, model: str, provider: str, base_url: str = "",
    max_tokens: int = 1024,
) -> StreamingLLMClient:
    """创建流式 LLMClient（底层走 stream_ai_response）。"""
    return StreamingLLMClient(
        api_key=api_key, model=model, provider=provider,
        base_url=base_url, max_tokens=max_tokens,
    )


# =====================================================================
# 消息格式转换
# =====================================================================

def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 AgentLoop history 转成 Anthropic Messages API 格式。
    tool 结果需转成 role=user / type=tool_result content block。
    """
    out = []
    for m in messages:
        if m["role"] == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                    "is_error": m.get("is_error", False),
                }],
            })
        else:
            out.append(m)
    return out


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 AgentLoop history 转成 OpenAI 兼容格式。"""
    out = []
    for m in messages:
        if m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append(m)
    return out


# =====================================================================
# 3. ToolExecutor 适配器 —— 包一层现有 execute_tool()
# =====================================================================

class ToolExecutorAdapter(ToolExecutor):
    """包装 tool_runtime.execute_tool() 为 AgentLoop 可用的 ToolExecutor 协议。

    execute_tool 返回形状:
        {"tool": str, "ok": bool, "output": Any, "error": str}
    ok=True 时 output 是实际结果（文件内容 / {path,bytes} / {command,stdout,...}）
    ok=False 时 error 是错误信息
    """

    async def execute(self, tool_call: ToolCall, *, workspace_id: str, subject: str) -> ToolResult:
        from backend.services.runtime.tool_runtime import execute_tool

        call_dict = {"tool": tool_call.name, "args": tool_call.arguments}
        try:
            raw = await execute_tool(call_dict, workspace_id, subject=subject)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ToolExecutorAdapter] execute_tool failed: %s", tool_call.name)
            return ToolResult(tool_call_id=tool_call.id, content=f"工具执行失败: {exc}", is_error=True)

        if not raw.get("ok"):
            return ToolResult(
                tool_call_id=tool_call.id,
                content=raw.get("error", "未知错误"),
                is_error=True,
            )

        output = raw.get("output")
        if isinstance(output, str):
            content = output
        else:
            content = json.dumps(output, ensure_ascii=False)
        return ToolResult(tool_call_id=tool_call.id, content=content, is_error=False)
