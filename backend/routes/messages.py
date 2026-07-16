"""
Message & chat routes — streaming AI response with separated cache/memory architecture.

Architecture:
  CACHE LAYER (static)  → cache_key.py + cache_prefix_builder.py
  DYNAMIC LAYER         → context_builder.py
  MEMORY ENGINE         → memory (intelligence layer) + memory_summarizer
  LLM RUNTIME           → ai_service.py (stream_ai_response + warmup_cache)

Flow:
  1. compute_cache_key(system_prompt) → static key
  2. build_fixed_prefix(system_prompt, recent_turns, current_input) → 9 messages
  3. warmup_cache(system_prompt) → prime DeepSeek cache entry
  4. stream_ai_response(system_prompt, messages) → LLM call
  5. process_conversation_turn() → memory write-back
"""
import asyncio
import json
import logging
import os
import uuid
import base64
import mimetypes
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models import Message, Channel, Teammate, APIKey
from backend.services.ai_service import stream_ai_response
from backend.services.cache_prefix_builder import build_fixed_prefix, extract_recent_turns
from backend.services.cache_warmup_service import is_warmed_up, mark_warmed_up
from backend.cache import message_cache, teammate_cache, apikey_cache

logger = logging.getLogger("messages")


def _no_key_error(message: str) -> dict:
    """Structured 400 body for the missing-API-key dead-end (P2 #5).

    Carries a recovery hint the frontend turns into a clickable link to Settings,
    so the user isn't stranded on a raw error string.
    """
    return {
        "message": message,
        "recovery": {
            "action": "open_settings",
            "label": "前往设置配置 API Key",
        },
    }

router = APIRouter(prefix="/api/messages", tags=["messages"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

WARMUP_ENABLED = True
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_TEXT_EXTRACT_SIZE = 8000  # 文本文件最大提取字符数

TEXT_EXTENSIONS = {
    '.txt', '.md', '.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml',
    '.html', '.htm', '.css', '.scss', '.less', '.xml', '.csv', '.log', '.sh',
    '.bash', '.zsh', '.sql', '.toml', '.ini', '.cfg', '.conf', '.env', '.rst',
    '.go', '.rs', '.java', '.kt', '.scala', '.c', '.cpp', '.h', '.hpp', '.swift',
    '.rb', '.php', '.pl', '.lua', '.r', '.m', '.mm', '.dockerfile', '.gitignore',
    '.vue', '.svelte', '.astro', '.php',
}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}
OFFICE_EXTENSIONS = {'.docx', '.pptx', '.pdf'}


def _process_file_for_llm(filename: str, content_bytes: bytes) -> tuple[str, Any]:
    """
    处理文件内容，准备可供 LLM 读取的形式。

    Returns:
        (text_content, message_content) —
        - text_content: 用于存入 DB content 字段的显示文本
        - message_content: 用于注入到 LLM message 的 content 格式
          文本文件 → str
          图片文件 → list of content blocks (OpenAI vision 格式)
    """
    ext = os.path.splitext(filename or "")[1].lower()

    # 文本类：直接 decode
    if ext in TEXT_EXTENSIONS:
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode("latin-1")
            except Exception as e:
                logger.warning(f"Failed to decode file content: {e}")
                text = f"[Binary file: {filename}]"
                return text, text

        if len(text) > MAX_TEXT_EXTRACT_SIZE:
            text = text[:MAX_TEXT_EXTRACT_SIZE] + f"\n... [truncated, total {len(text)} chars]"

        llm_content = f"[File: {filename}]\n{text}" if text.strip() else f"[File: {filename}] (empty)"
        return llm_content, llm_content

    # Office 文档类：专用解析器提取文本
    if ext in OFFICE_EXTENSIONS:
        from backend.services.attachment_service import _extract_office_text
        text = _extract_office_text(content_bytes, ext)
        if text:
            if len(text) > MAX_TEXT_EXTRACT_SIZE:
                text = text[:MAX_TEXT_EXTRACT_SIZE] + f"\n... [truncated, total {len(text)} chars]"
            llm_content = f"[File: {filename}]\n{text}" if text.strip() else f"[File: {filename}] (empty)"
            return llm_content, llm_content
        # Fall through to binary handling on failure

    # 图片类：base64 data URI (vision 格式)
    if ext in IMAGE_EXTENSIONS or (len(content_bytes) > 0 and _is_image_bytes(content_bytes)):
        mime = mimetypes.guess_type(filename)[0] or "image/png"
        b64 = base64.b64encode(content_bytes).decode("ascii")
        data_uri = f"data:{mime};base64,{b64}"
        # OpenAI-compatible vision content block
        llm_content = [
            {"type": "text", "text": f"[Image: {filename}]"},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]
        return f"[Image: {filename}]", llm_content

    # 其他二进制：尝试 utf-8 decode（可能漏掉的文本）
    try:
        text = content_bytes.decode("utf-8")
        if len(text) > MAX_TEXT_EXTRACT_SIZE:
            text = text[:MAX_TEXT_EXTRACT_SIZE] + f"\n... [truncated, total {len(text)} chars]"
        llm_content = f"[File: {filename}]\n{text}"
        return llm_content, llm_content
    except UnicodeDecodeError:
        pass

    # 纯二进制
    size = len(content_bytes)
    return f"[Binary file: {filename} ({_format_size(size)})]", f"[Binary file: {filename} ({_format_size(size)}), content not readable]"


def _is_image_bytes(data: bytes) -> bool:
    """Check magic bytes for common image formats."""
    if len(data) < 8:
        return False
    if data[:4] == b'\x89PNG':
        return True
    if data[:2] == b'\xff\xd8':
        return True
    if data[:4] == b'GIF8' and data[4:6] in (b'87a', b'89a'):
        return True
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    return False


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def _extract_text_from_history_message(msg) -> str:
    """
    从历史消息中提取文本内容。
    如果消息 content 是 list (vision 格式)，提取文本部分，忽略 image blocks。
    """
    content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)
    return str(content or "")


def _inject_attachment_content(messages: list) -> list:
    """
    将历史消息中 attachments 的 llm_content 注入到 message content。
    这样 build_fixed_prefix 构建的 prompt 就能包含文件内容。

    处理逻辑：
    - 文本文件：llm_content 是 str，直接替换 content（保留原始文本摘要）
    - 图片文件：llm_content 是 list (vision blocks)，把 content 转为 vision 格式
    """
    result = []
    for m in messages:
        if isinstance(m, dict):
            content = m.get("content", "")
            attachments = m.get("attachments") or []
        else:
            content = getattr(m, "content", "")
            attachments = getattr(m, "attachments", None) or []

        if attachments:
            # Take the first attachment's llm_content
            att = attachments[0]
            llm_content = att.get("llm_content")
            if llm_content and isinstance(llm_content, list):
                # Vision format: convert content to multimodal blocks
                text_content = str(content) if content else ""
                content = [
                    {"type": "text", "text": text_content},
                    *llm_content,
                ]
            elif llm_content and isinstance(llm_content, str):
                # Text file: llm_content already contains "[File: xxx]\n<content>"
                content = llm_content

        if isinstance(m, dict):
            m = dict(m)
            m["content"] = content
            result.append(m)
        else:
            # Create a dict representation for the LLM pipeline
            result.append({
                "role": getattr(m, "role", "user"),
                "content": content,
            })
    return result


@router.get("/{channel_id}")
async def list_messages(channel_id: str, limit: int = 200, db: AsyncSession = Depends(get_db)):
    if limit == 200:
        cached = message_cache.get(channel_id)
        if cached is not None:
            return cached

    result = await db.execute(
        select(Message)
        .where(Message.channel_id == channel_id)
        .order_by(Message.created_at)
        .limit(limit)
    )
    msgs = result.scalars().all()
    data = [
        {
            "id": m.id, "channel_id": m.channel_id, "role": m.role,
            "author_name": m.author_name, "author_id": m.author_id,
            "avatar_emoji": m.avatar_emoji or "🤖",
            "status": m.status or "unread",
            "content": m.content, "attachments": m.attachments or [],
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]

    if limit == 200:
        message_cache.set(channel_id, data)
    return data


@router.delete("/{channel_id}")
async def clear_messages(channel_id: str, db: AsyncSession = Depends(get_db)):
    ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
    if not ch_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Channel not found")
    result = await db.execute(select(Message).where(Message.channel_id == channel_id))
    msgs = result.scalars().all()
    for m in msgs:
        await db.delete(m)
    await db.commit()
    message_cache.invalidate(channel_id)
    return {"ok": True, "deleted": len(msgs)}


@router.post("/{channel_id}/system")
async def send_system_message(channel_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
    if not ch_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Channel not found")
    msg = Message(channel_id=channel_id, role="system",
                  author_name=data.get("author_name", "System"), content=data.get("content", ""))
    db.add(msg)
    await db.commit()
    message_cache.invalidate(channel_id)
    return {"id": msg.id, "role": "system"}


@router.post("/{channel_id}/file")
async def upload_file(channel_id: str, file: UploadFile = File(...),
                      author_name: str = Form("You"), db: AsyncSession = Depends(get_db)):
    return await _do_upload_file(channel_id, file, author_name, db)


async def _do_upload_file(channel_id: str, file: UploadFile, author_name: str, db: AsyncSession):
    ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
    if not ch_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Channel not found")

    ext = os.path.splitext(file.filename or "file")[1] or ""
    safe_name = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    content_bytes = await file.read()
    with open(file_path, "wb") as f:
        f.write(content_bytes)

    # Process file content so LLM can read it
    display_text, llm_content = _process_file_for_llm(file.filename or "file", content_bytes)
    is_vision = isinstance(llm_content, list)

    # ── Generate Shared AttachmentContext (async, single parse → DB cache) ──
    from backend.services.attachment_context import _db_save_context, parse_file_context, compute_content_hash

    file_id = str(uuid.uuid4())
    content_hash = compute_content_hash(content_bytes)
    ctx = parse_file_context(file_id, file.filename or "file", content_bytes)

    # Persist to DB (fire-and-forget style — INSERT OR IGNORE)
    await _db_save_context(ctx)

    msg = Message(
        channel_id=channel_id, role="user", author_name=author_name,
        content=display_text,
        attachments=[{
            "filename": file.filename or "file", "saved_as": safe_name,
            "size": len(content_bytes), "mime": file.content_type or "application/octet-stream",
            "llm_content": llm_content,
            "is_vision": is_vision,
            "context_version_key": ctx.version_key,
            "context_summary": ctx.summary,
            "context_dict": ctx.to_dict(),  # inline cache — avoids DB lookup on send
        }],
    )
    db.add(msg)
    await db.commit()
    message_cache.invalidate(channel_id)
    return {"id": msg.id, "attachment": msg.attachments[0], "message": f"Uploaded {file.filename}"}


@router.post("/{channel_id}")
async def send_message(channel_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    content = data.get("content", "")
    teammate_ids_raw = data.get("teammate_ids")
    attachments = data.get("attachments")
    skip_user_save = data.get("skip_user_save", False)

    # ── Load shared AttachmentContext (from uploaded file) ──
    shared_attachment_context = None
    if attachments:
        # Try inline cache first (avoids DB round-trip)
        for att in attachments:
            ctx_dict = att.get("context_dict")
            if ctx_dict:
                shared_attachment_context = ctx_dict
                break

        # Fallback to DB lookup if inline not present
        if not shared_attachment_context:
            from backend.services.attachment_context import _db_find_context_by_file_id
            for att in attachments:
                version_key = att.get("context_version_key")
                if version_key:
                    parts = version_key.split(":")
                    if len(parts) == 2:
                        ctx = await _db_find_context_by_file_id(parts[0], parts[1])
                        if ctx:
                            shared_attachment_context = ctx.to_dict()
                            break

    # If attachments contain llm_content, inject into content for LLM visibility
    if attachments:
        att_text_parts = []
        att_vision_blocks = []
        for att in attachments:
            llm_c = att.get("llm_content")
            if llm_c and isinstance(llm_c, str):
                att_text_parts.append(llm_c)
            elif llm_c and isinstance(llm_c, list):
                # Vision blocks — extract text parts and collect image blocks
                for block in llm_c:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            att_text_parts.append(block.get("text", ""))
                        elif block.get("type") == "image_url":
                            att_vision_blocks.append(block)
        if att_text_parts:
            content = (content + "\n\n" + "\n".join(att_text_parts)).strip()
        # If there are vision blocks, convert content to multimodal format
        if att_vision_blocks:
            content = json.dumps([
                {"type": "text", "text": content},
                *att_vision_blocks,
            ])

    # Save user message
    user_msg_id = None
    if not skip_user_save:
        user_msg = Message(channel_id=channel_id, role="user",
                           author_name=data.get("author_name", "You"),
                           content=content, attachments=attachments)
        db.add(user_msg)
        await db.commit()
        user_msg_id = user_msg.id
        message_cache.invalidate(channel_id)

    # ── Inject memory context before team response ──
    from backend.services.memory.memory_context import get_memory_context
    mem_ctx = await get_memory_context().build_chat_context(channel_id, content)
    if mem_ctx.text:
        content = f"[Previous context]\n{mem_ctx.text}\n\n---\n\n{content}"

    # ── Team Collaboration: all teammates respond ──
    from backend.services.team_collaboration import generate_team_response
    from backend.models import Channel as ChannelModel

    # Get all teammates in this channel
    channel_data = teammate_cache.get(f"channel_teammates:{channel_id}")
    channel_ws = None
    if channel_data is None:
        ch_result = await db.execute(select(ChannelModel).where(ChannelModel.id == channel_id))
        ch_obj = ch_result.scalar_one_or_none()
        if ch_obj:
            tm_ids = ch_obj.teammate_ids or []
            channel_data = list(tm_ids) if tm_ids else []
            channel_ws = ch_obj.workspace_id
            teammate_cache.set(f"channel_teammates:{channel_id}", channel_data)
        else:
            channel_data = []

    # Normalize teammate_ids: string → single-element list, list → as-is, None → all
    teammate_ids = teammate_ids_raw
    if isinstance(teammate_ids, str):
        teammate_ids = [teammate_ids]
    if not isinstance(teammate_ids, list):
        teammate_ids = None

    # Helper to load a teammate dict from cache or DB
    async def _load_teammate(tm_id: str) -> dict | None:
        tm = teammate_cache.get(tm_id)
        if tm is not None:
            return tm
        tm_result = await db.execute(select(Teammate).where(Teammate.id == tm_id))
        tm_obj = tm_result.scalar_one_or_none()
        if not tm_obj:
            return None
        tm = {
            "id": tm_obj.id, "name": tm_obj.name, "role": tm_obj.role,
            "avatar_emoji": tm_obj.avatar_emoji, "system_prompt": tm_obj.system_prompt,
            "model_provider": tm_obj.model_provider, "model_name": tm_obj.model_name,
            "api_key_ref": tm_obj.api_key_ref,
            "workspace_id": tm_obj.workspace_id,
        }
        teammate_cache.set(tm_id, tm)
        return tm

    # Ponytail fallback: if a teammate was never bound to a key but the
    # workspace has an active key, use it. Prevents the "configured a key but
    # channel says none found" dead-end (P1 #1).
    async def _fallback_key_ref(ws: str | None = None) -> str | None:
        kr = await db.execute(
            select(APIKey).where(
                APIKey.is_active == "1",
                APIKey.workspace_id == (ws or None),
            ).limit(1)
        )
        k = kr.scalar_one_or_none()
        return k.id if k else None

    all_teammates = []
    if teammate_ids:
        # Only the specified teammates
        for tm_id in teammate_ids:
            tm = await _load_teammate(tm_id)
            if tm and (tm.get("api_key_ref") or await _fallback_key_ref(channel_ws)):
                all_teammates.append(tm)
        if not all_teammates:
            raise HTTPException(status_code=400, detail=_no_key_error("No specified teammates found or have API keys"))
    else:
        # All channel teammates
        for tm_id in channel_data:
            tm = await _load_teammate(tm_id)
            if tm and (tm.get("api_key_ref") or await _fallback_key_ref(channel_ws)):
                all_teammates.append(tm)
        if not all_teammates:
            raise HTTPException(status_code=400, detail=_no_key_error("No teammates with API keys found in this channel"))

    # ── Load message history (always from DB to avoid truncated cache) ──
    hist_result = await db.execute(
        select(Message).where(Message.channel_id == channel_id).order_by(Message.created_at)
    )
    all_messages = list(hist_result.scalars().all())

    # ── Policy Gate: check each teammate's send permission ──
    from backend.services.task.task_policy import check_message_policy
    policy_allowed: list[dict] = []
    for tm in all_teammates:
        ok, _reason = await check_message_policy(db, tm, channel_id, action="message.send")
        if ok:
            policy_allowed.append(tm)
        else:
            logger.info("[Policy] blocked %s from channel %s: %s",
                        tm.get("name", "?"), channel_id[:8], _reason)
    all_teammates = policy_allowed
    if not all_teammates:
        raise HTTPException(status_code=400, detail="All teammates blocked by policy")

    # ── Cede Protocol: let each teammate decide whether to respond ──
    from backend.services.autonomous.cede_protocol import get_cede_protocol, CedeDecision
    cede = get_cede_protocol()
    cede_msg_id = user_msg_id or str(uuid.uuid4())
    ceded_teammates: list[dict] = []
    active_teammates: list[dict] = []
    # Explicit @ → user named these teammates; they MUST respond, skip cede.
    specified_ids = set(teammate_ids) if teammate_ids else set()
    for tm in all_teammates:
        if tm.get("id") in specified_ids:
            decision = CedeDecision.RESPOND
        else:
            decision = await cede.decide(tm, content, channel_id=channel_id, message_id=cede_msg_id)
        await cede.record_decision(tm, cede_msg_id, decision, channel_id=channel_id)
        if decision.value == "respond":
            active_teammates.append(tm)
        else:
            ceded_teammates.append(dict(tm))
    all_teammates = active_teammates

    # Team-mode chit-chat with no relevant teammate: nobody responds.
    # That's normal — return an empty success SSE instead of a 400 error.
    if not all_teammates:
        async def _empty():
            yield "data: [DONE]\n\n"
        return StreamingResponse(_empty(), media_type="text/event-stream")

    # ── Stream team collaboration response ──
    collected_events: list[dict] = []  # structured events — no SSE re-parse needed

    async def generate():
        try:
            # Emit cede notifications before streaming responses
            for ctm in ceded_teammates:
                yield "data: " + json.dumps({
                    "type": "system_message",
                    "payload": {"content": f"**{ctm.get('name', '?')}** chose not to respond ({ctm.get('role', '?')})"},
                }) + "\n\n"
            async for chunk in generate_team_response(
                teammates=all_teammates,
                user_message=content,
                channel_id=channel_id,
                shared_attachment_context=shared_attachment_context,
            ):
                # Parse structured event from SSE line for DB saving
                if chunk.startswith("data:") and not chunk.startswith("data: [DONE]"):
                    try:
                        evt = json.loads(chunk[5:].strip().rstrip("\n"))
                        collected_events.append(evt)
                    except (json.JSONDecodeError, ValueError):
                        pass
                yield chunk
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"\n\n⚠️ Team Error: {str(e)}"

    response = StreamingResponse(generate(), media_type="text/event-stream")

    # Background: save response to DB from structured events (no SSE re-parse)
    async def save_after_stream():
        """Background task: save AI response after stream completes."""
        await asyncio.sleep(0.1)  # Brief delay to ensure all chunks collected
        if not collected_events:
            return
        await _save_team_response_from_events(
            events=collected_events,
            channel_id=channel_id,
            teammate_ids=[tm["id"] for tm in all_teammates],
            tm_names=[tm["name"] for tm in all_teammates],
            all_messages=all_messages,
            content=content,
        )

    import asyncio
    from starlette.background import BackgroundTask
    response.background = BackgroundTask(save_after_stream)
    return response


# ── Helper: Save AI response to DB from structured events (no SSE re-parse) ──

async def _save_team_response_from_events(
    events: list[dict],
    channel_id: str,
    teammate_ids: list[str],
    tm_names: list[str],
    all_messages: list = None,
    content: Any = None,
):
    """Save team collaboration response to database from structured events.

    Accumulates teammate_message chunks by group_id/message_id.
    No SSE string parsing — events are already parsed during streaming.
    """
    try:
        # Accumulate teammate_message chunks by dedup key
        responses = {}
        for event in events:
            evt_type = event.get("type", "")
            if evt_type != "teammate_message":
                continue
            payload = event.get("payload", {})
            msg_id = event.get("message_id", "")
            chunk_content = payload.get("content", "")
            group_id = payload.get("group_id", "") or event.get("phase", "")
            dedup_key = group_id or msg_id
            if dedup_key in responses:
                responses[dedup_key]["content"] += chunk_content
            else:
                responses[dedup_key] = {
                    "teammate_id": payload.get("teammate_id") or event.get("role", ""),
                    "message_id": msg_id,
                    "content": chunk_content,
                    "author_name": payload.get("author_name", ""),
                    "phase": event.get("phase", ""),
                }

        if not responses:
            return

        # Build name lookup
        name_map = dict(zip(teammate_ids, tm_names))

        # Build avatar lookup from teammate cache → DB fallback
        avatar_map = {}
        from sqlalchemy import select as _select
        from backend.models import Teammate as _Teammate
        from backend.database import async_session as _avatar_session
        for tm_id in teammate_ids:
            tm_data = teammate_cache.get(tm_id)
            if tm_data and tm_data.get("avatar_emoji"):
                avatar_map[tm_id] = tm_data["avatar_emoji"]
            else:
                async with _avatar_session() as sess:
                    tm_result = await sess.execute(_select(_Teammate).where(_Teammate.id == tm_id))
                    tm_obj = tm_result.scalar_one_or_none()
                    avatar_map[tm_id] = tm_obj.avatar_emoji if tm_obj else "🤖"

        async with async_session() as sess:
            for resp in responses.values():
                tm_id = resp["teammate_id"]
                msg_id = resp.get("message_id", "")
                tm_name = name_map.get(tm_id, "Teammate")
                tm_avatar = avatar_map.get(tm_id, "🤖")
                ai_msg = Message(
                    channel_id=channel_id, role="ai",
                    author_name=tm_name,
                    author_id=tm_id,          # LEGACY — kept for existing rows
                    teammate_id=tm_id,         # unified field
                    message_id=msg_id,        # per-teammate uuid key
                    avatar_emoji=tm_avatar,
                    content=resp["content"],
                    status="replied",
                )
                sess.add(ai_msg)
            await sess.commit()
            message_cache.invalidate(channel_id)
            logger.info(f"Team response saved ({len(responses)} individual messages)")

        # ── Phase 4: Store conversation memory ──
        try:
            response_summary = " | ".join(
                f"{name_map.get(r['teammate_id'], '?')}: {r['content'][:100]}"
                for r in responses.values()
            )
            from backend.services.memory.memory_context import get_memory_context
            await get_memory_context().store_turn(
                channel_id=channel_id,
                user_message=str(content or "")[:500],
                response_summary=response_summary[:500],
            )
        except Exception as mem_err:
            logger.debug(f"[MEMORY] Chat memory write skipped: {mem_err}")

        # ── Task 7: Store per-teammate brain fragments from chat ──
        # ponytail: store each teammate's response as a brain:preferences
        # fragment. The BrainPage shows this immediately; BrainLoader injects
        # it into the teammate's system prompt on next interaction.
        # No LLM extraction — the response content IS the record.
        try:
            from backend.services.brain.fragment_store import (
                get_brain_fragment_store, BrainFragment,
            )
            bstore = get_brain_fragment_store()
            for resp in responses.values():
                tm_id = resp["teammate_id"]
                content = resp.get("content", "").strip()
                if not content or len(content) < 10:
                    continue
                frag = BrainFragment(
                    teammate_id=tm_id,
                    fragment_type="brain:preferences",
                    content=content[:300],
                    confidence=0.6,
                    source="chat",
                )
                await bstore.store(frag)
            if responses:
                logger.debug(f"[BRAIN] stored {len(responses)} chat fragments")
        except Exception as brain_err:
            logger.debug(f"[BRAIN] chat fragment write skipped: {brain_err}")

        # ── Phase 28: parse AI reply for explicit [TASK] directives → board ──
        # ponytail: best-effort. A parse failure must never break message save.
        try:
            from backend.services.board_task_parser import create_board_tasks_from_reply
            full_reply = " | ".join(r["content"] for r in responses.values())
            await create_board_tasks_from_reply(channel_id, full_reply, created_by="ai")
        except Exception as board_err:
            logger.debug(f"[BOARD-TASK] directive parse skipped: {board_err}")

    except Exception as e:
        logger.error(f"Failed to save team response: {e}", exc_info=True)


async def _save_ai_response_to_db(
    full_response: str,
    channel_id: str,
    teammate_id: str,
    tm_name: str,
    all_messages: list,
    content: Any,
    provider: str,
    model: str,
    api_key: str = None,
    base_url: str = None,
):
    """Save AI response to database (called from background task) — kept for compat"""
    try:
        async with async_session() as sess:
            ai_msg = Message(
                channel_id=channel_id, role="ai",
                author_name=tm_name, author_id=teammate_id,
                content=full_response,
            )
            sess.add(ai_msg)
            await sess.commit()
            message_cache.invalidate(channel_id)
            logger.info(f"AI response saved: {len(full_response)} chars")

        # Memory write-back (non-blocking) — memory kernel is not yet wired
        logger.debug(f"Memory turn recorded: channel={channel_id} teammate={teammate_id} content_len={len(full_response)}")
    except Exception as e:
        logger.error(f"Failed to save AI response: {e}")
