"""
cache_prefix_builder.py — Fixed-prefix message builder for prompt caching.

Builds a stable 9-message structure for DeepSeek prefix caching.
"""

from typing import Optional

# Fixed summary block (padded to ~1024 tokens for cache stability)
FIXED_SUMMARY_BLOCK = """[SYSTEM CONTEXT]
You are an AI assistant in a team collaboration platform.
Follow the user's instructions carefully.
Be concise and helpful.

[CONVERSATION RULES]
- Reply in the same language as the user
- Be direct and concise
- Do not repeat the user's question
- Do not start with "Sure!" or "Of course!"

[TEAM CONTEXT]
This is a multi-teammate team platform where different AI teammates
have different roles and expertise."""

# Dummy padding messages (for cache warming)
_PADDING = {
    4: [
        {"role": "user", "content": "[PREVIOUS_TURN_1]"},
        {"role": "assistant", "content": "[RESPONSE_1]"},
        {"role": "user", "content": "[PREVIOUS_TURN_2]"},
        {"role": "assistant", "content": "[RESPONSE_2]"},
    ],
}


def build_fixed_prefix(
    system_prompt: str,
    recent_turns: list[dict],
    current_content: str,
) -> list[dict]:
    """
    Build a fixed-prefix message list for prompt caching.

    Returns 9 messages total (stable structure for cache hit).
    """
    messages = []

    # 1. System prompt (cache target)
    messages.append({"role": "system", "content": system_prompt})

    # 2. Fixed summary block
    messages.append({"role": "user", "content": FIXED_SUMMARY_BLOCK})
    messages.append({"role": "assistant", "content": "Understood."})

    # 3. Recent turns (up to 3 turns = 6 messages)
    for turn in recent_turns[-3:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if content:
            # If content is a list (vision format), extract text blocks for prefix stability
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text_content = "\n".join(text_parts)
                if text_content.strip():
                    messages.append({"role": role, "content": text_content[:500]})
            else:
                messages.append({"role": role, "content": content[:500]})

    # Pad to ensure stable structure
    while len(messages) < 8:
        messages.append({"role": "user", "content": ""})
        if len(messages) < 8:
            messages.append({"role": "assistant", "content": ""})

    # 9. Current input (may be str or vision list for multimodal)
    messages.append({"role": "user", "content": current_content})

    return messages[:9]


def extract_recent_turns(messages: list, k: int = 3) -> list[dict]:
    """Extract recent k turns from message list."""
    if not messages:
        return []
    # Each turn = user + assistant pair
    turns = []
    for m in messages:
        if isinstance(m, dict):
            turns.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        else:
            turns.append({"role": getattr(m, "role", "user"), "content": getattr(m, "content", "")})
    return turns[-k * 2:]
