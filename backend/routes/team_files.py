"""
routes/team_files.py — Teammate Chat with RAG Context Injection

Extends the existing /v1/team/chat endpoint with file context.

Endpoint:
  POST /v1/team/chat-with-files — Chat with uploaded file context
"""
import time
import logging
import json
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/team", tags=["team-files"])

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════

class TeamFilesChatRequest(BaseModel):
    message: str = Field(..., description="User message / question")
    session_id: Optional[str] = None
    file_id: Optional[str] = Field(None, description="Specific file to query (optional)")
    top_k: int = Field(3, description="Number of context chunks to inject", ge=1, le=10)
    mode: Optional[str] = "auto"

    class Config:
        json_schema_extra = {
            "example": {
                "message": "What is the project progress?",
                "top_k": 3,
            }
        }


class TeamFilesChatResponse(BaseModel):
    session_id: str
    status: str
    response: str
    context_used: bool
    sources: List[Dict[str, Any]] = []
    latency_ms: float = 0
    message: str = ""


# ═══════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════

def get_user_id(request: Request) -> str:
    if hasattr(request.state, "tenant_id") and request.state.tenant_id:
        return request.state.tenant_id
    user_id = request.headers.get("X-User-ID", "")
    if user_id:
        return user_id
    return "local-dev-user"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


# ═══════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════

@router.post("/chat-with-files", response_model=TeamFilesChatResponse)
async def teammate_chat_with_files(req: TeamFilesChatRequest, request: Request):
    """
    Teammate chat with RAG file context injection.

    1. Embed user message
    2. Retrieve relevant chunks from user's files
    3. Inject CONTEXT into teammate prompt
    4. Generate response via Team Engine executor
    """
    import uuid
    from backend.database import async_session
    from backend.models import FileUpload, FileChunk
    from backend.services.embedding_service import get_embedding_service
    from sqlalchemy import select

    start = time.time()
    session_id = req.session_id or str(uuid.uuid4())[:8]
    user_id = get_user_id(request)

    # Step 1: Retrieve RAG context
    embed_svc = get_embedding_service()
    query_embedding = embed_svc.embed(req.message)

    context_text = ""
    sources = []
    context_used = False

    async with async_session() as session:
        # Load user's chunks
        if req.file_id:
            # Verify ownership
            file_result = await session.execute(
                select(FileUpload).where(
                    FileUpload.id == req.file_id,
                    FileUpload.user_id == user_id,
                )
            )
            if not file_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="文件不存在或无权访问")

            chunk_result = await session.execute(
                select(FileChunk)
                .where(FileChunk.file_id == req.file_id)
                .order_by(FileChunk.index)
            )
        else:
            chunk_result = await session.execute(
                select(FileChunk, FileUpload)
                .join(FileUpload, FileChunk.file_id == FileUpload.id)
                .where(FileUpload.user_id == user_id)
                .order_by(FileChunk.file_id, FileChunk.index)
            )

        rows = chunk_result.all()
        chunks = []
        for row in rows:
            if req.file_id:
                chunk = row
                chunks.append({
                    "chunk_id": chunk.id,
                    "file_id": chunk.file_id,
                    "content": chunk.content,
                    "index": int(chunk.index),
                    "embedding": json.loads(chunk.embedding) if chunk.embedding else None,
                    "user_id": user_id,
                })
            else:
                chunk, file_upload = row
                chunks.append({
                    "chunk_id": chunk.id,
                    "file_id": chunk.file_id,
                    "content": chunk.content,
                    "index": int(chunk.index),
                    "embedding": json.loads(chunk.embedding) if chunk.embedding else None,
                    "user_id": file_upload.user_id,
                })

    # Step 2: Search for relevant context
    if chunks:
        results = embed_svc.search(query_embedding, chunks, top_k=req.top_k, user_id=user_id)
        if results:
            context_parts = []
            for i, r in enumerate(results):
                context_parts.append(f"[Source {i+1}] {r['content']}")
                sources.append({
                    "file_id": r["file_id"],
                    "chunk_id": r["chunk_id"],
                    "score": r["score"],
                })
            context_text = "\n\n".join(context_parts)
            context_used = True

    # Step 3: Build prompt with context
    if context_text:
        full_prompt = f"""CONTEXT:
{context_text}

QUESTION:
{req.message}

Based on the context above, provide a helpful answer. If the context doesn't contain relevant information, say so."""
    else:
        full_prompt = req.message

    # Step 4: Execute via Team Engine
    try:
        from backend.routes.maeos import get_runtime
        runtime = get_runtime()
        task_id = await runtime.submit(
            description=full_prompt,
            priority=2,
            wait=True,
        )
        response_text = f"Task submitted with RAG context, ID: {task_id}"
    except Exception as e:
        # Fallback: return context summary if Team Engine unavailable
        logger.warning(f"Team Engine unavailable: {e}")
        if context_used:
            response_text = f"基于文件内容检索到以下相关信息：\n\n{context_text}\n\n（Team Engine 执行器暂不可用，以上为原始检索结果）"
        else:
            response_text = "未找到相关文件内容。请先上传文件。"

    elapsed = round((time.time() - start) * 1000, 2)

    return TeamFilesChatResponse(
        session_id=session_id,
        status="ok",
        response=response_text,
        context_used=context_used,
        sources=sources,
        latency_ms=elapsed,
        message="RAG context retrieved and injected" if context_used else "No file context found",
    )
