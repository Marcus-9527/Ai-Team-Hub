"""
coordinator.py — FROZEN: replaced by orchestrator_fsm.py

⛔ FROZEN — This module is permanently disabled. It cannot be instantiated.
    All orchestration must go through orchestrator_fsm.py (FSM v4).
    This file is kept for reference only. DO NOT call get_coordinator().
"""

import logging
import uuid
from typing import Optional


def _frozen():
    raise RuntimeError(
        "coordinator.py is FROZEN and cannot be used. "
        "Use orchestrator_fsm.py (FSM v4) instead."
    )


# Freeze the module: any import triggers immediate failure
_frozen()
from backend.services.agent_context import (
    AgentContext, AgentOutput, AgentRole,
    CoordinatorRequest, CoordinatorResponse,
)
from backend.services.agent_registry import get_agent_context, get_agents_for_intent, get_namespace
from backend.services.context_builder_v2 import build_agent_context, format_prompt_for_llm
from backend.services.ai_service import stream_ai_response
from backend.services.cache_key import compute_cache_key

logger = logging.getLogger("coordinator")


class Coordinator:
    """Legacy coordinator (kept for backward compatibility)."""

    def __init__(self):
        self.task_counter = 0

    def _next_task_id(self) -> str:
        self.task_counter += 1
        return f"task_{self.task_counter:06d}"

    def classify_intent(self, user_input: str) -> str:
        input_lower = user_input.lower()
        if any(kw in input_lower for kw in ["代码", "code", "编程", "函数", "class", "debug", "修复"]):
            return "code"
        if any(kw in input_lower for kw in ["分析", "analyze", "数据", "趋势", "统计"]):
            return "analysis"
        if any(kw in input_lower for kw in ["推理", "reasoning", "为什么", "原因", "解释"]):
            return "reasoning"
        if any(kw in input_lower for kw in ["评估", "比较", "哪个更好", "judge", "rank"]):
            return "judge"
        return "analysis"

    async def process(self, user_input: str, intent: str = None) -> CoordinatorResponse:
        import asyncio
        task_id = self._next_task_id()
        if not intent:
            intent = self.classify_intent(user_input)
        agent_ids = get_agents_for_intent(intent)
        tasks = [self._dispatch_agent(aid, user_input, task_id) for aid in agent_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        agent_outputs: list[AgentOutput] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                agent_outputs.append(AgentOutput(agent_id=agent_ids[i], result=f"Error: {result}", confidence=0.0))
            elif result:
                agent_outputs.append(result)
        final_result = self._merge_outputs(agent_outputs, intent)
        return CoordinatorResponse(
            task_id=task_id, agent_outputs=agent_outputs, final_result=final_result,
            merged=True, metadata={"intent": intent, "agents_used": agent_ids, "agent_count": len(agent_outputs)},
        )

    async def _dispatch_agent(self, agent_id: str, user_input: str, task_id: str) -> Optional[AgentOutput]:
        import asyncio
        max_retries = 3
        retry_delay = 2
        from backend.services.coordinator import AGENT_PROVIDER, AGENT_MODEL
        for attempt in range(max_retries):
            try:
                context = build_agent_context(agent_id, user_input)
                if not context:
                    return None
                prompt = format_prompt_for_llm(context)
                agent_ctx = get_agent_context(agent_id)
                ns = get_namespace(agent_id)
                from backend.services.cache_prefix_builder import FIXED_SUMMARY_BLOCK, _PADDING
                dummy_window = _PADDING[4]
                agent_messages = [{"role": "user", "content": FIXED_SUMMARY_BLOCK}]
                agent_messages.extend(dummy_window)
                agent_messages.append({"role": "user", "content": prompt})
                api_key = await self._get_api_key()
                if not api_key:
                    return AgentOutput(agent_id=agent_id, result="Error: No API key", confidence=0.0)
                provider = AGENT_PROVIDER.get(agent_id, "deepseek")
                model = AGENT_MODEL.get(agent_id, "deepseek-chat")
                full_response = ""
                async for chunk in stream_ai_response(
                    system_prompt=context["system"], messages=agent_messages,
                    provider=provider, model=model, api_key=api_key,
                ):
                    full_response += chunk
                ns.write_history("user", user_input)
                ns.write_history("assistant", full_response)
                ns.write_episodic("user", user_input)
                ns.write_episodic("assistant", full_response)
                output = AgentOutput(
                    agent_id=agent_id, result=full_response,
                    confidence=self._estimate_confidence(full_response),
                    tokens_used=len(prompt) + len(full_response),
                )
                return output
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return AgentOutput(agent_id=agent_id, result=f"Error: {str(e)}", confidence=0.0)
        return AgentOutput(agent_id=agent_id, result="Error: Max retries exceeded", confidence=0.0)

    def _merge_outputs(self, outputs: list[AgentOutput], intent: str) -> str:
        if not outputs:
            return "No output generated."
        if len(outputs) == 1:
            return outputs[0].result
        sorted_outputs = sorted(outputs, key=lambda o: o.confidence, reverse=True)
        best = sorted_outputs[0]
        if len(sorted_outputs) > 1 and abs(best.confidence - sorted_outputs[1].confidence) < 0.1:
            return self._combine_outputs(sorted_outputs[:2])
        return best.result

    def _combine_outputs(self, outputs: list[AgentOutput]) -> str:
        parts = []
        seen = set()
        for o in outputs:
            key = o.result[:100]
            if key not in seen:
                seen.add(key)
                parts.append(f"[{o.agent_id}]: {o.result}")
        return "\n\n".join(parts)

    def _estimate_confidence(self, response: str) -> float:
        if not response:
            return 0.0
        score = 0.5
        if len(response) > 100: score += 0.1
        if len(response) > 300: score += 0.1
        for word in ["因此", "所以", "结论", "总结", "建议", "应该", "需要"]:
            if word in response: score += 0.05
        for word in ["可能", "也许", "不确定", "不知道", "无法", "?"]:
            if word in response: score -= 0.05
        return max(0.0, min(1.0, score))

    async def _get_api_key(self) -> str:
        if hasattr(self, "_cached_api_key") and self._cached_api_key:
            return self._cached_api_key
        try:
            from backend.database import async_session
            from sqlalchemy import select
            from backend.models import APIKey
            async with async_session() as sess:
                result = await sess.execute(select(APIKey).where(APIKey.provider == "deepseek").limit(1))
                key_obj = result.scalar_one_or_none()
                if key_obj and key_obj.api_key:
                    self._cached_api_key = key_obj.api_key
                    return key_obj.api_key
        except Exception:
            pass
        return ""


AGENT_PROVIDER = {"agent_a": "deepseek", "agent_b": "deepseek", "agent_c": "deepseek", "agent_j": "deepseek"}
AGENT_MODEL = {"agent_a": "deepseek-chat", "agent_b": "deepseek-chat", "agent_c": "deepseek-chat", "agent_j": "deepseek-chat"}

_coordinator: Optional[Coordinator] = None


def get_coordinator() -> Coordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = Coordinator()
    return _coordinator
