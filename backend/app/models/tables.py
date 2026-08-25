from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")
    settings: Mapped[Optional["UserSettings"]] = relationship(
        back_populates="user", uselist=False
    )


class AuthEmailToken(Base):
    """One-time email verify / password-reset tokens."""

    __tablename__ = "auth_email_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # verify | reset
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="未命名剧本")
    genre: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    logline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # 乐观锁基础：每次写路径自增（配合 put_project 的 FOR UPDATE 行锁，
    # 为后续客户端 If-Match/rowVersion 条件保存铺路）
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"), default=1
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner: Mapped["User"] = relationship(back_populates="projects")
    shares: Mapped[list["Share"]] = relationship(
        back_populates="project", passive_deletes=True
    )
    agent_sessions: Mapped[list["AgentSession"]] = relationship(
        back_populates="project", passive_deletes=True
    )
    snapshot_rows: Mapped[list["ProjectSnapshotRow"]] = relationship(
        back_populates="project", passive_deletes=True
    )


class Share(Base):
    __tablename__ = "shares"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
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
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    messages: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    chat_memory: Mapped[str] = mapped_column(Text, default="")
    undo_stack: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # 运行中/中断的 Agent 执行快照（断点续跑的依据）：
    # {status: running|interrupted|error|done, step, steps, task, temperature,
    #  craftMode, messages, project, actions, trace, final_message, last_tool_text}
    run_state: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
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
    api_model: Mapped[str] = mapped_column(String(128), default="deepseek-v4-flash")
    critic_api_key_enc: Mapped[str] = mapped_column(Text, default="")
    critic_api_base_url: Mapped[str] = mapped_column(String(255), default="")
    critic_api_model: Mapped[str] = mapped_column(String(128), default="")
    bg: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    user: Mapped["User"] = relationship(back_populates="settings")


class ChapterMemoryArchive(Base):
    """NovelMaster-style chapter-span archive (one row per chapters_001_010 group)."""

    __tablename__ = "chapter_memory_archives"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # e.g. chapters_001_010
    label: Mapped[str] = mapped_column(String(64))
    span: Mapped[int] = mapped_column(Integer, default=10)
    range_from: Mapped[int] = mapped_column(Integer)
    range_to: Mapped[int] = mapped_column(Integer)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # Ordered chapter ids in this span
    chapter_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # [{chapterId, index, title, recall}]
    spine: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # [{chapterId, title, wordCount, quickRecall, speakers}]
    summaries: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # Placeholder deltas (character / relationship / hooks) — JSONB object
    deltas: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship()
    slices: Mapped[list["ChapterMemorySlice"]] = relationship(
        back_populates="archive", cascade="all, delete-orphan"
    )


class ChapterMemorySlice(Base):
    """TEXT slices of long continuity markdown — PG-friendly chunked storage."""

    __tablename__ = "chapter_memory_slices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    archive_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chapter_memory_archives.id"), index=True
    )
    # continuity | context_snapshot | notes
    kind: Mapped[str] = mapped_column(String(32), default="continuity")
    slice_index: Mapped[int] = mapped_column(Integer, default=0)
    # Keep each slice modest (~6KB) for easy paging / Agent budgets
    content: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    archive: Mapped["ChapterMemoryArchive"] = relationship(back_populates="slices")


class AnalysisInboxItem(Base):
    """Sidecar inbox for analysis fact candidates (relations / timeline / paste)."""

    __tablename__ = "analysis_inbox_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # character_link | timeline_event | source_snippet
    kind: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # pending | accepted | rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProjectSnapshotRow(Base):
    """Version snapshots stored outside the project blob (content-addressed)."""

    __tablename__ = "project_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(255), default="")
    # sha256[:32] of the canonical payload — used for dedupe
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    # Full project payload (snapshots field stripped)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="snapshot_rows")


class AgentJob(Base):
    """Persistent async job rows (pipeline / chapter revise) — survives restarts."""

    __tablename__ = "agent_jobs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    # pipeline | chapter_revise
    kind: Mapped[str] = mapped_column(String(32), default="", index=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # queued | running | done | error
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(64), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LlmUsage(Base):
    """Per-user LLM token accounting (written fire-and-forget from llm_http)."""

    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # coarse call kind: agent | pipeline | revise | harness | voice | brainstorm | map | settings | llm
    kind: Mapped[str] = mapped_column(String(32), default="llm", index=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProjectMember(Base):
    """Collaborative membership — owner | editor | viewer (owner is the creator).

    (project_id, user_id) is unique so concurrent add_member / invite accepts
    cannot produce duplicate memberships.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", name="uq_project_members_project_user"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # owner | editor | viewer
    role: Mapped[str] = mapped_column(String(16), default="editor")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProjectInvite(Base):
    """Invite links — anyone with the token can join the project as a member."""

    __tablename__ = "project_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # editor | viewer
    role: Mapped[str] = mapped_column(String(16), default="editor")
    created_by: Mapped[str] = mapped_column(String(36), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChapterLock(Base):
    """Chapter-level edit lock — prevents two editors clobbering the same chapter.

    (project_id, chapter_id) is unique: at most one lock row per chapter, so
    concurrent acquire_lock calls cannot double-lock.
    """

    __tablename__ = "chapter_locks"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "chapter_id", name="uq_chapter_locks_project_chapter"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # Heartbeat expiry — stale locks are reclaimable.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LoreCraftCard(Base):
    """Distilled ACG craft card (萌百启发精炼，非百科原文库)."""

    __tablename__ = "lore_craft_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # empty/null = global library; else project-scoped favorites
    project_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    term: Mapped[str] = mapped_column(String(128), index=True)
    aliases: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    kind: Mapped[str] = mapped_column(String(32), default="term", index=True)
    definition_short: Mapped[str] = mapped_column(Text, default="")
    do_list: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    dont_list: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    vn_beats: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    source_title: Mapped[str] = mapped_column(String(255), default="")
    source_url: Mapped[str] = mapped_column(String(512), default="")
    raw_extract: Mapped[str] = mapped_column(Text, default="")
    attribution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProjectComment(Base):
    """Inline annotations on chapters — collaboration stage C.

    ``anchor`` is a free-form locator for the commented region, e.g.
    ``block:<blockId>`` or ``text:start=12&end=45``; when empty the comment
    is chapter-level. Comments are shared across all project members.
    """

    __tablename__ = "project_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[str] = mapped_column(String(64), index=True)
    # chapter-level when empty; else block:<id> or text range
    anchor: Mapped[str] = mapped_column(String(255), default="", index=True)
    # reply thread: null = top-level comment; else parent comment id (2 levels max)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("project_comments.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProjectChapterRow(Base):
    """Chapters stored outside the project blob (JSONB split, stage 1).

    The ``projects.data`` blob keeps a mirror of chapters so existing
    synchronous read paths (``row_to_vn``) keep working unchanged; chapter
    writes go through this table first, then the mirror is refreshed. A full
    migration that drops the blob copy can follow once every read path reads
    the table.
    """

    __tablename__ = "project_chapter_rows"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    synopsis: Mapped[str] = mapped_column(Text, default="")
    blocks: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WritingActivity(Base):
    """Per-day word-count deltas for the writing stats dashboard.

    One row per (project_id, activity_date); every chapter save adds/subtracts
    from that day's tally so the UI can show a calendar heatmap, daily progress
    and totals without re-diffing snapshots.
    """

    __tablename__ = "writing_activity"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "activity_date", name="uq_writing_activity_project_date"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    activity_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    words_added: Mapped[int] = mapped_column(Integer, default=0)
    words_removed: Mapped[int] = mapped_column(Integer, default=0)
    edits: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ErrorReport(Base):
    """Client-side error reports (global window errors + React boundaries).

    Collected for diagnosis; the public POST endpoint is rate-limited per IP
    and never returns the stored payload back to the caller.
    """

    __tablename__ = "error_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    level: Mapped[str] = mapped_column(String(16), default="error")
    message: Mapped[str] = mapped_column(Text, default="")
    stack: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    component: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)