"""
Message & chat routes — streaming AI response with separated cache/memory architecture.

Architecture:
  CACHE LAYER (static)  → cache_key.py + cache_prefix_builder.py
  DYNAMIC LAYER         → context_builder.py
  MEMORY ENGINE         → memory_store.py + memory_retriever.py + memory_summarizer.py
  LLM RUNTIME           → ai_service.py (stream_ai_response + warmup_cache)

Flow:
  1. compute_cache_key(system_prompt) → static key
  2. build_fixed_prefix(system_prompt, recent_turns, current_input) → 9 messages
  3. warmup_cache(system_prompt) → prime DeepSeek cache entry
  4. stream_ai_response(system_prompt, messages) → LLM call
  5. process_conversation_turn() → memory write-back
"""
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models import Message, Channel, Teammate, APIKey
from backend.services.ai_service import stream_ai_response, warmup_cache
from backend.services.cache_prefix_builder import build_fixed_prefix, extract_recent_turns
from backend.services.memory_summarizer import process_conversation_turn, SUMMARY_INTERVAL
from backend.services.cache_warmup_service import is_warmed_up, mark_warmed_up
from backend.cache import message_cache, teammate_cache, apikey_cache

logger = logging.getLogger("messages")

router = APIRouter(prefix="/api/messages", tags=["messages"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

WARMUP_ENABLED = True


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
    ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
    if not ch_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Channel not found")

    ext = os.path.splitext(file.filename or "file")[1] or ""
    safe_name = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    content_bytes = await file.read()
    with open(file_path, "wb") as f:
        f.write(content_bytes)

    msg = Message(
        channel_id=channel_id, role="user", author_name=author_name,
        content=f"[Uploaded: {file.filename}]",
        attachments=[{
            "filename": file.filename or "file", "saved_as": safe_name,
            "size": len(content_bytes), "mime": file.content_type or "application/octet-stream",
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
    teammate_id = data.get("teammate_id")
    attachments = data.get("attachments")
    skip_user_save = data.get("skip_user_save", False)

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

    if not teammate_id:
        return {"user_message_id": user_msg_id}

    # ── Load teammate (cache-first) ──
    teammate = teammate_cache.get(teammate_id)
    if teammate is not None:
        tm_system_prompt = teammate["system_prompt"]
        tm_model_provider = teammate["model_provider"]
        tm_model_name = teammate["model_name"]
        tm_api_key_ref = teammate["api_key_ref"]
        tm_name = teammate["name"]
    else:
        t_result = await db.execute(select(Teammate).where(Teammate.id == teammate_id))
        tm = t_result.scalar_one_or_none()
        if not tm:
            raise HTTPException(status_code=404, detail="Teammate not found")
        tm_system_prompt = tm.system_prompt
        tm_model_provider = tm.model_provider
        tm_model_name = tm.model_name
        tm_api_key_ref = tm.api_key_ref
        tm_name = tm.name
        teammate_cache.set(teammate_id, {
            "id": tm.id, "name": tm.name, "role": tm.role,
            "avatar_emoji": tm.avatar_emoji, "system_prompt": tm.system_prompt,
            "model_provider": tm.model_provider, "model_name": tm.model_name,
            "api_key_ref": tm.api_key_ref,
        })

    if not tm_api_key_ref:
        raise HTTPException(status_code=400, detail="Teammate has no API key configured")

    # ── Load API key (cache-first) ──
    apikey = apikey_cache.get(tm_api_key_ref)
    if apikey is not None:
        api_key_val = apikey["api_key"]
        base_url_val = apikey["base_url"]
    else:
        k_result = await db.execute(select(APIKey).where(APIKey.id == tm_api_key_ref))
        apikey_obj = k_result.scalar_one_or_none()
        if not apikey_obj or not apikey_obj.api_key:
            raise HTTPException(status_code=400, detail="API key not found")
        api_key_val = apikey_obj.api_key
        base_url_val = apikey_obj.base_url
        apikey_cache.set(tm_api_key_ref, {
            "id": apikey_obj.id, "provider": apikey_obj.provider,
            "api_key": apikey_obj.api_key, "base_url": apikey_obj.base_url,
        })

    # ── Load message history ──
    cached_msgs = message_cache.get(channel_id)
    if cached_msgs is not None:
        all_messages = cached_msgs
    else:
        hist_result = await db.execute(
            select(Message).where(Message.channel_id == channel_id).order_by(Message.created_at)
        )
        all_messages = list(hist_result.scalars().all())
        message_cache.set(channel_id, all_messages)

    # ── Step 1: Build fixed-prefix messages (9 messages, structure stable) ──
    recent_turns = extract_recent_turns(all_messages, k=3)
    fixed_messages = build_fixed_prefix(
        system_prompt=tm_system_prompt,
        recent_turns=recent_turns,
        current_content=content,
    )

    logger.info(
        f"LLM call: channel={channel_id[:8]}... teammate={tm_name} "
        f"messages={len(fixed_messages)} "
        f"system_hash={hash(tm_system_prompt) & 0xFFFFFFFF:08x}"
    )

    # ── Step 2: Cache warming (static only, 9 messages) ──
    if WARMUP_ENABLED and not is_warmed_up(teammate_id, channel_id):
        logger.info(f"Cache warming: priming DeepSeek cache for {tm_name}")
        try:
            # Warmup 使用完整的 9 条 messages（包含 system）
            # 这样 DeepSeek 建立的 cache entry 与真实请求一致
            warmup_ok = await warmup_cache(
                system_prompt=tm_system_prompt,
                provider=tm_model_provider,
                model=tm_model_name,
                api_key=api_key_val,
                base_url=base_url_val,
            )
            if warmup_ok:
                mark_warmed_up(teammate_id, channel_id)
        except Exception as e:
            logger.warning(f"Cache warming failed (non-fatal): {e}")

    # ── Step 3: Stream the actual response ──
    # 使用列表收集所有 chunk，在流式响应结束后同步保存
    collected_chunks = []

    async def generate():
        try:
            _gen = stream_ai_response(
                system_prompt=tm_system_prompt,
                messages=fixed_messages[1:],
                provider=tm_model_provider,
                model=tm_model_name,
                api_key=api_key_val,
                base_url=base_url_val,
                channel_id=channel_id,
                teammate_id=teammate_id,
            )
            async for chunk in _gen:
                collected_chunks.append(chunk)
                yield chunk
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"\n\n⚠️ AI Error: {str(e)}"

    # Start streaming response
    response = StreamingResponse(generate(), media_type="text/plain")

    # Use BackgroundTask to save AI response after stream completes
    # Note: collected_chunks is a shared list; after generate() completes, it contains all chunks
    async def save_after_stream():
        """Background task: save AI response after stream completes"""
        await asyncio.sleep(0.1)  # Brief delay to ensure all chunks collected
        full_response = "".join(collected_chunks)
        if not full_response.strip():
            logger.warning("Empty AI response, skipping save")
            return
        await _save_ai_response_to_db(
            full_response=full_response,
            channel_id=channel_id,
            teammate_id=teammate_id,
            tm_name=tm_name,
            all_messages=all_messages,
            content=content,
            provider=tm_model_provider,
            model=tm_model_name,
            api_key=api_key_val,
            base_url=base_url_val,
        )

    import asyncio
    from starlette.background import BackgroundTask

    response.background = BackgroundTask(save_after_stream)
    return response


# ── Helper: Save AI response to DB (used by background task) ──

async def _save_ai_response_to_db(
    full_response: str,
    channel_id: str,
    teammate_id: str,
    tm_name: str,
    all_messages: list,
    content: str,
    provider: str,
    model: str,
    api_key: str = None,
    base_url: str = None,
):
    """Save AI response to database (called from background task)"""
    try:
        # Convert all_messages to dict list
        history_dicts = []
        for m in all_messages:
            if isinstance(m, dict):
                history_dicts.append({"role": m.get("role", ""), "content": m.get("content", "")})
            else:
                history_dicts.append({"role": getattr(m, "role", ""), "content": getattr(m, "content", "")})

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

        # Memory write-back (non-blocking)
        new_messages = history_dicts + [
            {"role": "user", "content": content},
            {"role": "ai", "content": full_response},
        ]
        try:
            await process_conversation_turn(
                channel_id=channel_id,
                teammate_id=teammate_id,
                messages=new_messages,
                msg_count=len(all_messages) + 2,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception as e:
            logger.warning(f"Memory write-back failed (non-fatal): {e}")
    except Exception as e:
        logger.error(f"Failed to save AI response: {e}")
