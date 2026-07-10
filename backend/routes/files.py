"""
routes/files.py — File Upload + Management API

Endpoints:
  POST /v1/files/upload       — Upload file for RAG processing
  GET  /v1/files/{file_id}    — File details + chunk list
  GET  /v1/files             — List user files
  DELETE /v1/files/{file_id}  — Delete file + chunks
"""
import io
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any

router = APIRouter(prefix="/v1/files", tags=["files-rag"])

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════

class FileUploadResponse(BaseModel):
    file_id: str = ""
    filename: str = ""
    file_type: str = ""
    size: int = 0
    user_id: str = ""
    status: str = "pending"
    chunk_count: int = 0
    message: str = ""


class ChunkInfo(BaseModel):
    chunk_id: str
    index: int
    content_preview: str = ""


class FileDetailResponse(BaseModel):
    file_id: str
    filename: str
    file_type: str
    size: int
    user_id: str
    status: str
    chunk_count: int
    chunks: List[ChunkInfo] = []
    created_at: str = ""


class FileListItem(BaseModel):
    file_id: str
    filename: str
    file_type: str
    size: int
    status: str
    chunk_count: int = 0
    created_at: str = ""


class FileListResponse(BaseModel):
    files: List[FileListItem] = []
    total: int = 0


class DeleteResponse(BaseModel):
    status: str = "ok"
    file_id: str = ""
    chunks_deleted: int = 0


# ═══════════════════════════════════════════════════════════
# Helper: Get user_id from request
# ═══════════════════════════════════════════════════════════

def get_user_id(request: Request) -> str:
    """Extract user_id from request context or header."""
    # Try auth middleware first
    if hasattr(request.state, "tenant_id") and request.state.tenant_id:
        return request.state.tenant_id
    # Fallback to header
    user_id = request.headers.get("X-User-ID", "")
    if user_id:
        return user_id
    # Development fallback
    return "local-dev-user"


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Upload a file for RAG processing.

    Supported types: PDF, DOCX, TXT, MD
    """
    from backend.database import async_session
    from backend.models import FileUpload, FileChunk
    from backend.services.rag_pipeline import process_file
    from backend.services.embedding_service import get_embedding_service, embed_text
    from sqlalchemy import select
    import json

    user_id = get_user_id(request)

    # Validate file type
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_types = {"pdf", "docx", "txt", "md"}
    if ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}。支持: {', '.join(allowed_types)}",
        )

    # Read file content
    content = await file.read()
    size = len(content)

    # Create DB record
    file_id = None
    async with async_session() as session:
        db_file = FileUpload(
            filename=filename,
            file_type=ext,
            size=str(size),
            user_id=user_id,
            status="processing",
        )
        session.add(db_file)
        await session.flush()
        file_id = db_file.id

        # Process file (extract + chunk)
        result = await process_file(content, file_id, ext)

        if result["status"] == "error":
            db_file.status = "error"
            db_file.error_message = result.get("error", "Unknown error")
            await session.commit()
            raise HTTPException(status_code=422, detail=f"文件处理失败: {result['error']}")

        # Store chunks with embeddings
        for chunk in result["chunks"]:
            embedding_vec = embed_text(chunk.content)
            db_chunk = FileChunk(
                id=chunk.chunk_id,
                file_id=file_id,
                content=chunk.content,
                index=str(chunk.index),
                embedding=json.dumps(embedding_vec),
                metadata_json=chunk.metadata,
            )
            session.add(db_chunk)

        db_file.status = "ready"
        db_file.chunk_count = result["chunk_count"]
        await session.commit()

    return FileUploadResponse(
        file_id=file_id,
        filename=filename,
        file_type=ext,
        size=size,
        user_id=user_id,
        status="ready",
        chunk_count=result["chunk_count"],
        message=f"文件上传成功，已生成 {result['chunk_count']} 个文本块",
    )


@router.get("/{file_id}", response_model=FileDetailResponse)
async def get_file_detail(file_id: str, request: Request):
    """Get file details with chunk list."""
    from backend.database import async_session
    from backend.models import FileUpload, FileChunk
    from sqlalchemy import select

    user_id = get_user_id(request)

    async with async_session() as session:
        result = await session.execute(
            select(FileUpload).where(FileUpload.id == file_id)
        )
        file_obj = result.scalar_one_or_none()

        if not file_obj:
            raise HTTPException(status_code=404, detail="文件不存在")

        # User isolation
        if file_obj.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问此文件")

        # Load chunks
        chunk_result = await session.execute(
            select(FileChunk)
            .where(FileChunk.file_id == file_id)
            .order_by(FileChunk.index)
        )
        chunks = chunk_result.scalars().all()

        return FileDetailResponse(
            file_id=file_obj.id,
            filename=file_obj.filename,
            file_type=file_obj.file_type,
            size=int(file_obj.size),
            user_id=file_obj.user_id,
            status=file_obj.status,
            chunk_count=len(chunks),
            chunks=[
                ChunkInfo(
                    chunk_id=c.id,
                    index=int(c.index),
                    content_preview=c.content[:100] + "..." if len(c.content) > 100 else c.content,
                )
                for c in chunks
            ],
            created_at=str(file_obj.created_at),
        )


@router.get("", response_model=FileListResponse)
async def list_files(request: Request):
    """List all files for the current user."""
    from backend.database import async_session
    from backend.models import FileUpload
    from sqlalchemy import select, func

    user_id = get_user_id(request)

    async with async_session() as session:
        # Count
        count_result = await session.execute(
            select(func.count(FileUpload.id)).where(FileUpload.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # List
        result = await session.execute(
            select(FileUpload)
            .where(FileUpload.user_id == user_id)
            .order_by(FileUpload.created_at.desc())
        )
        files = result.scalars().all()

        return FileListResponse(
            files=[
                FileListItem(
                    file_id=f.id,
                    filename=f.filename,
                    file_type=f.file_type,
                    size=int(f.size),
                    status=f.status,
                    created_at=str(f.created_at),
                )
                for f in files
            ],
            total=total,
        )


@router.delete("/{file_id}", response_model=DeleteResponse)
async def delete_file(file_id: str, request: Request):
    """Delete a file and all its chunks."""
    from backend.database import async_session
    from backend.models import FileUpload, FileChunk
    from sqlalchemy import select, delete

    user_id = get_user_id(request)

    async with async_session() as session:
        result = await session.execute(
            select(FileUpload).where(FileUpload.id == file_id)
        )
        file_obj = result.scalar_one_or_none()

        if not file_obj:
            raise HTTPException(status_code=404, detail="文件不存在")

        if file_obj.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权删除此文件")

        # Delete chunks first (cascade)
        chunk_result = await session.execute(
            select(FileChunk).where(FileChunk.file_id == file_id)
        )
        chunks = chunk_result.scalars().all()
        chunk_count = len(chunks)

        await session.execute(
            delete(FileChunk).where(FileChunk.file_id == file_id)
        )
        await session.delete(file_obj)
        await session.commit()

    return DeleteResponse(
        status="ok",
        file_id=file_id,
        chunks_deleted=chunk_count,
    )
