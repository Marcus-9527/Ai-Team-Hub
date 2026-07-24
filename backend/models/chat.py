"""Chat models — channels, teammates, messages, templates."""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Float, Integer
from sqlalchemy.orm import relationship

from backend.database import Base
from ._helpers import gen_uuid, utcnow


class Channel(Base):
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    workspace_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Many-to-many: teammates in this channel
    teammate_ids = Column(JSON, default=list)

    messages = relationship("Message", back_populates="channel", cascade="all, delete-orphan",
                            order_by="Message.created_at")


class Teammate(Base):
    __tablename__ = "teammates"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    role = Column(String, default="assistant")
    avatar_emoji = Column(String, default="🤖")
    system_prompt = Column(Text, default="You are a helpful AI assistant.")
    model_provider = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    api_key_ref = Column(String, nullable=True)
    workspace_id = Column(String, nullable=True, index=True)
    skills = Column(JSON, default=list)
    capabilities = Column(JSON, default=list)
    success_rate = Column(Float, default=0.0)
    average_score = Column(Float, default=0.0)
    execution_count = Column(Integer, default=0)
    strengths = Column(JSON, default=list)
    weaknesses = Column(JSON, default=list)
    learned_patterns = Column(JSON, default=list)
    failed_patterns = Column(JSON, default=list)
    preferred_tools = Column(JSON, default=list)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "avatar_emoji": self.avatar_emoji,
            "system_prompt": self.system_prompt,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "api_key_ref": self.api_key_ref,
            "skills": self.skills or [],
            "capabilities": self.capabilities or [],
            "success_rate": self.success_rate or 0.0,
            "average_score": self.average_score or 0.0,
            "execution_count": self.execution_count or 0,
            "strengths": self.strengths or [],
            "weaknesses": self.weaknesses or [],
            "learned_patterns": self.learned_patterns or [],
            "failed_patterns": self.failed_patterns or [],
            "preferred_tools": self.preferred_tools or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    channel_id = Column(String, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)
    author_name = Column(String, nullable=False)
    author_id = Column(String, nullable=True)
    teammate_id = Column(String, nullable=True)
    message_id = Column(String, nullable=True)
    avatar_emoji = Column(String, default="🤖")
    status = Column(String, default="unread")
    content = Column(Text, default="")
    attachments = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    channel = relationship("Channel", back_populates="messages")


class TeammateTemplate(Base):
    __tablename__ = "teammate_templates"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)
    description = Column(Text, default="")
    identity = Column(String, default="")
    system_prompt = Column(Text, default="")
    skills = Column(JSON, default=list)
    tools = Column(JSON, default=list)
    memory_schema = Column(JSON, default=dict)
    automation_defaults = Column(JSON, default=dict)
    avatar_emoji = Column(String, default="🤖")
    model_provider = Column(String, default="openrouter")
    model_name = Column(String, default="openrouter/auto")
    created_at = Column(DateTime, default=utcnow)
