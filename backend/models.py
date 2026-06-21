"""
SQLAlchemy models for AI Team Hub.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from backend.database import Base


def gen_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Many-to-many: teammates in this channel
    teammate_ids = Column(JSON, default=list)   # list of teammate UUID strings

    messages = relationship("Message", back_populates="channel", cascade="all, delete-orphan",
                            order_by="Message.created_at")


class Teammate(Base):
    __tablename__ = "teammates"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    role = Column(String, default="assistant")
    avatar_emoji = Column(String, default="🤖")
    system_prompt = Column(Text, default="You are a helpful AI assistant.")
    model_provider = Column(String, nullable=False)   # e.g. "openai", "deepseek", "anthropic"
    model_name = Column(String, nullable=False)        # e.g. "gpt-4o", "deepseek-chat"
    api_key_ref = Column(String, nullable=True)        # reference to an APIKey id
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class APIKey(Base):
    __tablename__ = "apikeys"

    id = Column(String, primary_key=True, default=gen_uuid)
    provider = Column(String, nullable=False)    # "openai", "deepseek", "anthropic"
    label = Column(String, nullable=False)        # user-defined name
    api_key = Column(String, nullable=False)      # encrypted/simple store (MVP: plain)
    base_url = Column(String, nullable=True)      # custom endpoint
    created_at = Column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    channel_id = Column(String, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)         # "user" | "ai" | "system"
    author_name = Column(String, nullable=False)   # display name
    author_id = Column(String, nullable=True)      # teammate id if role=="ai"
    content = Column(Text, default="")
    attachments = Column(JSON, nullable=True)       # list of file metadata
    created_at = Column(DateTime, default=utcnow)

    channel = relationship("Channel", back_populates="messages")
