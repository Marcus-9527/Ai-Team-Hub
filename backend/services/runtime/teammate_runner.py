"""
runtime/teammate_runner.py — Single-teammate execution runner.

Extracted from team_collaboration.py to provide a reusable,
pipeline-compatible interface for calling individual teammates.

Ponytail: TeammateRunner is a module-level function collection, not a class.
A class would be a layer of indentation with one implementation.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from backend.cache import teammate_cache, apikey_cache
from backend.services.brain.chat_memory import extract_and_store
from backend.database import async_session
from sqlalchemy import select
from backend.models import APIKey
from backend.security.crypto import decrypt_value

logger = logging.getLogger("runtime.teammate_runner")


# ── Role Detection ──

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
Output: 2-3 sentences max. Be concrete and architectural.
""",

    "techlead": """You are the TECH LEAD. Focus: REQUIREMENTS ANALYSIS, TASK DECOMPOSITION,
DEPENDENCY SETTING, ENGINEER ASSIGNMENT, and REVIEW SYNTHESIS.
Think in: what needs building, who should build it, in what order, how pieces fit.
Do NOT write implementation code. Decompose the work and coordinate; let Engineers implement.
Output: 2-3 sentences max. Be concrete and structural.
""",
}

def detect_role(teammate: dict) -> str:
    """Detect teammate role from system_prompt, role field, or name."""
    combined = " ".join([
        teammate.get("system_prompt") or "",
        teammate.get("role") or "",
        teammate.get("name") or "",
    ]).lower()

    if any(kw in combined for kw in ["reviewer", "review", "审核", "code review", "代码审查"]):
        return "reviewer"
    if any(kw in combined for kw in ["techlead", "tech lead", "技术负责人", "技术主管", "tech leader"]):
        return "techlead"
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
    return "engineer"


def build_anti_redundancy_context(history_texts: list[str]) -> str:
    """Build anti-redundancy instruction. Injected into each teammate's prompt."""
    if not history_texts:
        return ""
    recent = history_texts[-3:]
    lines = []
    for i, txt in enumerate(recent):
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


def build_turn_prompt(
    teammate: dict,
    user_message: str,
    history_texts: list[str],
    turn_number: int,
    shared_attachment_context: Optional[dict] = None,
    brain_prompt: str = "",
) -> str:
    """Build the full prompt for a single teammate's turn."""
    raw_system = teammate.get("system_prompt") or "You are a helpful team member."
    brain_prompt = brain_prompt or ""
    system_prompt = (brain_prompt + "\n\n" + raw_system) if brain_prompt else raw_system
    history_texts = [str(h) for h in (history_texts or [])]
    role = detect_role(teammate)
    axis = ROLE_AXIS_PROMPTS.get(role, ROLE_AXIS_PROMPTS["engineer"])
    anti_redundancy = build_anti_redundancy_context(history_texts)

    if turn_number == 0:
        turn_instruction = "You are the FIRST to respond. Give your perspective directly."
    elif turn_number == 1:
        turn_instruction = "You are responding AFTER other teammates. Build on or differ from their points."
    else:
        turn_instruction = "Several teammates have already spoken. Add unique value or say [NO_NEW_INFO]."

    attachment_section = ""
    if shared_attachment_context:
        attachment_section = _build_attachment_section(shared_attachment_context, role)

    return f"""{system_prompt}

{axis}

{attachment_section}
## Question from user:
{user_message}

{turn_instruction}
{anti_redundancy}

## Your response (2-3 sentences, natural, in your role's voice):
"""


def _build_attachment_section(ctx: dict, role: str = "engineer") -> str:
    """Build attachment context section for a role."""
    if not ctx:
        return ""
    filename = ctx.get("metadata", {}).get("filename", "unknown")
    file_type = ctx.get("type", "text")
    summary = ctx.get("summary", "")
    entities = ctx.get("extracted_entities", [])
    chunks = ctx.get("chunks", [])

    lines = [f"## File: {filename}"]
    lines.append(f"**Type**: {file_type} | {summary}")

    if role == "engineer":
        tech_entities = [e for e in entities if (e[0].isupper() or e.startswith("/") or "." in e or e.startswith("def "))]
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
        biz_entities = [e for e in entities if (e[0].isupper() and not e.startswith("/") and "." not in e)]
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
        layout_entities = [e for e in entities if ("/" in e or e.startswith("app") or e.startswith("page") or e.endswith("View") or e.endswith("Page"))]
        if layout_entities:
            lines.append(f"**Components / routes**: {', '.join(layout_entities[:10])}")
        if chunks:
            total_lines = sum(c.count("\n") + 1 for c in chunks)
            lines.append(f"**File size**: ~{total_lines} lines")
        lines.append("\n> Focus: user flow, information architecture, UX implications. Do NOT discuss backend logic.")
    elif role == "engineer_lead":
        tech_entities = [e for e in entities if (e[0].isupper() or e.startswith("/") or "." in e)]
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


# ── API Key Resolution ──

# ponytail: when a teammate has no key bound and we fall back to the
# workspace key, the teammate's stored model_name (e.g. "gpt-4o" from a
# stale seed) is usually invalid on that provider. Map each provider to one
# known-good default so a fresh user actually gets a response instead of a 401.
DEFAULT_MODEL_BY_PROVIDER = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
    "opencode": "deepseek-v4-flash-free",  # ponytail: free tier so a fresh user sees a reply without a payment method
    "openrouter": "openrouter/auto",
    "google": "gemini-2.0-flash",
    "deepseek": "deepseek-chat",
    "moonshot": "moonshot-v1-8k",
    "zhipu": "glm-4-plus",
    "alibaba": "qwen-max",
    "doubao": "doubao-pro-32k",
}


async def resolve_api_key(teammate: dict) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Resolve API key, base_url, provider and (fallback) default model for a teammate.

    Returns (api_key_val, base_url_val, provider, fallback_model).
    fallback_model is non-None only when we fell back to a workspace key, in
    which case the teammate's stored model_name may not exist on that provider
    and should be replaced with it.
    """
    tm_api_key_ref = teammate.get("api_key_ref")
    ws_id = teammate.get("workspace_id")
    fallback = False
    fallback_model = None
    if not tm_api_key_ref:
        fb = await _workspace_active_key(ws_id)
        if fb:
            tm_api_key_ref, fb_base, fb_provider = fb
            fallback = True
            fallback_model = DEFAULT_MODEL_BY_PROVIDER.get(fb_provider)
            # ponytail: explicit audit trail — teammate has no own key, using
            # the workspace-scoped key (never a foreign workspace's key).
            logger.info(
                "[KEY] teammate '%s' has no own key — using workspace %s's active key",
                teammate.get("name", "?"), ws_id or "legacy-global",
            )

    if not tm_api_key_ref:
        return None, None, None, None

    apikey = apikey_cache.get(tm_api_key_ref)
    if apikey:
        # ponytail: a bound key's provider is authoritative; only fall back to the
        # teammate's stored provider when the key has no provider recorded.
        if fallback:
            prov = apikey.get("provider")
        else:
            prov = apikey.get("provider") or teammate.get("model_provider", "openrouter")
        return apikey["api_key"], (apikey.get("base_url") or ""), prov, fallback_model

    async with async_session() as sess:
        result = await sess.execute(select(APIKey).where(APIKey.id == tm_api_key_ref))
        apikey_obj = result.scalar_one_or_none()
        if apikey_obj and apikey_obj.is_active == "1":
            plain = decrypt_value(apikey_obj.api_key)
            prov = apikey_obj.provider if fallback else teammate.get("model_provider", "openrouter")
            apikey_cache.set(tm_api_key_ref, {"api_key": plain, "base_url": apikey_obj.base_url or "", "provider": apikey_obj.provider})
            return plain, apikey_obj.base_url or "", prov, fallback_model
    return None, None, None, None


async def resolve_workspace_api_key(workspace_id: str | None = None, db_session=None) -> Optional[tuple]:
    """Return (api_key, base_url, provider) for the workspace's active key, or None.

    Scoped to workspace_id when given; otherwise matches workspace-less keys
    (legacy/global fallback).  Queries + decrypts in one call —
    the single point of truth for workspace-scoped key resolution.

    Accepts an optional existing DB session to avoid deadlocks.
    If none given, opens a new one.
    """
    from backend.security.crypto import decrypt_value

    if db_session is not None:
        return await _resolve_ws_key_raw(db_session, workspace_id)

    async with async_session() as sess:
        return await _resolve_ws_key_raw(sess, workspace_id)


async def _resolve_ws_key_raw(sess, workspace_id: str | None = None) -> Optional[tuple]:
    """Internal: full query + decrypt, caller must provide a session."""
    from backend.security.crypto import decrypt_value

    for cond in (
        APIKey.workspace_id == (workspace_id or None),
        APIKey.workspace_id.isnot(None),
        APIKey.workspace_id.is_(None),
    ):
        result = await sess.execute(
            select(APIKey).where(APIKey.is_active == "1", cond).limit(1)
        )
        k = result.scalar_one_or_none()
        if k:
            plain = decrypt_value(k.api_key)
            if plain:
                return plain, (k.base_url or ""), k.provider
    return None


async def _workspace_active_key(workspace_id: str | None = None) -> Optional[tuple]:
    """DEPRECATED — use resolve_workspace_api_key().  Kept for backward compat.

    Return (id, base_url, provider) for the active workspace key, or None.
    Does NOT decrypt the key — callers should migrate to resolve_workspace_api_key().
    """
    async with async_session() as sess:
        for cond in (
            APIKey.workspace_id == (workspace_id or None),
            APIKey.workspace_id.isnot(None),
            APIKey.workspace_id.is_(None),
        ):
            result = await sess.execute(
                select(APIKey).where(APIKey.is_active == "1", cond).limit(1)
            )
            k = result.scalar_one_or_none()
            if k:
                return k.id, (k.base_url or ""), k.provider
    return None


# ── Call Teammate (non-streaming) ──

async def call_teammate(
    teammate: dict,
    user_message: str,
    history_texts: list[str],
    turn_number: int,
    shared_attachment_context: Optional[dict] = None,
) -> Optional[dict]:
    """
    Call a single teammate (non-streaming). Returns {"role", "message", "author_name"} or None.
    Used by pipeline and task-execution paths.
    """
    api_key_val, base_url_val, key_provider, fallback_model = await resolve_api_key(teammate)
    if not api_key_val:
        return None

    # ponytail: fallback → use provider default model, not the teammate's stale one.
    model_name = fallback_model or teammate.get("model_name", "openrouter/auto")

    # ponytail: pass user_message as semantic query for relevant memory
    from backend.services.brain.brain_loader import get_brain_loader
    brain_prompt = await get_brain_loader().build_prompt(
        teammate.get("id", ""), query=user_message,
        workspace_id=teammate.get("workspace_id", ""),
    )

    prompt = build_turn_prompt(teammate, user_message, history_texts, turn_number, shared_attachment_context, brain_prompt=brain_prompt)

    from backend.services.runtime.agent_loop import AgentLoop as _AgentLoop
    from backend.services.runtime.llm_client_and_tools import (
        create_streaming_llm_client as _create_streaming, ToolExecutorAdapter as _ToolExec,
    )

    chunks = []
    async def _collect_chunk(text: str):
        chunks.append(text)

    try:
        streaming_client = _create_streaming(
            api_key=api_key_val, model=model_name,
            provider=key_provider or teammate.get("model_provider", "openrouter"),
            base_url=base_url_val or "",
            max_tokens=1024,
        )
        loop = _AgentLoop(llm_client=streaming_client, tool_executor=_ToolExec(), max_turns=1)
        await loop.run(
            system_prompt=prompt,
            messages=[{"role": "user", "content": user_message}],
            tools=[],
            workspace_id=teammate.get("workspace_id", ""),
            subject=detect_role(teammate),
            on_text_chunk=_collect_chunk,
        )
    except Exception as e:
        logger.warning(f"Teammate {teammate.get('name', '?')} failed: {e}")
        return None

    full_text = "".join(chunks).strip()

    # [NO_NEW_INFO] retry
    if full_text == "[NO_NEW_INFO]" or full_text.endswith("[NO_NEW_INFO]"):
        logger.info(f"Teammate {teammate.get('name', '?')} signaled NO_NEW_INFO, retrying...")
        retry_prompt = f"""{teammate.get('system_prompt', 'You are a helpful team member.')}

The user asked: {user_message}

Give YOUR personal perspective in 2-3 sentences. Do NOT say "no new info" — just give your opinion, even if the question is generic."""
        try:
            retry_chunks = []
            async def _retry_chunk(text: str):
                retry_chunks.append(text)
            sc = _create_streaming(
                api_key=api_key_val, model=model_name,
                provider=teammate.get("model_provider", "openrouter"),
                base_url=base_url_val or "",
                max_tokens=1024,
            )
            loop = _AgentLoop(llm_client=sc, tool_executor=_ToolExec(), max_turns=1)
            await loop.run(
                system_prompt=retry_prompt,
                messages=[{"role": "user", "content": user_message}],
                tools=[],
                workspace_id=teammate.get("workspace_id", ""),
                subject=teammate.get("role", ""),
                on_text_chunk=_retry_chunk,
            )
            retry_text = "".join(retry_chunks).strip()
            if retry_text and retry_text != "[NO_NEW_INFO]" and not retry_text.endswith("[NO_NEW_INFO]"):
                full_text = retry_text
            else:
                return None
        except Exception as e:
            logger.warning(f"Teammate {teammate.get('name', '?')} retry failed: {e}")
            return None

    if not full_text:
        return None

    role = detect_role(teammate)
    return {"role": role, "message": full_text, "author_name": teammate.get("name", "")}


# ── Stream Teammate (SSE) ──

def _emit_event(
    event_type: str,
    message_id: str,
    role: str = "",
    phase: str = "",
    payload: dict = None,
    channel_id: str = "",
) -> str:
    """Emit a single SSE-formatted JSON event."""
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


def _emit_placeholder_then_error(
    message_id: str, role: str, phase: str, teammate: dict, err: str
) -> list[str]:
    """Ponytail: guarantee a bubble exists before the error event.

    Frontend matches the `error` event to a team bubble by message_id and only
    then flips its status to 'error' (✗). If the stream dies before emitting any
    teammate_message (no key / connection failure), no bubble exists and the ✗
    never shows. Emitting an empty placeholder bubble first keeps the existing
    frontend match logic untouched.
    """
    placeholder = _emit_event(
        event_type="teammate_message",
        message_id=message_id,
        role=role,
        phase=phase,
        payload={"content": "", "author_name": teammate.get("name", ""), "teammate_id": teammate.get("id", "")},
    )
    error = _emit_event(
        event_type="error",
        message_id=message_id,
        role=role,
        phase=phase,
        payload={"content": f"Teammate {teammate.get('name', '?')} failed: {err}"},
    )
    return [placeholder, error]


async def stream_teammate(
    teammate: dict,
    user_message: str,
    history_texts: list[str],
    turn_idx: int,
    phase: str,
    shared_attachment_context: Optional[dict] = None,
    channel_id: str = "",
) -> AsyncGenerator[str, None]:
    """
    Run a single teammate with SSE streaming.
    Yields SSE events (teammate_message, teammate_end, error).
    """
    role = detect_role(teammate)
    api_key_val, base_url_val, resolved_provider, fallback_model = await resolve_api_key(teammate)
    if not api_key_val:
        for ev in _emit_placeholder_then_error(
            message_id=str(uuid.uuid4()), role=role, phase=phase,
            teammate=teammate, err="no API key configured",
        ):
            yield ev
        return

    # ponytail: when we fell back to a workspace key, the teammate's stored
    # model_name may not exist on that provider — use the provider default.
    model_name = fallback_model or teammate.get("model_name", "openrouter/auto")
    message_id = str(uuid.uuid4())
    # ponytail: pass user_message as semantic query for relevant memory
    from backend.services.brain.brain_loader import get_brain_loader
    brain_prompt = await get_brain_loader().build_prompt(
        teammate.get("id", ""), query=user_message,
        workspace_id=teammate.get("workspace_id", ""),
    )
    # 聊天记忆注入：best-effort，失败跳过（不阻塞对话）
    try:
        from backend.services.brain.fragment_store import get_brain_fragment_store, BrainFragmentType
        chat_mem = await get_brain_fragment_store().recent_chat_memory(
            teammate.get("id", ""), teammate.get("workspace_id", ""), limit=8,
        )
        if chat_mem:
            lines = "\n".join(f"  - {m.content}" for m in chat_mem)
            brain_prompt = (brain_prompt + f"\n\n## CHAT MEMORY（你之前在这个工作区记住的）\n{lines}").strip()
    except Exception as e:
        logger.warning("[ChatMemory] injection skipped (msg still flows): %s", e)
    prompt = build_turn_prompt(teammate, user_message, history_texts, turn_idx, shared_attachment_context, brain_prompt=brain_prompt)

    ENGINEER_ROLES = {"engineer", "techlead", "engineer_lead"}
    full_text = ""
    role_is_engineer = role in ENGINEER_ROLES

    if role_is_engineer:
        # ── AgentLoop + Queue bridge 路径（工具角色）──
        import asyncio
        from backend.services.runtime.agent_loop import AgentLoop
        from backend.services.runtime.llm_client_and_tools import (
            create_llm_client, ToolExecutorAdapter,
        )
        from backend.services.organization.capability import CapabilityRegistry

        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        async def _emit_text(text: str):
            queue.put_nowait(("text", text))

        async def _emit_tool(tc, tr):
            queue.put_nowait(("tool", tc, tr))

        async def _run_loop_background():
            try:
                llm_client = create_llm_client(
                    api_key=api_key_val, model=model_name,
                    provider=resolved_provider or teammate.get("model_provider", "openrouter"),
                    base_url=base_url_val or "",
                )
                executor = ToolExecutorAdapter()
                loop = AgentLoop(llm_client=llm_client, tool_executor=executor, max_turns=6)
                engineer_tools = CapabilityRegistry().resolve_tools(role)
                result = await loop.run(
                    system_prompt=prompt,
                    messages=[{"role": "user", "content": user_message}],
                    tools=engineer_tools,
                    workspace_id=teammate.get("workspace_id", ""),
                    subject=role,
                    on_text_chunk=_emit_text,
                    on_tool_call=_emit_tool,
                )
                queue.put_nowait(_SENTINEL)
                return result
            except (Exception, asyncio.CancelledError) as e:
                logger.exception("[AgentLoop] background task failed")
                queue.put_nowait(("error", str(e)))
                queue.put_nowait(_SENTINEL)

        task = asyncio.create_task(_run_loop_background())

        # task.add_done_callback 保险：即使任务崩在 try 块之前（创建 client/AgentLoop 时），
        # 也确保 sentinel 不会缺失 → 外层 while 不会死锁
        def _on_task_done(t: asyncio.Task):
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                queue.put_nowait(("error", str(exc)))
                queue.put_nowait(_SENTINEL)
        task.add_done_callback(_on_task_done)

        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            kind = item[0]
            if kind == "text":
                content = item[1]
                full_text += content
                yield _emit_event(
                    event_type="teammate_message",
                    message_id=message_id, role=role, phase=phase,
                    payload={"content": content, "author_name": teammate.get("name", ""), "teammate_id": teammate.get("id", "")},
                )
            elif kind == "tool":
                tc, tr = item[1], item[2]
                yield _emit_event(
                    event_type="tool_call",
                    message_id=message_id, role=role, phase=phase,
                    payload={"name": tc.name, "arguments": tc.arguments, "status": "ok" if not tr.is_error else "error"},
                )
            elif kind == "error":
                for ev in _emit_placeholder_then_error(
                    message_id=message_id, role=role, phase=phase,
                    teammate=teammate, err=item[1],
                ):
                    yield ev
                return

        full_text = full_text.strip()
        yield _emit_event(
            event_type="teammate_end",
            message_id=message_id, role=role, phase=phase,
            payload={"author_name": teammate.get("name", ""), "teammate_id": teammate.get("id", "")},
        )
        extract_and_store(teammate, user_message, full_text, channel_id)
        return

    # ── 非工具角色（analyst / designer / pm / …）── AgentLoop + StreamingLLMClient
    import asyncio
    from backend.services.runtime.agent_loop import AgentLoop as _AgentLoop
    from backend.services.runtime.llm_client_and_tools import (
        create_streaming_llm_client as _create_streaming, ToolExecutorAdapter as _ToolExec,
    )

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()
    early_buffer = ""
    early_done = False
    buffered_chunks: list[str] = []
    _detected_no_new_info = False

    async def _on_text(text: str):
        nonlocal early_buffer, early_done, buffered_chunks, _detected_no_new_info, full_text
        full_text += text
        if not early_done:
            early_buffer += text
            buffered_chunks.append(text)
            if len(early_buffer) >= 60 or "\n" in early_buffer:
                if early_buffer.lstrip().startswith("[NO_NEW_INFO]"):
                    early_done = True
                    _detected_no_new_info = True
                    return
                early_done = True
                for c in buffered_chunks:
                    queue.put_nowait(c)
                buffered_chunks = []
        else:
            queue.put_nowait(text)

    async def _run_bg():
        try:
            streaming_client = _create_streaming(
                api_key=api_key_val, model=model_name,
                provider=resolved_provider or teammate.get("model_provider", "openrouter"),
                base_url=base_url_val or "",
                max_tokens=1024,
            )
            loop = _AgentLoop(llm_client=streaming_client, tool_executor=_ToolExec(), max_turns=1)
            await loop.run(
                system_prompt=prompt,
                messages=[{"role": "user", "content": user_message}],
                tools=[],
                workspace_id=teammate.get("workspace_id", ""),
                subject=role,
                on_text_chunk=_on_text,
            )
            queue.put_nowait(_SENTINEL)
        except Exception as e:
            logger.exception("[AgentLoop] background task failed")
            queue.put_nowait(("error", str(e)))
            queue.put_nowait(_SENTINEL)

    # Flush remaining buffered chunks before reading from queue
    if buffered_chunks and not early_done:
        for c in buffered_chunks:
            queue.put_nowait(c)
        buffered_chunks = []
        early_done = True

    bg_task = asyncio.create_task(_run_bg())

    while True:
        item = await queue.get()
        if item is _SENTINEL:
            break
        if isinstance(item, str):
            yield _emit_event(
                event_type="teammate_message",
                message_id=message_id, role=role, phase=phase,
                payload={"content": item, "author_name": teammate.get("name", ""), "teammate_id": teammate.get("id", "")},
            )
            continue
        if isinstance(item, tuple) and item[0] == "error":
            for ev in _emit_placeholder_then_error(
                message_id=message_id, role=role, phase=phase,
                teammate=teammate, err=item[1],
            ):
                yield ev
            return

    full_text = full_text.strip()

    # ── [NO_NEW_INFO] retry ──
    if _detected_no_new_info and (full_text == "[NO_NEW_INFO]" or full_text.endswith("[NO_NEW_INFO]")):
        logger.info(f"Teammate {teammate.get('name', '?')} signaled NO_NEW_INFO, retrying...")
        retry_prompt = f"""{teammate.get('system_prompt', 'You are a helpful team member.')}

The user asked: {user_message}

Give YOUR personal perspective in 2-3 sentences. Do NOT say "no new info" — just give your opinion, even if the question is generic."""
        try:
            retry_full = ""
            queue2: asyncio.Queue = asyncio.Queue()

            async def _retry_chunk(text: str):
                nonlocal retry_full
                retry_full += text
                queue2.put_nowait(text)

            async def _retry_bg():
                try:
                    sc = _create_streaming(
                        api_key=api_key_val, model=model_name,
                        provider=teammate.get("model_provider", "openrouter"),
                        base_url=base_url_val or "",
                        max_tokens=1024,
                    )
                    loop = _AgentLoop(llm_client=sc, tool_executor=_ToolExec(), max_turns=1)
                    await loop.run(
                        system_prompt=retry_prompt,
                        messages=[{"role": "user", "content": user_message}],
                        tools=[],
                        workspace_id=teammate.get("workspace_id", ""),
                        subject=role,
                        on_text_chunk=_retry_chunk,
                    )
                    queue2.put_nowait(_SENTINEL)
                except Exception as e:
                    logger.exception("[AgentLoop] retry background task failed")
                    queue2.put_nowait(("error", str(e)))
                    queue2.put_nowait(_SENTINEL)

            asyncio.create_task(_retry_bg())
            while True:
                item2 = await queue2.get()
                if item2 is _SENTINEL:
                    break
                if isinstance(item2, str):
                    yield _emit_event(
                        event_type="teammate_message",
                        message_id=message_id, role=role, phase=phase,
                        payload={"content": item2, "author_name": teammate.get("name", ""), "teammate_id": teammate.get("id", "")},
                    )
                    continue
                if isinstance(item2, tuple) and item2[0] == "error":
                    yield _emit_event(
                        event_type="error",
                        message_id=message_id, role=role, phase=phase,
                        payload={"content": f"Teammate {teammate.get('name', '?')} retry failed: {item2[1]}"},
                    )
                    return

            yield _emit_event(
                event_type="teammate_end",
                message_id=message_id, role=role, phase=phase,
                payload={"author_name": teammate.get("name", ""), "teammate_id": teammate.get("id", "")},
            )
            extract_and_store(teammate, user_message, retry_full.strip(), channel_id)
        except Exception as e:
            logger.warning(f"Teammate {teammate.get('name', '?')} retry failed: {e}")
            yield _emit_event(
                event_type="error",
                message_id=message_id, role=role, phase=phase,
                payload={"content": f"Teammate {teammate.get('name', '?')} retry failed: {e}"},
            )
        return

    yield _emit_event(
        event_type="teammate_end",
        message_id=message_id, role=role, phase=phase,
        payload={"author_name": teammate.get("name", ""), "teammate_id": teammate.get("id", "")},
    )
    extract_and_store(teammate, user_message, full_text, channel_id)
