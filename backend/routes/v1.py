"""
routes/v1.py — Simplified Public API

Only 3 endpoints:
  POST /v1/chat     — Send a message, get AI response (streaming)
  POST /v1/upload   — Upload a file
  GET  /v1/health   — Health check
"""
import time
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/v1", tags=["v1-public"])


class ChatRequest(BaseModel):
    channel_id: str
    message: str
    stream: Optional[bool] = True

    class Config:
        json_schema_extra = {
            "example": {
                "channel_id": "chan_abc123",
                "message": "Help me analyze this data",
                "stream": True,
            }
        }


class UploadResponse(BaseModel):
    status: str
    filename: str
    size: int
    message: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    latency: str = "0ms"


@router.post("/chat")
async def v1_chat(req: ChatRequest, request: Request):
    """
    Send a message to the team and get a streaming collaborative response.
    Uses team_collaboration engine for multi-teammate synthesis.
    """
    from backend.routes.messages import send_message

    if req.stream:
        return await send_message(
            channel_id=req.channel_id,
            data={"content": req.message, "author_name": "You"},
        )
    else:
        # Non-streaming: collect full response
        from backend.services.pipeline import run_pipeline
        from backend.services.key_vault_service import get_key_by_provider

        # Get API key from Key Vault (decrypted in memory)
        key_info = await get_key_by_provider("openrouter")
        api_key, base_url = (key_info[1], key_info[2]) if key_info else ("", "")

        response_text = await run_pipeline(
            channel_id=req.channel_id,
            user_message=req.message,
            api_key=api_key,
            base_url=base_url or None,
        )

        return {
            "status": "ok",
            "response": response_text,
            "latency": "0ms",
        }


@router.post("/upload")
async def v1_upload(request: Request):
    """Upload a file for processing."""
    from backend.routes.messages import _do_upload_file
    from backend.database import async_session
    from fastapi import UploadFile, File, Form
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    author_name = form.get("author_name", "You")
    channel_id = form.get("channel_id")
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required")
    async with async_session() as db:
        return await _do_upload_file(
            channel_id=channel_id,
            file=file,
            author_name=str(author_name),
            db=db,
        )


@router.get("/health", response_model=HealthResponse)
async def v1_health():
    """Public API health check."""
    return HealthResponse(
        status="ok",
        service="AI Team Hub",
        version="3.0.0",
    )
