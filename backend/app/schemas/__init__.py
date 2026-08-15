from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    created_at: datetime


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


class ProjectPutIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: Dict[str, Any]
    updated_at: Optional[str] = None  # client version for optimistic concurrency
    # When true, skip updated_at check and overwrite server (user chose "keep local")
    force: bool = False


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


class AgentIngestSettingsIn(BaseModel):
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    note: Optional[str] = None
    conversation_id: Optional[str] = None
