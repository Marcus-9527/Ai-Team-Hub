"""brain/chat_memory.py — 每轮聊天记忆提炼 (Task 7, min version)

聊天每轮队友回复完成后，best-effort 用一次 LLM 调用把这轮对话的
关键事实/偏好/决策压缩成 1-2 句，存入 Brain 表。

隔离：每条记忆必带 workspace_id + teammate_id + channel_id（焊死）。
失败不影响主消息流：整个动作在 asyncio.ensure_future 内 try/except。

Ponytail: 不加向量库/语义检索。一条记忆 = memory_items 表一行独立记录。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("brain.chat_memory")

_EXTRACT_PROMPT = """\
你是一个记忆提炼器。请从下面这段对话中，提取对用户偏好、事实性信息、关键决策有长期价值的内容。
只提取明确陈述的事实（例如"我叫XX""这个项目用React"），不要编造。
如果存在有价值的信息，压缩成一句中文（不超过 40 字）；如果没有值得长期记住的，只回复 [NONE]。
不要解释，不要加前缀。"""

_MAX_TOKENS = 120


async def _extract_summary(user_message: str, reply_text: str, api_key: str,
                           base_url: str | None, provider: str, model: str) -> str | None:
    """返回压缩摘要，或 None（无可记内容 / 失败）。"""
    try:
        from backend.services.ai_service import stream_ai_response
        conversation = f"用户：{user_message}\n队友：{reply_text}"
        chunks: list[str] = []
        async for chunk in stream_ai_response(
            system_prompt=_EXTRACT_PROMPT,
            messages=[{"role": "user", "content": conversation}],
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            max_tokens=_MAX_TOKENS,
        ):
            chunks.append(chunk)
        text = "".join(chunks).strip()
        if not text or text.upper() == "[NONE]":
            return None
        # 去前缀噪音
        text = text.lstrip("要点：").lstrip("摘要：").strip()
        return text[:200] or None
    except Exception as e:  # best-effort：提炼失败绝不抛出
        logger.warning("[ChatMemory] extract failed (skipped): %s", e)
        return None


async def _do_store(teammate: dict, user_message: str, reply_text: str,
                   channel_id: str) -> None:
    """实际提炼 + 落库。整段 best-effort。"""
    try:
        # 延迟 import 避免 brain ↔ runtime 循环依赖
        from backend.services.brain.fragment_store import (
            get_brain_fragment_store,
            BrainFragment,
            BrainFragmentType,
        )
        from backend.services.runtime.teammate_runner import resolve_api_key
        from backend.services.ai_service import stream_ai_response

        api_key, base_url, provider, fallback_model = await resolve_api_key(teammate)
        if not api_key:
            return  # 无 key 不记，静默跳过
        model = fallback_model or teammate.get("model_name", "openrouter/auto")

        summary = await _extract_summary(user_message, reply_text, api_key,
                                          base_url, provider, model)
        if not summary:
            return

        ws_id = teammate.get("workspace_id", "")
        tm_id = teammate.get("id", "")
        frag = BrainFragment(
            teammate_id=tm_id,
            workspace_id=ws_id,  # 焊死隔离
            channel_id=channel_id,  # 关联频道
            fragment_type=BrainFragmentType.CHAT_MEMORY,
            content=summary,
            confidence=0.8,
            source="chat_memory",
        )
        store = get_brain_fragment_store()
        await store.store(frag)
        logger.info("[ChatMemory] stored for teammate %s (ws %s, ch %s): %s",
                    tm_id[:8], ws_id[:8] if ws_id else "-", channel_id[:8] if channel_id else "-", summary[:40])
    except Exception as e:
        logger.warning("[ChatMemory] store failed (skipped, msg still delivered): %s", e)


def extract_and_store(teammate: dict, user_message: str, reply_text: str,
                      channel_id: str) -> None:
    """触发异步提炼。fire-and-forget，绝不阻塞调用方。"""
    if not reply_text or not reply_text.strip():
        return
    asyncio.ensure_future(_do_store(teammate, user_message, reply_text, channel_id))
