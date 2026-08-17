"""Domain types ported from packages/core/src/types.ts.

ScriptBlock and AgentAction are kept as flexible ``Dict[str, Any]`` payloads
(mirroring the plain-object discriminated unions used in the TypeScript
source) so that the core business logic can pattern-match on a ``"type"`` /
``"op"`` key exactly like the original code does. ``TypedDict`` variants are
provided for documentation / static-typing purposes only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict

CharacterId = str
LabelId = str
LocationId = str


class VoiceCorpusLine(BaseModel):
    model_config = ConfigDict(extra="allow")

    speaker: str = "self"  # self | other | name
    text: str = ""


class VoiceCorpusSample(BaseModel):
    """Accepted (or imported) dialogue evidence for a character voice."""

    model_config = ConfigDict(extra="allow")

    id: str
    scenario: str = ""
    scenarioLabel: Optional[str] = None
    axis: Optional[str] = None
    hypothesis: Optional[str] = None
    lines: List[VoiceCorpusLine] = Field(default_factory=list)
    source: Literal[
        "preference", "import", "script_extract", "scene", "interview", "manual", "chat"
    ] = "preference"
    userNote: Optional[str] = None
    rejectedSummary: Optional[str] = None
    createdAt: Optional[str] = None


class Character(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: CharacterId
    # Ren'Py define name, e.g. eileen
    defineName: str
    displayName: str
    color: Optional[str] = None
    # Speaking voice / personality for AI
    voice: Optional[str] = None
    bio: Optional[str] = None
    # Optional image tag for show statements
    imageTag: Optional[str] = None
    # Relations to other characters (free text)
    relationships: Optional[str] = None
    # Preference-calibrated dialogue corpus (positive examples)
    voiceCorpus: Optional[List[VoiceCorpusSample]] = None
    # Lightweight character mind card (markdown; nuwa five-layer lite)
    voiceMind: Optional[str] = None
    # Short notes from rejected variants (anti-patterns)
    voiceRejectNotes: Optional[List[str]] = None
    # Why a pick felt right (preference chips / free text)
    voicePreferNotes: Optional[List[str]] = None


# --- ScriptBlock ------------------------------------------------------------
# Kept as a plain dict at runtime (matching the TS discriminated union of
# plain objects). TypedDicts below document the expected shape per "type".


class LabelBlock(TypedDict):
    type: Literal["label"]
    id: LabelId
    name: str


class SceneBlock(TypedDict):
    type: Literal["scene"]
    image: str
    transition: NotRequired[str]


class ShowBlock(TypedDict):
    type: Literal["show"]
    image: str
    at: NotRequired[str]


class HideBlock(TypedDict):
    type: Literal["hide"]
    image: str


class NarrationBlock(TypedDict):
    type: Literal["narration"]
    text: str


class DialogueBlock(TypedDict):
    type: Literal["dialogue"]
    characterId: CharacterId
    text: str


class MenuChoice(TypedDict):
    text: str
    jump: NotRequired[LabelId]
    blocks: NotRequired[List["ScriptBlock"]]


class MenuBlock(TypedDict):
    type: Literal["menu"]
    id: str
    prompt: NotRequired[str]
    choices: List[MenuChoice]


class JumpBlock(TypedDict):
    type: Literal["jump"]
    target: LabelId


class ReturnBlock(TypedDict):
    type: Literal["return"]


class CommentBlock(TypedDict):
    type: Literal["comment"]
    text: str


class RawBlock(TypedDict):
    type: Literal["raw"]
    code: str


ScriptBlockTyped = Union[
    LabelBlock,
    SceneBlock,
    ShowBlock,
    HideBlock,
    NarrationBlock,
    DialogueBlock,
    MenuBlock,
    JumpBlock,
    ReturnBlock,
    CommentBlock,
    RawBlock,
]

# Runtime-friendly alias used throughout core/*.py — a plain dict with a
# "type" discriminant key, exactly like the JS objects at runtime.
ScriptBlock = Dict[str, Any]


class SceneChapter(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    synopsis: Optional[str] = None
    blocks: List[ScriptBlock] = Field(default_factory=list)


class StoryBible(BaseModel):
    """Story setting — independent from character cards."""

    model_config = ConfigDict(extra="allow")

    # 世界观 / 规则
    world: Optional[str] = None
    # 故事背景 / 前情
    background: Optional[str] = None
    # 大纲 / 节拍
    outline: Optional[str] = None
    # 主题、基调、禁忌
    themes: Optional[str] = None
    # 其他备忘
    notes: Optional[str] = None


LocationRelation = Literal[
    "adjacent",
    "contains",
    "inside",
    "above",
    "below",
    "leads_to",
    "visible_from",
    "other",
]

LOCATION_RELATION_LABELS: Dict[str, str] = {
    "adjacent": "相邻",
    "contains": "包含",
    "inside": "位于其内",
    "above": "上方",
    "below": "下方",
    "leads_to": "通往",
    "visible_from": "可见于",
    "other": "其他",
}

MapStyleId = Literal["default"]

MapLineStyle = Literal["solid", "dashed", "dotted", "double", "rail", "magic"]

MAP_LINE_STYLE_LABELS: Dict[str, str] = {
    "solid": "实线",
    "dashed": "虚线",
    "dotted": "点线",
    "double": "双线",
    "rail": "轨道",
    "magic": "魔力轨",
}


class MapStrokePoint(BaseModel):
    model_config = ConfigDict(extra="allow")
    x: float
    y: float


class MapStroke(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    # Freehand polyline in world coords
    points: List[MapStrokePoint] = Field(default_factory=list)
    color: str
    width: float
    kind: Literal["path", "mark"]


MapElementKind = Literal[
    "station",
    "plaza",
    "park",
    "hospital",
    "school",
    "cafe",
    "home",
    "shop",
    "office",
    "apartment",
    "temple",
    "forest",
    "beach",
    "bridge",
    "landmark",
    "custom",
]


class Location(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: LocationId
    name: str
    # Hint for Ren'Py scene image, e.g. bg station_night
    imageTag: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    # Story-map coordinates
    mapX: Optional[float] = None
    mapY: Optional[float] = None
    elementKind: Optional[str] = None
    # Emoji / short glyph shown on map
    icon: Optional[str] = None
    color: Optional[str] = None
    scale: Optional[float] = None
    rotation: Optional[float] = None


class CustomMapElementDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    icon: str
    color: str


class LocationLink(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    fromId: LocationId
    toId: LocationId
    relation: str
    note: Optional[str] = None
    lineStyle: Optional[str] = None


class GameVariable(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    # Ren'Py / code identifier
    key: str
    type: Literal["number", "bool", "string"]
    value: Union[float, bool, str]
    # e.g. affection toward character id
    bindCharacterId: Optional[str] = None
    note: Optional[str] = None


class SpriteExpression(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    # Ren'Py image tag suffix, e.g. sad
    tag: str
    note: Optional[str] = None


class SpriteDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    # Base Ren'Py image name, e.g. linxia
    imageTag: str
    characterId: Optional[str] = None
    expressions: List[SpriteExpression] = Field(default_factory=list)


class ProjectSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    createdAt: str
    # dict (content-addressed) or legacy JSON string
    payload: Any
    contentHash: Optional[str] = None


class ChapterIndexEntry(BaseModel):
    """Lightweight per-chapter digest stored on the project blob."""

    model_config = ConfigDict(extra="allow")

    chapterId: str
    title: str
    hash: str
    synopsis: str = ""
    speakers: List[str] = Field(default_factory=list)
    openHook: str = ""
    closeHook: str = ""


class FactEvidence(BaseModel):
    """Provenance for an accepted or proposed analysis fact."""

    model_config = ConfigDict(extra="allow")

    # script | bible | card | paste | upload | agent
    source: str
    chapterId: Optional[str] = None
    quote: Optional[str] = None
    field: Optional[str] = None
    fingerprint: Optional[str] = None


class CharacterLink(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    fromId: CharacterId
    toId: CharacterId
    label: str
    evidence: Optional[List[FactEvidence]] = None
    stale: Optional[bool] = None
    staleReason: Optional[str] = None
    acceptedAt: Optional[str] = None


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    # Free-form time label, e.g. 第一晚 / Day 3
    when: Optional[str] = None
    chapterRef: Optional[str] = None
    summary: Optional[str] = None
    order: float
    evidence: Optional[List[FactEvidence]] = None
    stale: Optional[bool] = None
    staleReason: Optional[str] = None
    acceptedAt: Optional[str] = None


class AnalysisMeta(BaseModel):
    """Lightweight fingerprints for incremental fact scanning (in project JSON)."""

    model_config = ConfigDict(extra="allow")

    chapterFingerprints: Optional[Dict[str, str]] = None
    bibleFingerprint: Optional[str] = None
    characterFingerprints: Optional[Dict[str, str]] = None
    lastScanAt: Optional[str] = None
    lastReconcileAt: Optional[str] = None


class VnProject(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    logline: Optional[str] = None
    genre: Optional[str] = None
    characters: List[Character] = Field(default_factory=list)
    chapters: List[SceneChapter] = Field(default_factory=list)
    # deprecated: prefer bible.world — kept for older saves
    lore: Optional[str] = None
    bible: Optional[StoryBible] = None
    locations: Optional[List[Location]] = None
    locationLinks: Optional[List[LocationLink]] = None
    mapStyle: Optional[str] = None
    customMapElements: Optional[List[CustomMapElementDef]] = None
    mapStrokes: Optional[List[MapStroke]] = None
    characterLinks: Optional[List[CharacterLink]] = None
    timeline: Optional[List[TimelineEvent]] = None
    variables: Optional[List[GameVariable]] = None
    sprites: Optional[List[SpriteDef]] = None
    snapshots: Optional[List[ProjectSnapshot]] = None
    # Extractive chapter digests / content hashes (refreshed on save)
    chapterIndex: Optional[List[ChapterIndexEntry]] = None
    # Plan→Write→Check ledger: chapter facts / character states / foreshadows
    writingLedger: Optional[Dict[str, Any]] = None
    # Recent harness / pipeline run summaries (capped; for replay & observability)
    harnessRuns: Optional[List[Dict[str, Any]]] = None
    # Writing mentor packs: activeIds + optional imported customPacks
    writingMentors: Optional[Dict[str, Any]] = None
    # Author lenses (optional multi-perspective review/plot); default off
    authorLenses: Optional[Dict[str, Any]] = None
    # Fingerprints for analysis fact-bus incremental scan
    analysisMeta: Optional[AnalysisMeta] = None
    # Persisted voice-check reports (chapterId + fingerprint; may be stale)
    voiceReports: Optional[List[Dict[str, Any]]] = None
    # Author style memory: LLM-learned writing-style guide from this novel
    styleMemory: Optional[Dict[str, Any]] = None
    # Local read-only share id
    shareId: Optional[str] = None
    updatedAt: str


AiAction = Literal[
    "continue", "rewrite", "choices", "polish", "outline", "character_voice"
]


class AiRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str
    project: VnProject
    selection: Optional[str] = None
    instruction: Optional[str] = None
    format: Optional[Literal["renpy", "blocks-json"]] = None


class AiResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    content: str
    model: str


# Structured operations the studio Agent may return.
# Kept as a flexible dict (with an "op" discriminant) — see agent.py for the
# handling logic, mirroring the TS discriminated union of plain objects.
AgentAction = Dict[str, Any]


class AgentChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["user", "assistant"]
    content: str


# Writing-task mode for Agent retrieval + prompt bias
AgentTaskKind = Literal[
    "chat",
    "continue",
    "rewrite",
    "polish",
    "branch",
    "outline",
    "voice",
    "consistency",
    "scene",
]


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: VnProject
    messages: List[AgentChatMessage] = Field(default_factory=list)
    chapterId: Optional[str] = None
    selection: Optional[str] = None
    # Specialized task — drives context retrieval and system hints
    task: Optional[str] = None
    # Rolling chat memory (extractive) for long conversations
    chatMemory: Optional[str] = None
    # NovelMaster-style long chapter archive (assembled from PG slices)
    longChapterMemory: Optional[str] = None
    # Moegirl-inspired ACG craft cards (distilled; never paste wiki into script)
    loreCraft: Optional[str] = None
    # User-uploaded reference docs (already extracted plain text)
    referenceDocs: Optional[str] = None
    # Writing craft injection: auto | off | lite | full
    craftMode: Optional[str] = None
    # Override project writingMentors.activeIds for this turn (max 2)
    mentorIds: Optional[List[str]] = None
    # Optional author lenses for this turn (max 3); None = use project.authorLenses
    lensIds: Optional[List[str]] = None
    # Second-pass narrative/social self-review: auto | on | off
    selfReview: Optional[str] = None
    # Optional separate critic model (cross-model review reduces self-bias)
    criticApiKey: Optional[str] = None
    criticApiBaseUrl: Optional[str] = None
    criticApiModel: Optional[str] = None
    # Optional client-provided credentials (override server env)
    apiKey: Optional[str] = None
    apiBaseUrl: Optional[str] = None
    apiModel: Optional[str] = None


class AgentContextMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    task: str
    charsUsed: int
    included: List[str] = Field(default_factory=list)
    craftMode: Optional[str] = None
    craftReason: Optional[str] = None
    mentorIds: Optional[List[str]] = None
    lensIds: Optional[List[str]] = None
    # Self-review outcome note
    selfReview: Optional[str] = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str
    actions: List[AgentAction] = Field(default_factory=list)
    model: str
    # What context slices were injected (transparency for long-form)
    contextMeta: Optional[AgentContextMeta] = None
    # Multi-step tool trajectory (thought / tool_call / tool_result / actions / done)
    trace: Optional[List[Dict[str, Any]]] = None
