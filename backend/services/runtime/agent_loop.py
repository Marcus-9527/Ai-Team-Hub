"""
统一 Agent Loop 内核。

替代的旧代码：
  runtime/agent.py::_parse_tool_calls()  —— 正则解析 <TOOL>...</TOOL>，整段删除
  runtime/agent.py::run_engineer_workflow() 里"拼文本→正则解析→execute_tool"那段
      —— 改成调 AgentLoop.run()，见文件末尾的迁移示例

设计目标（对应验收标准）：
  - chat 和 task 只保留各自的"上下文构建"，构建完统一交给 AgentLoop.run()
  - 工具调用走 provider 原生 tool_calls，不再解析 <TOOL>...</TOOL> 文本
  - 加一个新工具，两条路径同时可用（因为工具执行走同一个 ToolExecutor）

TODO — 需要你接入真实项目的三处（已标注）：
  1. LLMClient.complete()：接你现有的底层模型调用（大概率是包了 Anthropic
     messages API 的某个函数）。它现在应该已经返回 tool_use 类型的 content
     block 了（Anthropic 原生支持 tool_calls，`<TOOL>` 文本协议是当初绕开
     原生能力的历史遗留），这里只是把返回值规整成 LLMResponse 的形状。
  2. ToolExecutor.execute()：直接包一层你现有的 execute_tool()。
  3. on_text_chunk 目前是"每轮调完一次性传整段文本"，跟你现在
     stream_ai_response 的逐 token 流式不是一回事——如果要保留真正的流式
     打字机效果，需要 LLMClient.complete() 内部一边流式接收一边转发 delta，
     这个我建议单独一轮再做，不要和"协议迁移"这一步混在一起。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

logger = logging.getLogger(__name__)


# ---------- 数据结构 ----------

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class AgentLoopResult:
    final_text: str
    messages: list[dict[str, Any]]
    tool_calls_made: list[ToolCall] = field(default_factory=list)
    turns: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str  # "end_turn" / "tool_use" / ...


# ---------- Provider / 工具执行 适配层（Protocol，需要你写实现） ----------

# ── 流式事件类型 ──

EVENT_TEXT_DELTA = "text_delta"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_FINAL = "final"


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LLMResponse: ...


class ToolExecutor(Protocol):
    async def execute(
        self, tool_call: ToolCall, *, workspace_id: str, subject: str
    ) -> ToolResult: ...


# ---------- 核心循环：chat 和 task 共用这一个类 ----------

MAX_TURNS_DEFAULT = 12


class AgentLoop:
    def __init__(
        self,
        llm_client: LLMClient,
        tool_executor: ToolExecutor,
        *,
        max_turns: int = MAX_TURNS_DEFAULT,
    ):
        self.llm_client = llm_client
        self.tool_executor = tool_executor
        self.max_turns = max_turns

    async def run(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        workspace_id: str,
        subject: str,
        on_text_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_call: Optional[Callable[[ToolCall, ToolResult], Awaitable[None]]] = None,
        on_event: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> AgentLoopResult:
        history = list(messages)
        all_tool_calls: list[ToolCall] = []
        turn = 0

        async def _emit(event_type: str, payload: dict) -> None:
            if on_event:
                await on_event(event_type, payload)

        while True:
            turn += 1
            if turn > self.max_turns:
                logger.warning(
                    "[AgentLoop] hit max_turns=%s subject=%s, forcing stop",
                    self.max_turns, subject,
                )
                return AgentLoopResult(
                    final_text="(达到最大轮数，强制结束)",
                    messages=history,
                    tool_calls_made=all_tool_calls,
                    turns=turn,
                )

            response = await self.llm_client.complete(
                system_prompt=system_prompt, messages=history, tools=tools,
                on_chunk=on_text_chunk,
            )

            await _emit(EVENT_TEXT_DELTA, {"text": response.text, "turn": turn})

            # 无 tool_calls → 视为 final message，这是唯一的循环出口
            if not response.tool_calls:
                history.append({"role": "assistant", "content": response.text})
                await _emit(EVENT_FINAL, {"text": response.text, "turns": turn})
                return AgentLoopResult(
                    final_text=response.text,
                    messages=history,
                    tool_calls_made=all_tool_calls,
                    turns=turn,
                )

            history.append({
                "role": "assistant",
                "content": response.text,
                "tool_calls": response.tool_calls,
            })

            for tool_call in response.tool_calls:
                all_tool_calls.append(tool_call)
                try:
                    result = await self.tool_executor.execute(
                        tool_call, workspace_id=workspace_id, subject=subject
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[AgentLoop] tool failed: %s", tool_call.name)
                    result = ToolResult(
                        tool_call_id=tool_call.id,
                        content=f"工具执行失败: {exc}",
                        is_error=True,
                    )

                if on_tool_call:
                    await on_tool_call(tool_call, result)

                await _emit(EVENT_TOOL_CALL, {
                    "call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "result": result.content,
                    "is_error": result.is_error,
                })

                history.append({
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                    "is_error": result.is_error,
                })
            # 循环回到顶部，带着新结果再调一轮模型


# =====================================================================
# 迁移示例：run_engineer_workflow() 从 <TOOL> 文本协议改成 AgentLoop
# =====================================================================
#
# 旧代码（要删的）：
#
#     chunks = []
#     async for chunk in stream_ai_response(...):
#         chunks.append(chunk)
#     text = "".join(chunks).strip()
#     calls = _parse_tool_calls(text)
#     if not calls:
#         break
#     for call in calls:
#         res = await execute_tool(call, workspace_id, subject=role)
#
# 新代码：
#
#     agent_loop = AgentLoop(llm_client=your_llm_client, tool_executor=your_tool_executor)
#     result = await agent_loop.run(
#         system_prompt=system_prompt,
#         messages=context_messages,       # 沿用你现有"上下文构建"的产物
#         tools=available_tools_schema,     # provider 原生 tool schema，不是 <TOOL> 提示词
#         workspace_id=workspace_id,
#         subject=role,
#     )
#     final_report = result.final_text
#
# chat 路径（TeammateRunner.stream_teammate）同理，区别只在于
# 传入的 on_text_chunk 回调要接到 SSE 广播，而不是像 task 路径一样忽略它。
