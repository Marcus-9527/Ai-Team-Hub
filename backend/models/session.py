"""Session 层数据模型：session_triggers + session_turns + session_events

- 一次用户消息（或一次 task 触发）= 一个 trigger
- 该 trigger 下每个队友的反应（回复或 cede）= 一个 turn
- 每个 trigger 包含有序事件流，记录 AI 组织内所有动作
- trigger : turn = 1:N, trigger : event = 1:N, turn : event = 1:N
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index, JSON, Text
from sqlalchemy.orm import relationship, backref

from backend.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TriggerType(str, Enum):
    CHAT = "chat"
    TASK = "task"
    AUTOMATION = "automation"
    CALENDAR = "calendar"
    SCHEDULE_WAKEUP = "schedule_wakeup"
    SYSTEM = "system"


class TurnAction(str, Enum):
    RESPONDED = "responded"
    CEDED = "ceded"


class SessionTrigger(Base):
    __tablename__ = "session_triggers"

    id = Column(String, primary_key=True, default=_uuid)
    trigger_type = Column(String, nullable=False, default=TriggerType.CHAT.value)
    channel_id = Column(String, nullable=True, index=True)
    user_msg_id = Column(String, nullable=True)
    source_ref_id = Column(String, nullable=True, index=True)
    workspace_id = Column(String, nullable=True, index=True)
    trigger_time = Column(DateTime(timezone=True), nullable=False, default=_now)
    task_id = Column(String, nullable=True, index=True)
    teammate_id = Column(String, nullable=True, index=True)
    run_id = Column(String, ForeignKey("organization_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String, nullable=False, default="active")
    ended_at = Column(DateTime(timezone=True), nullable=True)

    turns = relationship(
        "SessionTurn", back_populates="trigger", cascade="all, delete-orphan",
    )
    events = relationship(
        "SessionEvent", back_populates="trigger", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_session_triggers_channel_time", "channel_id", "trigger_time"),
    )


class SessionEvent(Base):
    """Session 事件流：记录 AI 组织内部的每个动作。

    trigger 下的有序时间线，包含 turn 边界事件和粒度的工具调用等。
    """
    __tablename__ = "session_events"

    id = Column(String, primary_key=True, default=_uuid)
    trigger_id = Column(
        String, ForeignKey("session_triggers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    turn_id = Column(
        String, ForeignKey("session_turns.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    event_type = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=_now)

    trigger = relationship("SessionTrigger", back_populates="events")
    turn = relationship("SessionTurn", back_populates="events")

    __table_args__ = (
        Index("ix_session_events_trigger_time", "trigger_id", "timestamp"),
    )


class SessionTurn(Base):
    __tablename__ = "session_turns"

    id = Column(String, primary_key=True, default=_uuid)
    trigger_id = Column(
        String, ForeignKey("session_triggers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    teammate_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)  # TurnAction: responded / ceded
    action_type = Column(String, nullable=True)  # OrganizationAction: respond/delegate/tool_call/execute/complete
    response_msg_id = Column(String, nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=False, default=_now)
    end_time = Column(DateTime(timezone=True), nullable=True)
    turn_type = Column(String, nullable=True)
    execution_id = Column(String, nullable=True, index=True)
    failure = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    trigger = relationship("SessionTrigger", back_populates="turns")
    events = relationship("SessionEvent", back_populates="turn", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_session_turns_teammate_time", "teammate_id", "start_time"),
    )
