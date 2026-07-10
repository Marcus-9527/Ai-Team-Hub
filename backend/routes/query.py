"""
routes/query.py — RAG Retrieval + Context Injection API

Endpoints:
  POST /v1/files/query          — Semantic search across uploaded files
  POST /v1/files/context        — Get RAG context for a query (for teammate injection)
"""
import time
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/files", tags=["files-rag"])

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    query: str = Field(..., description="Search query / user question")
    file_id: Optional[str] = Field(None, description="Limit search to specific file")
    top_k: int = Field(5, description="Number of results to return", ge=1, le=50)

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What is the project about?",
                "top_k": 5,
            }
        }


class QueryResult(BaseModel):
    content: str
    score: float
    file_id: str
    chunk_id: str
    index: int = 0


class QueryResponse(BaseModel):
    results: List[QueryResult]
    query: str
    total_found: int
    latency_ms: float = 0
    cached: bool = False


class ContextRequest(BaseModel):
    query: str = Field(..., description="User question to generate context for")
    top_k: int = Field(3, description="Number of context chunks", ge=1, le=10)
    file_id: Optional[str] = Field(None, description="Limit to specific file")


class ContextResponse(BaseModel):
    context: str
    sources: List[Dict[str, Any]]
    query: str
    token_count: int = 0


# ═══════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════

def get_user_id(request: Request) -> str:
    """Extract user_id from request context or header."""
    if hasattr(request.state, "tenant_id") and request.state.tenant_id:
        return request.state.tenant_id
    user_id = request.headers.get("X-User-ID", "")
    if user_id:
        return user_id
    return "local-dev-user"


def _estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English, ~1.5 for Chinese."""
    return max(1, len(text) // 3)


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════

@router.post("/query", response_model=QueryResponse)
async def query_files(req: QueryRequest, request: Request):
    """
    Semantic search across uploaded files.

    Embeds the query, performs cosine similarity against stored chunks,
    returns top-k most relevant chunks.
    """
    from backend.database import async_session
    from backend.models import FileUpload, FileChunk
    from backend.services.embedding_service import get_embedding_service, cosine_similarity
    from sqlalchemy import select
    import json

    start = time.time()
    user_id = get_user_id(request)

    # Get embedding service
    embed_svc = get_embedding_service()
    query_embedding = embed_svc.embed(req.query)

    # Load chunks (scoped by user, optionally by file)
    async with async_session() as session:
        if req.file_id:
            # Verify file belongs to user
            file_result = await session.execute(
                select(FileUpload).where(
                    FileUpload.id == req.file_id,
                    FileUpload.user_id == user_id,
                )
            )
            file_obj = file_result.scalar_one_or_none()
            if not file_obj:
                raise HTTPException(status_code=404, detail="文件不存在或无权访问")

            chunk_result = await session.execute(
                select(FileChunk)
                .where(FileChunk.file_id == req.file_id)
                .order_by(FileChunk.index)
            )
        else:
            # Load all user's chunks via join
            chunk_result = await session.execute(
                select(FileChunk, FileUpload)
                .join(FileUpload, FileChunk.file_id == FileUpload.id)
                .where(FileUpload.user_id == user_id)
                .order_by(FileChunk.file_id, FileChunk.index)
            )

        rows = chunk_result.all()

        # Build chunk list with embeddings
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

    # Perform search
    results = embed_svc.search(query_embedding, chunks, top_k=req.top_k, user_id=user_id)

    elapsed = round((time.time() - start) * 1000, 2)

    return QueryResponse(
        results=[
            QueryResult(
                content=r["content"],
                score=r["score"],
                file_id=r["file_id"],
                chunk_id=r["chunk_id"],
                index=r.get("index", 0),
            )
            for r in results
        ],
        query=req.query,
        total_found=len(results),
        latency_ms=elapsed,
    )


@router.post("/context", response_model=ContextResponse)
async def get_context(req: ContextRequest, request: Request):
    """
    Get RAG context formatted for teammate injection.

    Returns a formatted context string ready to be injected into
    teammate prompt with CONTEXT / QUESTION structure.
    """
    from backend.database import async_session
    from backend.models import FileUpload, FileChunk
    from backend.services.embedding_service import get_embedding_service
    from sqlalchemy import select
    import json

    user_id = get_user_id(request)
    embed_svc = get_embedding_service()
    query_embedding = embed_svc.embed(req.query)

    async with async_session() as session:
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

    # Search
    results = embed_svc.search(query_embedding, chunks, top_k=req.top_k, user_id=user_id)

    # Build context string
    context_parts = []
    sources = []
    for i, r in enumerate(results):
        context_parts.append(f"[Source {i+1}] {r['content']}")
        sources.append({
            "file_id": r["file_id"],
            "chunk_id": r["chunk_id"],
            "score": r["score"],
        })

    context_text = "\n\n".join(context_parts)
    token_count = _estimate_tokens(context_text)

    return ContextResponse(
        context=context_text,
        sources=sources,
        query=req.query,
        token_count=token_count,
    )
