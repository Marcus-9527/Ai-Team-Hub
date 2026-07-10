"""
memory_summarizer.py — Conversation turn summarizer (stub).

Exposes SUMMARY_INTERVAL and process_conversation_turn for the memory layer.
"""

import logging
from typing import Optional

logger = logging.getLogger("memory_summarizer")

SUMMARY_INTERVAL = 10  # Summarize every N turns


async def process_conversation_turn(
    channel_id: str,
    teammate_id: str,
    messages: list[dict],
    msg_count: int,
    provider: str,
    model: str,
    api_key: str = None,
    base_url: str = None,
) -> None:
    """Process conversation turn and update summary if needed."""
    if msg_count % SUMMARY_INTERVAL != 0:
        return
    # Summary logic would go here
    logger.debug(f"Summary check: {msg_count} messages")
