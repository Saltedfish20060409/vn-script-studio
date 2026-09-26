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
    # 其它叫法：绰号、旧名、英文 id、称呼（检索时一并命中，避免"换个说法就搜不到"）
    aliases: Optional[List[str]] = None


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
    # 条件选项：只有条件成立时才出现（对应 Ren'Py 的 `"文本" if cond:`）
    condition: NotRequired[str]


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


# ---- 演出指令（音频 / 等待 / 镜头 / 特效）----
# 此前完全缺失：作者只能在 raw 里手写 Ren'Py，而且试玩时也演不出来。


class MusicBlock(TypedDict):
    """BGM：play/stop + 淡入淡出秒数。"""

    type: Literal["music"]
    action: Literal["play", "stop"]
    file: NotRequired[str]
    fade: NotRequired[float]


class SoundBlock(TypedDict):
    """音效（短音）：play/stop。"""

    type: Literal["sound"]
    action: Literal["play", "stop"]
    file: NotRequired[str]
    volume: NotRequired[float]


class VoiceBlock(TypedDict):
    """语音：通常紧挨着一句台词；action=stop 表示停止当前语音。"""

    type: Literal["voice"]
    action: Literal["play", "stop"]
    file: NotRequired[str]


class WaitBlock(TypedDict):
    """等待若干秒（试玩自动继续；导出 pause）。"""

    type: Literal["wait"]
    seconds: NotRequired[float]


class CameraBlock(TypedDict):
    """镜头：缩放 / 位移 / 具名 transform（at 优先）。"""

    type: Literal["camera"]
    zoom: NotRequired[float]
    x: NotRequired[float]
    y: NotRequired[float]
    at: NotRequired[str]


class EffectBlock(TypedDict):
    """画面特效：预置枚举，导出成对应 Ren'Py transition。"""

    type: Literal["effect"]
    # shake | vshake | flash_white | flash_black | fade_black | fade_white | dissolve
    kind: str
    duration: NotRequired[float]


class SetVariableBlock(TypedDict):
    """变量赋值：`set affection += 1` → 导出 `$ affection += 1`。"""

    type: Literal["set"]
    key: str
    op: NotRequired[Literal["=", "+=", "-="]]
    value: NotRequired[Any]


class IfBranch(TypedDict):
    """条件分支：condition 为空表示 else。"""

    condition: NotRequired[str]
    blocks: List["ScriptBlock"]


class IfBlock(TypedDict):
    type: Literal["if"]
    branches: List[IfBranch]


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
    MusicBlock,
    SoundBlock,
    VoiceBlock,
    WaitBlock,
    CameraBlock,
    EffectBlock,
    SetVariableBlock,
    IfBlock,
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
    # Natural-language manuscript (default writing surface). Independent of blocks.
    prose: Optional[str] = None
    # Fingerprint of prose last used to generate RPY (stale when it drifts).
    rpyFromProseHash: Optional[str] = None
    # 所属卷（可选）。没有卷时是 None，行为与"平铺章节"完全一致。
    volumeId: Optional[str] = None
    # 连载发布状态（可选）：有值 = 这一章作者标记为"已发布"（ISO 时间）。
    # 为什么不做成 bool：连载作者常回头改已发布的章，改完想再发一次，
    # 记时间才能看出"这一章是什么时候发的"。缺省 = 未发布（老工程行为不变）。
    publishedAt: Optional[str] = None


class Volume(BaseModel):
    """一卷（轻小说/网文的连载单位）。

    章节靠 ``SceneChapter.volumeId`` 归属；卷的顺序就是本列表的顺序。
    老工程没有 volumes 字段 → 空列表 → 界面上仍是平铺章节，不改变任何行为。
    """

    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    # 卷备注（这一卷要写什么、给谁看），不进正文
    note: Optional[str] = None


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
    # 其它叫法：别称、俗称、英文 id（检索时一并命中）
    aliases: Optional[List[str]] = None


class LoreLink(BaseModel):
    """设定条目的实体链接（条目 → 角色 / 地点 / 章节）。

    为什么加它：条目原来只有触发词，是**孤岛**——只有提问里恰好出现那个词才会被检索到。
    而"这条设定讲的是谁、发生在哪"本来就该是显式的边：有了边，
    命中条目就能把相关角色/地点一起带进来，命中角色也能反向带出相关条目。
    """

    model_config = ConfigDict(extra="allow")

    toType: Literal["character", "location", "chapter"]
    toId: str
    note: Optional[str] = None


class LoreEntry(BaseModel):
    """设定条目：一条可被检索的设定（门派 / 系统 / 规则 / 组织 / 历史事件…）。

    存在的理由：`bible` 那五个字段每个都有几百字的预算，装不下大体量设定；
    而"上百万字设定用不动"的根因不在模型窗口，在于没有"按需取一条"的载体。
    条目可以无上限地堆，每条自带**触发词**（keywords），检索命中的进上下文，
    没命中的不进——所以设定再大，单次进去的仍然只有相关的那几条。
    """

    model_config = ConfigDict(extra="allow")

    id: str
    title: str = ""
    body: str = ""
    # 触发词 / 别名：提问里出现这些词就命中（比正文里恰好出现某个字可靠得多）
    keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    # 钉住：不管提问是什么，每轮都带上（作者认为"永远不能写错"的那几条）
    pinned: Optional[bool] = None
    # 同分时的排序权重（越大越优先），默认 0
    priority: Optional[int] = None
    # 实体链接：这条设定讲的是谁 / 在哪 / 属于哪一章（检索会沿边走一步）
    links: Optional[List[LoreLink]] = None


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


class Ending(BaseModel):
    """结局登记。

    为什么需要"声明式结局"：在此之前"这作品有几个结局"只能从控制流**推断**
    （`script_analysis._flow_ends` 看哪里 return / 断流），于是两类问题都查不出来——
    写了 5 个结局但只有 3 个能从 start 走到，以及"某个终点其实是个 bug 不是结局"。
    登记之后，"声明 vs 可达"才能对账。
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    # 结局所在 label（写 label 名；导出后对应 Ren'Py 的 label）
    label: Optional[str] = None
    # 进入该结局的条件（受控语法，与菜单选项条件同一套：core/conditions.py）
    condition: Optional[str] = None
    # 路线 / 攻略线名，如「雪见线」「真结局」
    route: Optional[str] = None
    description: Optional[str] = None


class WritingGoals(BaseModel):
    """写作目标（可选）：三个口径的字数目标，单位是"字"（口径同写作统计）。

    为什么不塞进 writingMentors 之类的自由字典：目标要跟着作品走（换设备要还在），
    而且是界面上会反复读写的小结构，声明成模型才能被 normalize 与合并逻辑带上。
    留 None 表示"没设目标"——界面上不显示进度条，而不是显示一个 0/0。

    ``mustBring`` 不是字数目标，但同属"作者为本场写作钉的短约束"：
    编排层保证进上下文头部且超预算不挤掉（见 agent_context / memory_probe）。
    """

    model_config = ConfigDict(extra="allow")

    # 日更目标（按 /stats 的当日净增字数算）
    daily: Optional[int] = None
    # 单章目标（按当前章节实时字数算）
    chapter: Optional[int] = None
    # 单卷目标（按 /stats 的该卷累计字数算）
    volume: Optional[int] = None
    # 本场必带进窗的短句（人/地/物/禁写）；空/缺省 = 不注入
    mustBring: Optional[List[str]] = None


class VnProject(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    logline: Optional[str] = None
    genre: Optional[str] = None
    characters: List[Character] = Field(default_factory=list)
    chapters: List[SceneChapter] = Field(default_factory=list)
    # 卷（可选）：章节按 volumeId 归属；空列表 = 平铺章节（老工程行为不变）
    volumes: Optional[List[Volume]] = None
    # deprecated: prefer bible.world — kept for older saves
    lore: Optional[str] = None
    bible: Optional[StoryBible] = None
    locations: Optional[List[Location]] = None
    locationLinks: Optional[List[LocationLink]] = None
    mapStyle: Optional[str] = None
    # 地图测距的比例尺与默认交通方式（属于作品设定：换设备要跟着走）
    mapMeasure: Optional[Dict[str, Any]] = None
    customMapElements: Optional[List[CustomMapElementDef]] = None
    mapStrokes: Optional[List[MapStroke]] = None
    characterLinks: Optional[List[CharacterLink]] = None
    # 设定条目（可无上限地堆；按触发词/正文检索，只有命中的进上下文）
    loreEntries: Optional[List[LoreEntry]] = None
    timeline: Optional[List[TimelineEvent]] = None
    variables: Optional[List[GameVariable]] = None
    sprites: Optional[List[SpriteDef]] = None
    # 结局登记（可选）：声明式多结局管理。不填则退回"按控制流推断结局"。
    endings: Optional[List[Ending]] = None
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
    # 作者风格记忆: LLM-learned writing-style guide from this novel
    styleMemory: Optional[Dict[str, Any]] = None
    # 本地化：locales / entries（源文本 + 各语言译文 + 状态）/ glossary
    localization: Optional[Dict[str, Any]] = None
    # 写作目标（可选）：日更/本章/本卷字数，写作页据此显示进度与"还差多少"
    writingGoals: Optional[WritingGoals] = None
    # 作品体裁（可选）：决定界面用哪套词——"vn" 用剧本/选项/Ren'Py，
    # "novel" 用正文/分卷/投稿；"auto" 或缺省 = 按 genre 关键词推断
    # （推断规则在前端 lib/genreCopy.ts，显式值优先，作者可以在设定页改）
    writingGenre: Optional[str] = None
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
    # 卷级/全局记忆层：四十章之后"到目前为止发生了什么"的压缩表示（core/global_memory.py）
    globalMemory: Optional[str] = None
    # Moegirl-inspired ACG craft cards (distilled; never paste wiki into script)
    loreCraft: Optional[str] = None
    # User-uploaded reference docs (already extracted plain text)
    referenceDocs: Optional[str] = None
    # 作者按需摘掉的资料块 key（见 agent_context.EXCLUDABLE_SECTIONS）
    excludeSections: Optional[List[str]] = None
    # 这一轮用的是谁的钱：own = 作者自己的 Key；shared = 站内免费档（轻量模型 + 每日额度）
    credentialsMode: Optional[str] = None
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
    # 本次上下文预算（字符）：作者据此看到"用满了没有"，而不是只看到一个绝对数字
    budgetChars: Optional[int] = None
    # 这次是否**被裁过**（正文截断 / 整块让位 / 中段压缩任一发生）。
    # 与 `included` 里的中文标记是同一件事，但结构化的布尔量才能让界面稳定地提示。
    truncated: Optional[bool] = None
    # 「没装下的是什么、怎么取回来」的结构化报告（见 agent_context._budget_report）：
    # 界面上可以直接列清单，不必解析中文标记
    budgetReport: Optional[Dict[str, Any]] = None
    included: List[str] = Field(default_factory=list)
    # 「证明它记得」：这次实际依据的资料与摘录（前端可展开看原文）
    includedDetails: Optional[List[Dict[str, Any]]] = None
    # 这次没带的资料块 key（作者在「资料」里摘掉的、或按任务自动省去的）
    excludedSections: Optional[List[str]] = None
    # own = 作者自己的 Key；shared = 站内免费档（前端据此提示"长任务建议配 Key"）
    credentialsMode: Optional[str] = None
    craftMode: Optional[str] = None
    craftReason: Optional[str] = None
    mentorIds: Optional[List[str]] = None
    lensIds: Optional[List[str]] = None
    # Self-review outcome note
    selfReview: Optional[str] = None
    # 写后廉价闸（确定性；见 core/write_gate.py）
    writeGate: Optional[Dict[str, Any]] = None
    # 写路径材料预取（上下文被裁时服务端已取回的工具清单）
    retrievePrefetch: Optional[Dict[str, Any]] = None
    # LLM chat-memory summary produced this run (persisted to the session)
    chatMemorySummary: Optional[str] = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str
    actions: List[AgentAction] = Field(default_factory=list)
    model: str
    # What context slices were injected (transparency for long-form)
    contextMeta: Optional[AgentContextMeta] = None
    # Multi-step tool trajectory (thought / tool_call / tool_result / actions / done)
    trace: Optional[List[Dict[str, Any]]] = None
