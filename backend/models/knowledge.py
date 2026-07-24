"""Knowledge/RAG models — file uploads, chunks, attachment contexts."""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from backend.database import Base
from ._helpers import gen_uuid, utcnow


class FileUpload(Base):
    __tablename__ = "file_uploads"

    id = Column(String, primary_key=True, default=gen_uuid)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    size = Column(String, default="0")
    user_id = Column(String, nullable=False, index=True)
    status = Column(String, default="pending")
    error_message = Column(Text, default="")
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    chunks = relationship("FileChunk", back_populates="file", cascade="all, delete-orphan",
                           order_by="FileChunk.index")


class FileChunk(Base):
    __tablename__ = "file_chunks"

    id = Column(String, primary_key=True, default=gen_uuid)
    file_id = Column(String, ForeignKey("file_uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    index = Column("index", String, default="0")
    embedding = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

    file = relationship("FileUpload", back_populates="chunks")


class AttachmentContextModel(Base):
    __tablename__ = "attachment_contexts"

    id = Column(String, primary_key=True, default=gen_uuid)
    file_id = Column(String, nullable=False, index=True)
    content_hash = Column(String, nullable=False, index=True)
    type = Column(String, default="text")
    summary = Column(Text, default="")
    chunks_json = Column(Text, default="[]")
    entities_json = Column(Text, default="[]")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )
