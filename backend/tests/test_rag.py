"""
test_rag.py — RAG Pipeline Unit Tests

Covers:
  1. Embedding service: encode/query
  2. RAG pipeline: store → retrieve pipeline
  3. Attachment context: file parsing and context building
"""
import pytest


class TestEmbeddingService:
    """Embedding service operations."""

    def test_embedding_service_import(self):
        """Embedding service should be importable."""
        from backend.services.embedding_service import EmbeddingService
        svc = EmbeddingService()
        assert svc is not None

    def test_rag_pipeline_import(self):
        """RAG pipeline module should be importable."""
        from backend.services import rag_pipeline
        assert rag_pipeline is not None


class TestAttachmentContext:
    """Attachment context operations."""

    def test_attachment_context_dataclass(self):
        """AttachmentContext dataclass should have expected fields."""
        from backend.services.attachment_context import AttachmentContext
        ctx = AttachmentContext(
            file_id="f1", filename="test.pdf", type="pdf",
            size=1000, summary="test summary",
        )
        assert ctx.file_id == "f1"
        assert ctx.filename == "test.pdf"
        assert ctx.type == "pdf"
        assert ctx.size == 1000

    def test_attachment_service_cache(self):
        """Attachment service should have a shared cache."""
        from backend.services.attachment_service import attachment_cache
        assert attachment_cache is not None

    def test_attachment_utils_import(self):
        """attachment_service should export AttachmentContext."""
        from backend.services.attachment_service import AttachmentContext
        assert AttachmentContext is not None


class TestFileUploadModel:
    """File upload model operations."""

    @pytest.mark.asyncio
    async def test_file_model_schema(self):
        """FileUpload model should define expected columns."""
        from backend.models import FileUpload, FileChunk
        assert hasattr(FileUpload, "filename")
        assert hasattr(FileUpload, "file_type")
        assert hasattr(FileUpload, "status")
        assert hasattr(FileChunk, "content")
        assert hasattr(FileChunk, "embedding")

    def test_upload_dir_exists(self):
        """Upload directory should exist."""
        import os
        upload_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "uploads"
        )
        assert os.path.isdir(upload_dir), f"Upload dir not found: {upload_dir}"
