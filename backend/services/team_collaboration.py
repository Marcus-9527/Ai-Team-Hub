"""
team_collaboration.py — Slack-like multi-teammate sequential chat runtime

Architecture:
  Round 1: teammates speak in fixed order

Flow:
  messages.py → OrganizationRuntime.handle_input()
                  → TeammateRunner.stream_teammate() per teammate
                  → AgentLoop → LLM
"""
import logging
from typing import AsyncGenerator, Optional

from backend.services.runtime.teammate_runner import (
    stream_teammate,
    detect_role,
)

logger = logging.getLogger("team_collaboration")


# ── Chain Order ──

ROLE_CHAIN_ORDER = [
    "engineer",
    "analyst",
    "designer",
    "product_manager",
    "engineer_lead",
]


def _sort_by_role_order(teammates: list[dict]) -> list[dict]:
    """Sort teammates by role order for consistent sequential turns."""
    def sort_key(tm):
        role = detect_role(tm)
        try:
            return ROLE_CHAIN_ORDER.index(role)
        except ValueError:
            return len(ROLE_CHAIN_ORDER)
    return sorted(teammates, key=sort_key)


# ── Public API ──

async def generate_team_response(
    teammates: list[dict],
    user_message: str,
    channel_id: str = "",
    shared_attachment_context: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    """
    Generate a multi-teammate team response with SSE streaming.

    For each teammate (in role order):
      1. Stream their response via TeammateRunner
      2. Collect the full text for anti-redundancy context

    Yields SSE events: teammate_message, teammate_end, system_message
    """
    # Sort teammates into role order
    ordered_teammates = _sort_by_role_order(teammates)
    history_texts: list[str] = []

    for turn_idx, tm in enumerate(ordered_teammates):
        phase = f"collaboration_round_1"
        name = tm.get("name", f"Teammate {turn_idx + 1}")

        # Emit teammate_start (system message with role context)
        role = detect_role(tm)
        yield _emit_system_message(f"**{name}** ({role}):")

        # Stream their response
        collected_text = ""
        async for event in stream_teammate(
            teammate=tm,
            user_message=user_message,
            history_texts=history_texts,
            turn_idx=turn_idx,
            phase=phase,
            shared_attachment_context=shared_attachment_context,
            channel_id=channel_id,
        ):
            yield event
            # Extract content payload from SSE for history
            if event.startswith("data:") and not event.startswith("data: [DONE]"):
                try:
                    import json
                    evt = json.loads(event[5:].strip().rstrip("\n"))
                    if evt.get("type") == "teammate_message":
                        collected_text += evt.get("payload", {}).get("content", "")
                except Exception:
                    pass

        if collected_text.strip():
            history_texts.append(collected_text.strip())

    # Final DONE signal
    yield "data: [DONE]\n\n"


def emit_event(
    event_type: str,
    message_id: str,
    role: str = "",
    phase: str = "",
    payload: Optional[dict] = None,
    channel_id: str = "",
) -> str:
    """Format a teammate/collaboration event as an SSE `data: JSON\\n\\n` frame.

    Returns the raw SSE string (without HTTP framing) so it can be concatenated
    into a stream or parsed by the frontend SSE parser.
    """
    import json
    from datetime import datetime, timezone

    event = {
        "type": event_type,
        "message_id": message_id,
        "role": role,
        "phase": phase,
        "payload": payload or {},
        "channel_id": channel_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def _emit_system_message(text: str) -> str:
    """Emit a system_message SSE event."""
    import json
    from datetime import datetime, timezone
    event = {
        "type": "system_message",
        "payload": {"content": text},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
