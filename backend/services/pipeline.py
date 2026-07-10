"""
pipeline.py — Simple single-pipeline LLM orchestration.

Replaces the multi-teammate team engine with a straightforward sequential pipeline:
  planner_step → executor_step → reviewer_step

No teammate-to-teammate communication, no FSM state machine, no shared state between requests.
All steps are internal — the public API is run_pipeline().
"""

import logging
import re
import json
from typing import Optional

from backend.services.ai_service import stream_ai_response
from backend.services.orchestrator_prompts import SYSTEM_PROMPT, PLANNER_PROMPT, REVIEWER_PROMPT

logger = logging.getLogger("pipeline")


def _parse_json(text: str) -> dict:
    """Best-effort JSON extraction from LLM output."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    bracket = re.search(r"\[.*\]|{.*?}", text, re.DOTALL)
    if bracket:
        try:
            return json.loads(bracket.group(0))
        except json.JSONDecodeError:
            pass
    return {"raw": text}


async def _call_llm(
    system_prompt: str,
    user_message: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = None,
    max_tokens: int = 4096,
) -> str:
    """Call LLM and collect all streamed chunks into a single string."""
    chunks = []
    async for chunk in stream_ai_response(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
    ):
        chunks.append(chunk)
    return "".join(chunks)


# ── Internal pipeline steps ──

async def planner_step(message: str, provider: str, model: str, api_key: str, base_url: str = None) -> str:
    """
    Analyze user intent and optionally rewrite the query for better results.
    Returns the (possibly rewritten) query.
    """
    try:
        result = await _call_llm(
            system_prompt=PLANNER_PROMPT,
            user_message=message,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=512,
        )
        data = _parse_json(result)
        # If the planner returns a rewritten query, use it; otherwise use original
        rewritten = data.get("rewritten_query", "").strip()
        intent = data.get("intent", "general")
        logger.info(f"Planner: intent={intent}, rewritten={bool(rewritten)}")
        return rewritten if rewritten else message
    except Exception as e:
        logger.warning(f"Planner step failed (using original message): {e}")
        return message


async def executor_step(message: str, context: str, provider: str, model: str, api_key: str, base_url: str = None) -> str:
    """
    Call LLM to generate the actual response.
    `context` is the planner's output (rewritten query or original message).
    """
    try:
        user_content = context if context else message
        result = await _call_llm(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_content,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=4096,
        )
        return result
    except Exception as e:
        logger.error(f"Executor step failed: {e}")
        raise


def reviewer_step(response: str) -> str:
    """
    Basic validation of the LLM response.
    Returns the response if valid, or an error message if validation fails.
    """
    # Length check
    if not response or len(response.strip()) < 2:
        logger.warning("Reviewer: response too short, rejecting")
        return "⚠️ The AI returned an empty or too-short response. Please try again."

    if len(response) > 50000:
        logger.warning("Reviewer: response too long, truncating")
        response = response[:50000] + "\n\n... [response truncated]"

    # Basic harmful content check (simple heuristic)
    harmful_patterns = [
        r"<script[^>]*>",
        r"javascript:",
        r"on\w+\s*=",
    ]
    for pattern in harmful_patterns:
        if re.search(pattern, response, re.IGNORECASE):
            logger.warning(f"Reviewer: detected potentially harmful pattern: {pattern}")
            # Don't reject, just sanitize by escaping
            response = response.replace("<", "&lt;").replace(">", "&gt;")
            break

    logger.info(f"Reviewer: passed (length={len(response)})")
    return response


# ── Public API ──

async def run_pipeline(
    channel_id: str,
    user_message: str,
    system_prompt: str = None,
    provider: str = "openrouter",
    model: str = "openrouter/auto",
    api_key: str = "",
    base_url: str = None,
) -> str:
    """
    Run the full pipeline for a user message.

    Steps:
      1. planner_step — analyze intent, optionally rewrite query
      2. executor_step — call LLM to generate response
      3. reviewer_step — basic validation

    Returns: AI response string.
    """
    logger.info(f"Pipeline start: channel={channel_id[:8]}... msg_len={len(user_message)}")

    # Step 1: Planner
    refined_message = await planner_step(
        message=user_message,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    # Step 2: Executor
    response = await executor_step(
        message=user_message,
        context=refined_message,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    # Step 3: Reviewer
    validated_response = reviewer_step(response)

    logger.info(f"Pipeline complete: channel={channel_id[:8]}... response_len={len(validated_response)}")
    return validated_response
