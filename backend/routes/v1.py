"""
routes/v1.py — Simplified Public API

Only 3 endpoints:
  POST /v1/chat     — Send a message, get AI response (always streaming)
  POST /v1/upload   — Upload a file
  GET  /v1/health   — Health check
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


router = APIRouter(prefix="/v1", tags=["v1-public"])


class ChatRequest(BaseModel):
    channel_id: str
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "channel_id": "chan_abc123",
                "message": "Help me analyze this data",
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
    Uses the OrganizationRuntime for multi-teammate synthesis.
    """
    from backend.routes.messages import send_message
    from backend.database import async_session

    async with async_session() as db:
        return await send_message(
            channel_id=req.channel_id,
            data={"content": req.message, "author_name": "You"},
            db=db,
        )


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
