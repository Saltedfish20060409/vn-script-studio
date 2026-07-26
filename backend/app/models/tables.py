from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")
    settings: Mapped[Optional["UserSettings"]] = relationship(
        back_populates="user", uselist=False
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="未命名剧本")
    genre: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    logline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner: Mapped["User"] = relationship(back_populates="projects")
    shares: Mapped[list["Share"]] = relationship(back_populates="project")
    agent_sessions: Mapped[list["AgentSession"]] = relationship(
        back_populates="project"
    )


class Share(Base):
    __tablename__ = "shares"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title_snapshot: Mapped[str] = mapped_column(String(255), default="")
    data_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="shares")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    messages: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    chat_memory: Mapped[str] = mapped_column(Text, default="")
    undo_stack: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="agent_sessions")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(16), default="day")
    font_scale: Mapped[float] = mapped_column(Float, default=1.0)
    craft_mode: Mapped[str] = mapped_column(String(16), default="auto")
    self_review: Mapped[str] = mapped_column(String(16), default="auto")
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    api_base_url: Mapped[str] = mapped_column(String(255), default="https://api.deepseek.com")
    api_model: Mapped[str] = mapped_column(String(128), default="deepseek-chat")
    critic_api_key_enc: Mapped[str] = mapped_column(Text, default="")
    critic_api_base_url: Mapped[str] = mapped_column(String(255), default="")
    critic_api_model: Mapped[str] = mapped_column(String(128), default="")
    bg: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    user: Mapped["User"] = relationship(back_populates="settings")
