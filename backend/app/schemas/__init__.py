from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TokenOut(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None


class RefreshIn(BaseModel):
    refresh_token: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    email: str = Field(min_length=3, max_length=255)


class RegisterOut(BaseModel):
    ok: bool = True
    message: str
    email: str


class LoginIn(BaseModel):
    username: str  # username or email
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    email_verified: bool = True
    created_at: datetime
    is_admin: bool = False


class EmailTokenIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)


class ResendVerifyIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    password: str = Field(min_length=6, max_length=128)


class OkMessageOut(BaseModel):
    ok: bool = True
    message: str = ""


class ProjectSummary(BaseModel):
    id: str
    title: str
    logline: Optional[str] = None
    genre: Optional[str] = None
    updated_at: datetime
    created_at: datetime


class ProjectCreateIn(BaseModel):
    title: Optional[str] = None
    from_demo: bool = False
    # Starter template id (see app/core/templates.py) — mutually exclusive
    # with from_demo; template projects get a fresh set of ids.
    template_id: Optional[str] = None


class ProjectPutIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: Dict[str, Any]
    updated_at: Optional[str] = None  # client version for optimistic concurrency
    # When true, skip updated_at check and overwrite server (user chose "keep local")
    force: bool = False
    # Collaboration stage B: chapters this save actually modified (create/update/delete).
    # When provided, the server merges only these chapters instead of replacing the
    # whole project — so concurrent edits to different chapters do not clobber each other.
    chapter_ids: Optional[List[str]] = None
    # Top-level fields (non-chapter) this save actually modified, e.g. ["characters"].
    sections: Optional[List[str]] = None


class ProjectPatchIn(BaseModel):
    title: Optional[str] = None
    logline: Optional[str] = None
    genre: Optional[str] = None


class SnapshotCreateIn(BaseModel):
    label: str = "快照"


class LintIn(BaseModel):
    draft: str


class AgentRunIn(BaseModel):
    messages: List[Dict[str, Any]]
    chapter_id: Optional[str] = None
    selection: Optional[str] = None
    task: Optional[str] = None
    chat_memory: Optional[str] = None
    conversation_id: Optional[str] = None
    apply_actions: bool = True
    lens_ids: Optional[List[str]] = None
    lens_intent: Optional[str] = None
    # Pre-extracted attachment texts from /agent/attachments or client
    attachments: Optional[List[Dict[str, Any]]] = None
    # 断点续跑：true 时从会话 run_state 的检查点继续上次中断/失败的多步运行
    resume: bool = False


class AgentRunOut(BaseModel):
    message: str
    actions: List[Dict[str, Any]]
    model: str
    context_meta: Optional[Dict[str, Any]] = None
    project: Optional[Dict[str, Any]] = None
    applied: bool = False
    warnings: List[str] = Field(default_factory=list)
    conversation_id: Optional[str] = None
    inbox_added: int = 0
    trace: Optional[List[Dict[str, Any]]] = None


class AgentConversationSummary(BaseModel):
    id: str
    title: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class AgentConversationOut(BaseModel):
    id: str
    title: str
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    chat_memory: str = ""
    undo_stack: List[Any] = Field(default_factory=list)
    # 运行检查点摘要（前端据此显示"上次运行中断，可继续"）
    run_state: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class AgentConversationCreateIn(BaseModel):
    title: Optional[str] = None


class AgentConversationPutIn(BaseModel):
    title: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    chat_memory: Optional[str] = None
    undo_stack: Optional[List[Any]] = None


class AgentConversationRenameIn(BaseModel):
    title: str


# Back-compat aliases
class AgentSessionOut(AgentConversationOut):
    pass


class AgentSessionPutIn(AgentConversationPutIn):
    pass


class AiRunIn(BaseModel):
    action: str
    selection: Optional[str] = None
    instruction: Optional[str] = None
    format: Optional[Literal["renpy", "blocks-json"]] = "renpy"


class VoiceCheckIn(BaseModel):
    chapter_id: Optional[str] = None
    draft: Optional[str] = None


class ShareCreateOut(BaseModel):
    token: str
    url: str


class ShareOut(BaseModel):
    token: str
    title: str
    project: Dict[str, Any]
    created_at: datetime
    # Public landing-page preview: chapter text taste + character list
    preview: Dict[str, Any] = Field(default_factory=dict)


class SettingsOut(BaseModel):
    theme: str = "day"
    font_scale: float = 1.0
    bg_image: str = ""
    bg_scale: float = 1.0
    bg_opacity: float = 0.35
    bg_pan_x: float = 0
    bg_pan_y: float = 0
    panel_glass: str = "auto"
    bg_scrim: float = 0.42
    # User-level LLM credentials (never return the raw key).
    has_api_key: bool = False
    api_key_masked: str = ""
    api_base_url: str = ""
    api_model: str = ""
    has_critic_api_key: bool = False
    critic_api_key_masked: str = ""
    critic_api_base_url: str = ""
    critic_api_model: str = ""
    # Effective model actually used (user override or server env), for display.
    active_model: str = ""
    active_base_url: str = ""
    # user = account DB key; server = env fallback; client = X-LLM-* headers
    credential_source: str = "server"


class SettingsPutIn(BaseModel):
    theme: Optional[str] = None
    font_scale: Optional[float] = None
    bg_image: Optional[str] = None
    bg_scale: Optional[float] = None
    bg_opacity: Optional[float] = None
    bg_pan_x: Optional[float] = None
    bg_pan_y: Optional[float] = None
    panel_glass: Optional[str] = None
    bg_scrim: Optional[float] = None
    # User-level LLM credentials. api_key: send a new key to set/rotate,
    # send "" to clear, omit to keep unchanged. Masked values echo back.
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None
    api_model: Optional[str] = None
    critic_api_key: Optional[str] = None
    critic_api_base_url: Optional[str] = None
    critic_api_model: Optional[str] = None


class TestLlmIn(BaseModel):
    """Test-connection request. Empty fields fall back to X-LLM-* request
    headers, then saved user creds, then server env."""

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class MapExtractIn(BaseModel):
    """mode=smart: scene rules + lexicon + LLM; mode=rules: scene tags only."""

    mode: Literal["smart", "rules"] = "smart"


class MapExtractProposalIn(BaseModel):
    locations: List[Dict[str, Any]] = Field(default_factory=list)
    locationLinks: List[Dict[str, Any]] = Field(default_factory=list)
    newPlaceIds: List[str] = Field(default_factory=list)
    newLinkIds: List[str] = Field(default_factory=list)


class MapExtractAcceptIn(BaseModel):
    placeIds: List[str] = Field(default_factory=list)
    linkIds: List[str] = Field(default_factory=list)
    proposal: MapExtractProposalIn


class FactsScanIn(BaseModel):
    chapter_id: Optional[str] = None
    paste_text: Optional[str] = None
    full: bool = False
    persist_paste: bool = False
    # Optional LLM semantic layer: verify/refine heuristic candidates first.
    llm: bool = False


class FactsAcceptIn(BaseModel):
    ids: List[str] = Field(default_factory=list)


class FactsRejectIn(BaseModel):
    ids: List[str] = Field(default_factory=list)


class FactsAckStaleIn(BaseModel):
    linkIds: List[str] = Field(default_factory=list)
    timelineIds: List[str] = Field(default_factory=list)
    all: bool = False


class ChapterReviseIn(BaseModel):
    chapter_id: Optional[str] = None
    note: Optional[str] = None
    conversation_id: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    mode: Optional[str] = None  # cut_lecture | human_warmth | light_touch
    preferences: Optional[Dict[str, Any]] = None
    async_mode: bool = False


class ChapterReviseApplyIn(BaseModel):
    chapter_id: Optional[str] = None
    text: str
    conversation_id: Optional[str] = None


class GenerateRpyIn(BaseModel):
    chapter_id: str = Field(min_length=1, max_length=64)
    prose: str = Field(min_length=1, max_length=200_000)
    use_llm: bool = True


class SnapshotCompareIn(BaseModel):
    """Diff a stored snapshot against another snapshot (or the live project)."""

    from_snap_id: str = Field(min_length=1, max_length=64)
    # When omitted, compare against the project's current state.
    to_snap_id: Optional[str] = Field(default=None, max_length=64)


class AgentIngestSettingsIn(BaseModel):
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    note: Optional[str] = None
    conversation_id: Optional[str] = None
