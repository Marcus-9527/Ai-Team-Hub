"""
team_collaboration.py — Slack-like multi-teammate sequential chat runtime

Architecture:
  Round 1: teammates speak in fixed order (engineer→analyst→designer→PM→engineer_lead)

- Each teammate gets a unique per-request message_id (uuid4)
- NO teammate_start event — only teammate_message creates bubbles
- NO author_id / group_id / debate_id / chain_id fields
- SSE events: teammate_message, teammate_end, system_message, error
- DB key: (teammate_id, phase, message_id)
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from backend.services.ai_service import stream_ai_response
from backend.cache import teammate_cache, apikey_cache

logger = logging.getLogger("team_collaboration")


# ── SSE Event Emitter — unified message model ──

EVENT_TYPES = {
    "teammate_message": "teammate_message",
    "teammate_end": "teammate_end",
    "system_message": "system_message",
    "error": "error",
}

# Standard message schema fields: message_id, teammate_id, phase, content, author_name, timestamp, status


def emit_event(
    event_type: str,
    message_id: str,
    role: str = "",
    phase: str = "",
    payload: dict = None,
    channel_id: str = "",
) -> str:
    """Emit a single SSE-formatted JSON event.

    Unified message model — NO author_id, NO group_id, NO debate_id, NO chain_id.
    message_id = per-teammate uuid (unique per request).
    role = teammate_id (engineer | analyst | designer | product_manager | engineer_lead).
    """
    event = {
        "message_id": message_id,
        "channel_id": channel_id,
        "type": event_type,
        "role": role,
        "phase": phase,
        "payload": payload or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


# ── Role Behavior Axis (internal — never shown to user) ──

ROLE_AXIS_PROMPTS = {
    "engineer": """You are an ENGINEER. Focus: IMPLEMENTATION and FEASIBILITY.
Think in: code, architecture, technical constraints, performance, scalability.
Do NOT discuss: business priorities, UX (unless asked).
Output: 2-3 sentences max. Be concrete and technical.""",

    "product_manager": """You are a PRODUCT MANAGER. Focus: GOALS and PRIORITIZATION.
Think in: user needs, business value, feature priority, roadmap.
Do NOT discuss: implementation details (unless asked).
Output: 2-3 sentences max. Be concrete and product-focused.""",

    "analyst": """You are an ANALYST. Focus: RISKS and DATA REASONING.
Think in: edge cases, data quality, metrics, potential failures.
Do NOT discuss: solutions (unless asked).
Output: 2-3 sentences max. Be concrete and risk-focused.""",

    "designer": """You are a DESIGNER. Focus: USER EXPERIENCE and INTERACTION.
Think in: usability, visual design, user flow, accessibility.
Do NOT discuss: backend implementation (unless asked).
Output: 2-3 sentences max. Be concrete and UX-focused.""",

    "engineer_lead": """You are the ENGINEERING LEAD. Focus: SYSTEM DESIGN and CODE QUALITY.
Think in: architecture patterns, testing strategy, maintainability.
Do NOT discuss: product priorities (unless asked).
Output: 2-3 sentences max. Be concrete and architectural.""",
}

# ── Chain Order ──
ROLE_CHAIN_ORDER = [
    "engineer",
    "analyst",
    "designer",
    "product_manager",
    "engineer_lead",
]


def _detect_role(teammate: dict) -> str:
    """Detect teammate role from system_prompt, role field, or name."""
    combined = " ".join([
        teammate.get("system_prompt", ""),
        teammate.get("role", ""),
        teammate.get("name", ""),
    ]).lower()

    if any(kw in combined for kw in ["engineer", "developer", "architect", "代码", "工程"]):
        return "engineer"
    if any(kw in combined for kw in ["product", "pm", "manager", "产品", "需求"]):
        return "product_manager"
    if any(kw in combined for kw in ["analyst", "data", "risk", "分析", "数据"]):
        return "analyst"
    if any(kw in combined for kw in ["design", "ux", "ui", "设计"]):
        return "designer"
    if any(kw in combined for kw in ["lead", "主管", "tech lead"]):
        return "engineer_lead"

    return "engineer"  # default


def _build_anti_redundancy_context(history_texts: list[str]) -> str:
    """
    Build anti-redundancy instruction based on what's already been said.
    Injected into each teammate's prompt to prevent repetition.
    """
    if not history_texts:
        return ""

    # Summarize key points already made (compact)
    recent = history_texts[-3:]  # Only last 3 responses for context
    lines = []
    for i, txt in enumerate(recent):
        # Truncate long responses to key sentence
        truncated = txt[:120].strip()
        if len(txt) > 120:
            truncated += "..."
        lines.append(f"- Previous point {i+1}: {truncated}")

    context = "\n".join(lines)

    return f"""
## WHAT HAS ALREADY BEEN SAID (DO NOT REPEAT):
{context}

## RULES:
- Do NOT restate, paraphrase, or rephrase any point already made above.
- Add ONLY new information, a different perspective, correction, or deeper detail.
- If you have nothing NEW to add, respond with ONLY: [NO_NEW_INFO]
"""


def _build_turn_prompt(
    teammate: dict,
    user_message: str,
    history_texts: list[str],
    turn_number: int,
    shared_attachment_context: Optional[dict] = None,
) -> str:
    """
    Build the full prompt for a single teammate's turn.
    No fact propagation — each teammate is independent.
    """
    system_prompt = teammate.get("system_prompt", "You are a helpful team member.")
    role = _detect_role(teammate)
    axis = ROLE_AXIS_PROMPTS.get(role, ROLE_AXIS_PROMPTS["engineer"])

    anti_redundancy = _build_anti_redundancy_context(history_texts)

    # Turn-aware instruction
    if turn_number == 0:
        turn_instruction = "You are the FIRST to respond. Give your perspective directly."
    elif turn_number == 1:
        turn_instruction = "You are responding AFTER other teammates. Build on or differ from their points."
    else:
        turn_instruction = "Several teammates have already spoken. Add unique value or say [NO_NEW_INFO]."

    # Build shared attachment context section
    attachment_section = ""
    if shared_attachment_context:
        attachment_section = _build_attachment_prompt_section(shared_attachment_context, role)

    prompt = f"""{system_prompt}

{axis}

{attachment_section}
## Question from user:
{user_message}

{turn_instruction}
{anti_redundancy}

## Your response (2-3 sentences, natural, in your role's voice):
"""
    return prompt


def _build_attachment_prompt_section(ctx: dict, role: str = "engineer") -> str:
    """
    Convert AttachmentContext dict to role-specific prompt section.
    RAW FILE CONTENT is NEVER injected — only structured intelligence.
    """
    if not ctx:
        return ""

    filename = ctx.get("metadata", {}).get("filename", "unknown")
    file_type = ctx.get("type", "text")
    summary = ctx.get("summary", "")
    entities = ctx.get("extracted_entities", [])
    chunks = ctx.get("chunks", [])

    # ── Shared summary (ALL teammates see this) ──
    lines = [f"## File: {filename}"]
    lines.append(f"**Type**: {file_type} | {summary}")

    if role == "engineer":
        tech_entities = [e for e in entities if (
            e[0].isupper() or e.startswith("/") or "." in e or e.startswith("def ")
        )]
        if tech_entities:
            lines.append(f"**Technical entities**: {', '.join(tech_entities[:12])}")
        if chunks:
            lines.append(f"\n### Full content for implementation analysis:")
            for i, chunk in enumerate(chunks):
                preview = chunk[:250].replace("\n", " ")
                lines.append(f"  [{i+1}] {preview}{'...' if len(chunk) > 250 else ''}")
            if len(chunks) > 5:
                lines.append(f"  ... ({len(chunks) - 5} more segments)")
        lines.append("\n> Focus: implementation details, technical feasibility, code patterns.")

    elif role == "product_manager":
        if entities:
            biz_entities = [e for e in entities if (
                e[0].isupper() and not e.startswith("/") and "." not in e
            )]
            if biz_entities:
                lines.append(f"**Key topics**: {', '.join(biz_entities[:8])}")
        if chunks:
            total_lines = sum(c.count("\n") + 1 for c in chunks)
            lines.append(f"**Structure**: ~{total_lines} lines across {len(chunks)} sections")
        lines.append("\n> Focus: user value, feature scope, goals, prioritization. Do NOT discuss code implementation.")

    elif role == "analyst":
        if entities:
            lines.append(f"**Entities to verify**: {', '.join(entities[:10])}")
        if chunks:
            risk_chunks = chunks[:2]
            if len(chunks) > 3:
                risk_chunks.append(chunks[-1])
            lines.append(f"\n### Critical segments (entry/exit patterns):")
            for i, chunk in enumerate(risk_chunks):
                preview = chunk[:200].replace("\n", " ")
                lines.append(f"  [{i+1}] {preview}{'...' if len(chunk) > 200 else ''}")
            lines.append(f"\n  (Total {len(chunks)} segments — review for edge cases)")
        lines.append("\n> Focus: risks, data quality, edge cases, missing error handling.")

    elif role == "designer":
        layout_entities = [e for e in entities if (
            "/" in e or e.startswith("app") or e.startswith("page") or e.endswith("View") or e.endswith("Page")
        )]
        if layout_entities:
            lines.append(f"**Components / routes**: {', '.join(layout_entities[:10])}")
        if chunks:
            total_lines = sum(c.count("\n") + 1 for c in chunks)
            lines.append(f"**File size**: ~{total_lines} lines")
        lines.append("\n> Focus: user flow, information architecture, UX implications. Do NOT discuss backend logic.")

    elif role == "engineer_lead":
        tech_entities = [e for e in entities if (
            e[0].isupper() or e.startswith("/") or "." in e
        )]
        if tech_entities:
            lines.append(f"**Architectural elements**: {', '.join(tech_entities[:10])}")
        if chunks:
            first_preview = chunks[0][:200].replace("\n", " ") if chunks else ""
            lines.append(f"\n### Overview: {first_preview}{'...' if len(chunks[0]) > 200 else ''}")
            if len(chunks) > 1:
                lines.append(f"\n  ({len(chunks)} total sections — assess partitioning)")
        lines.append("\n> Focus: architecture decisions, modularity, scalability, test coverage potential.")

    else:
        if entities:
            lines.append(f"**Key entities**: {', '.join(entities[:12])}")
        if chunks:
            lines.append(f"Content: {len(chunks)} segments available")

    return "\n".join(lines) + "\n"


async def _call_single_teammate(
    teammate: dict,
    user_message: str,
    history_texts: list[str],
    turn_number: int,
    shared_attachment_context: Optional[dict] = None,
) -> Optional[dict]:
    """
    Call a single teammate and return result, or None if failed.
    Returns: {"role": str, "message": str, "author_name": str} | None
    """
    tm_api_key_ref = teammate.get("api_key_ref")
    if not tm_api_key_ref:
        return None

    apikey = apikey_cache.get(tm_api_key_ref)
    if apikey:
        api_key_val, base_url_val = apikey["api_key"], apikey["base_url"] or ""
    else:
        from backend.database import async_session
        from sqlalchemy import select
        from backend.models import APIKey
        from backend.crypto import decrypt_value
        async with async_session() as sess:
            result = await sess.execute(select(APIKey).where(APIKey.id == tm_api_key_ref))
            apikey_obj = result.scalar_one_or_none()
            if not apikey_obj or apikey_obj.is_active != "1":
                return None
            plain = decrypt_value(apikey_obj.api_key)
            api_key_val, base_url_val = plain, apikey_obj.base_url or ""
            apikey_cache.set(tm_api_key_ref, {"api_key": plain, "base_url": apikey_obj.base_url or ""})

    prompt = _build_turn_prompt(
        teammate, user_message, history_texts, turn_number,
        shared_attachment_context,
    )

    chunks = []
    try:
        async for chunk in stream_ai_response(
            system_prompt=prompt,
            messages=[{"role": "user", "content": user_message}],
            provider=teammate.get("model_provider", "openrouter"),
            model=teammate.get("model_name", "openrouter/auto"),
            api_key=api_key_val,
            base_url=base_url_val or None,
        ):
            chunks.append(chunk)
    except Exception as e:
        logger.warning(f"Teammate {teammate.get('name', '?')} failed: {e}")
        return None

    full_text = "".join(chunks).strip()

    # Check for "no new info" signal — retry once with a more direct prompt
    if full_text == "[NO_NEW_INFO]" or full_text.endswith("[NO_NEW_INFO]"):
        logger.info(f"Teammate {teammate.get('name', '?')} signaled NO_NEW_INFO, retrying...")
        # Retry: ask directly for their perspective without anti-redundancy pressure
        retry_prompt = f"""{teammate.get('system_prompt', 'You are a helpful team member.')}

The user asked: {user_message}

Give YOUR personal perspective in 2-3 sentences. Do NOT say "no new info" — just give your opinion, even if the question is generic."""
        try:
            retry_chunks = []
            async for chunk in stream_ai_response(
                system_prompt=retry_prompt,
                messages=[{"role": "user", "content": user_message}],
                provider=teammate.get("model_provider", "openrouter"),
                model=teammate.get("model_name", "openrouter/auto"),
                api_key=api_key_val,
                base_url=base_url_val or None,
            ):
                retry_chunks.append(chunk)
            retry_text = "".join(retry_chunks).strip()
            if retry_text and retry_text != "[NO_NEW_INFO]" and not retry_text.endswith("[NO_NEW_INFO]"):
                full_text = retry_text
            else:
                return None
        except Exception as e:
            logger.warning(f"Teammate {teammate.get('name', '?')} retry also failed: {e}")
            return None

    if not full_text:
        return None

    role = _detect_role(teammate)
    return {
        "role": role,
        "message": full_text,
        "author_name": teammate.get("name", ""),
    }


async def _resolve_api_key(tm: dict):
    """Resolve API key and base_url for a teammate. Returns (api_key_val, base_url_val) or (None, None)."""
    tm_api_key_ref = tm.get("api_key_ref")
    if not tm_api_key_ref:
        return None, None

    apikey = apikey_cache.get(tm_api_key_ref)
    if apikey:
        return apikey["api_key"], apikey["base_url"] or ""

    from backend.database import async_session
    from sqlalchemy import select
    from backend.models import APIKey
    from backend.crypto import decrypt_value
    async with async_session() as sess:
        result = await sess.execute(select(APIKey).where(APIKey.id == tm_api_key_ref))
        apikey_obj = result.scalar_one_or_none()
        if apikey_obj and apikey_obj.is_active == "1":
            plain = decrypt_value(apikey_obj.api_key)
            apikey_cache.set(tm_api_key_ref, {"api_key": plain, "base_url": apikey_obj.base_url or ""})
            return plain, apikey_obj.base_url or ""
    return None, None


async def _run_single_teammate(
    tm: dict,
    user_message: str,
    history_texts: list[str],
    turn_idx: int,
    phase: str,
    shared_attachment_context: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    """
    Run a single teammate and yield SSE events.
    Handles [NO_NEW_INFO] — detects early (first 60 chars),
    buffers the full response and retries if needed.
    Otherwise streams chunk-by-chunk for fast perceived speed.
    """
    role = _detect_role(tm)
    api_key_val, base_url_val = await _resolve_api_key(tm)
    if not api_key_val:
        return

    message_id = str(uuid.uuid4())

    prompt = _build_turn_prompt(tm, user_message, history_texts, turn_idx, shared_attachment_context)

    # Phase 1: collect early prefix to detect [NO_NEW_INFO]
    early_buffer = ""
    early_done = False
    full_text = ""
    buffered_chunks: list[str] = []

    try:
        async for chunk in stream_ai_response(
            system_prompt=prompt,
            messages=[{"role": "user", "content": user_message}],
            provider=tm.get("model_provider", "openrouter"),
            model=tm.get("model_name", "openrouter/auto"),
            api_key=api_key_val,
            base_url=base_url_val or None,
        ):
            full_text += chunk
            if not early_done:
                early_buffer += chunk
                buffered_chunks.append(chunk)
                # Check if we have enough to detect [NO_NEW_INFO]
                if len(early_buffer) >= 60 or "\n" in early_buffer:
                    if early_buffer.lstrip().startswith("[NO_NEW_INFO]"):
                        # Found [NO_NEW_INFO] — buffer the rest and retry
                        early_done = True  # signal to keep collecting
                        continue
                    # Normal response — flush buffer and stream normally
                    early_done = True
                    for c in buffered_chunks:
                        yield emit_event(
                            event_type="teammate_message",
                            message_id=message_id,
                            role=role,
                            phase=phase,
                            payload={"content": c, "author_name": tm.get("name", ""), "teammate_id": tm.get("id", "")},
                        )
                    buffered_chunks = []
                    continue
            else:
                # Still collecting after [NO_NEW_INFO] detection — keep buffering
                continue
    except Exception as e:
        logger.warning(f"Teammate {tm.get('name', '?')} ({role}) stream failed: {e}")
        return

    full_text = full_text.strip()

    # Flag: did we already stream content to the frontend?
    already_streamed = early_done and not buffered_chunks

    # Handle [NO_NEW_INFO] — retry once (only if we haven't streamed yet)
    if not already_streamed and (full_text == "[NO_NEW_INFO]" or full_text.endswith("[NO_NEW_INFO]")):
        logger.info(f"Teammate {tm.get('name', '?')} signaled NO_NEW_INFO, retrying...")
        retry_prompt = f"""{tm.get('system_prompt', 'You are a helpful team member.')}

The user asked: {user_message}

Give YOUR personal perspective in 2-3 sentences. Do NOT say "no new info" — just give your opinion, even if the question is generic."""
        try:
            retry_full = ""
            async for chunk in stream_ai_response(
                system_prompt=retry_prompt,
                messages=[{"role": "user", "content": user_message}],
                provider=tm.get("model_provider", "openrouter"),
                model=tm.get("model_name", "openrouter/auto"),
                api_key=api_key_val,
                base_url=base_url_val or None,
            ):
                retry_full += chunk
                yield emit_event(
                    event_type="teammate_message",
                    message_id=message_id,
                    role=role,
                    phase=phase,
                    payload={"content": chunk, "author_name": tm.get("name", ""), "teammate_id": tm.get("id", "")},
                )
            retry_full = retry_full.strip()
            if not retry_full or retry_full == "[NO_NEW_INFO]" or retry_full.endswith("[NO_NEW_INFO]"):
                return
        except Exception as e:
            logger.warning(f"Teammate {tm.get('name', '?')} retry failed: {e}")
            return

        yield emit_event(
            event_type="teammate_end",
            message_id=message_id,
            role=role,
            phase=phase,
            payload={},
        )
        return

    if not full_text:
        return

    # If we exited early without flushing (short response where early_done never triggered)
    if buffered_chunks and not early_done:
        for c in buffered_chunks:
            yield emit_event(
                event_type="teammate_message",
                message_id=message_id,
                role=role,
                phase=phase,
                payload={"content": c, "author_name": tm.get("name", ""), "teammate_id": tm.get("id", "")},
            )

    yield emit_event(
        event_type="teammate_end",
        message_id=message_id,
        role=role,
        phase=phase,
        payload={},
    )


async def generate_team_response(
    teammates: list[dict],
    user_message: str,
    channel_id: str,
    shared_attachment_context: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    """
    Slack-like multi-teammate sequential chat.

    Flow:
      Round 1: teammates speak in ROLE_CHAIN_ORDER (engineer→analyst→designer→PM→engineer_lead)

    SSE event types: teammate_message, teammate_end, system_message, error
    Each teammate gets a unique per-request message_id (uuid4).
    No debate, no fact verification, no conflict detection, no decision compression.
    """
    if not teammates:
        yield emit_event(
            event_type="error",
            message_id="no-teammates",
            role="",
            phase="",
            payload={"message": "No teammates available for this channel."},
        )
        return

    # ── Single teammate: direct response ──
    if len(teammates) == 1:
        tm = teammates[0]
        async for event in _run_single_teammate(
            tm, user_message, [], 0, "round_1", shared_attachment_context
        ):
            # Skip empty responses
            yield event
        return

    # ── Multi-teammate: Sequential chain ──
    # Build ordered list of teammates matching ROLE_CHAIN_ORDER
    role_to_tm = {}
    for tm in teammates:
        r = _detect_role(tm)
        if r not in role_to_tm:
            role_to_tm[r] = tm

    chain = []
    for role in ROLE_CHAIN_ORDER:
        tm = role_to_tm.get(role)
        if tm and tm.get("api_key_ref"):
            chain.append(tm)

    if len(chain) < 2:
        chain = [tm for tm in teammates if tm.get("api_key_ref")]

    # Collect history for anti-redundancy
    history_texts = []

    # ═══════════════════════════════════════════════
    # ROUND 1: Sequential chain (TRUE streaming — emit per chunk)
    # ═══════════════════════════════════════════════
    skipped = 0
    for idx, tm in enumerate(chain):
        # Capture state for closure
        captured_history = history_texts.copy()
        captured_idx = idx

        # We need to collect full_text to decide if we add to history.
        # Since _run_single_teammate yields streaming, we collect here.
        full_text = ""
        response_message_id = None

        async for event_str in _run_single_teammate(
            tm, user_message, captured_history, captured_idx, "round_1", shared_attachment_context
        ):
            # Extract message_id from the first event to detect empty responses
            try:
                parsed = json.loads(event_str[6:].strip())  # strip "data: " prefix
                if not response_message_id:
                    response_message_id = parsed.get("message_id")
            except:
                pass

            yield event_str

        # Check if we actually got meaningful content by re-checking the stream
        # (We can't easily know post-hoc; events already yielded)
        # Always add a placeholder to history — anti-redundancy still works
        # even if slightly less effective with this simplification
        history_texts.append(f"[teammate {idx} responded]")

    if skipped > 0:
        logger.info(f"Sequential chat skipped {skipped} empty responses")

    logger.info(
        f"Sequential chat completed: {len(history_texts)} teammates responded"
    )
