type CharacterId = string;
type LabelId = string;
type LocationId = string;

interface VoiceCorpusLine {
  speaker: string;
  text: string;
}

export interface VoiceCorpusSample {
  id: string;
  scenario: string;
  scenarioLabel?: string;
  axis?: string;
  hypothesis?: string;
  lines: VoiceCorpusLine[];
  source?:
    | "preference"
    | "import"
    | "script_extract"
    | "scene"
    | "interview"
    | "manual"
    | "chat"
    | string;
  userNote?: string;
  rejectedSummary?: string;
  createdAt?: string;
}

export interface Character {
  id: CharacterId;
  /** Ren'Py define name, e.g. eileen */
  defineName: string;
  displayName: string;
  color?: string;
  /** Speaking voice / personality for AI */
  voice?: string;
  bio?: string;
  /** Optional image tag for show statements */
  imageTag?: string;
  /** Relations to other characters (free text) */
  relationships?: string;
  /** Preference-calibrated dialogue evidence */
  voiceCorpus?: VoiceCorpusSample[];
  /** Lightweight mind card markdown */
  voiceMind?: string;
  /** Notes from rejected variants */
  voiceRejectNotes?: string[];
  /** Why a pick felt right */
  voicePreferNotes?: string[];
  /** 其它叫法：绰号、旧名、英文 id —— AI 检索时一并命中 */
  aliases?: string[];
}

export type ScriptBlock =
  | { type: "label"; id: LabelId; name: string }
  | { type: "scene"; image: string; transition?: string }
  | { type: "show"; image: string; at?: string }
  | { type: "hide"; image: string }
  | { type: "narration"; text: string }
  | { type: "dialogue"; characterId: CharacterId; text: string }
  | { type: "menu"; id: string; prompt?: string; choices: MenuChoice[] }
  | { type: "jump"; target: LabelId }
  | { type: "return" }
  | { type: "comment"; text: string }
  | { type: "raw"; code: string }
  // ---- 演出指令（音频 / 等待 / 镜头 / 特效）----
  | { type: "music"; action: "play" | "stop"; file?: string; fade?: number }
  | { type: "sound"; action: "play" | "stop"; file?: string; volume?: number }
  | { type: "voice"; action: "play" | "stop"; file?: string }
  | { type: "wait"; seconds?: number }
  | { type: "camera"; zoom?: number; x?: number; y?: number; at?: string }
  | { type: "effect"; kind: string; duration?: number }
  // ---- 变量与条件 ----
  | {
      type: "set";
      key: string;
      op?: "=" | "+=" | "-=";
      value?: number | boolean | string;
    }
  | { type: "if"; branches: IfBranch[] };

export interface IfBranch {
  /** 空 = 否则分支 */
  condition?: string;
  blocks: ScriptBlock[];
}

export interface MenuChoice {
  text: string;
  jump?: LabelId;
  blocks?: ScriptBlock[];
  /** 条件选项：只有条件成立时才出现（对应 Ren'Py 的 `"文本" if cond:`） */
  condition?: string;
}

export interface SceneChapter {
  id: string;
  title: string;
  synopsis?: string;
  blocks: ScriptBlock[];
  /** Natural-language manuscript (default writing surface). */
  prose?: string;
  /** Fingerprint of prose last used to generate RPY. */
  rpyFromProseHash?: string;
  /** 所属卷（可选）。没有卷 = 平铺章节，老工程行为不变。 */
  volumeId?: string;
  /**
   * 连载发布状态：有值 = 这一章标记为已发布（ISO 时间）。
   * 记时间而不是布尔，是因为连载作者会回头改已发布的章、改完再发一次。
   */
  publishedAt?: string;
}

/** 一卷（轻小说/网文的连载单位）。顺序就是数组顺序。 */
export interface Volume {
  id: string;
  title: string;
  /** 卷备注（这一卷要写什么），不进正文 */
  note?: string;
}

/** Story setting — independent from character cards */
export interface StoryBible {
  /** 世界观 / 规则 */
  world?: string;
  /** 故事背景 / 前情 */
  background?: string;
  /** 大纲 / 节拍 */
  outline?: string;
  /** 主题、基调、禁忌 */
  themes?: string;
  /** 其他备忘 */
  notes?: string;
}

type LocationRelation =
  | "adjacent"
  | "contains"
  | "inside"
  | "above"
  | "below"
  | "leads_to"
  | "visible_from"
  | "other";

export type MapStyleId = "default";

export type MapLineStyle = "solid" | "dashed" | "dotted" | "double" | "rail" | "magic";

export const MAP_LINE_STYLE_LABELS: Record<MapLineStyle, string> = {
  solid: "实线",
  dashed: "虚线",
  dotted: "点线",
  double: "双线",
  rail: "轨道",
  magic: "魔力轨",
};

export interface MapStroke {
  id: string;
  /** Freehand polyline in world coords */
  points: { x: number; y: number }[];
  color: string;
  width: number;
  kind: "path" | "mark";
}

export type MapElementKind =
  | "station"
  | "plaza"
  | "park"
  | "hospital"
  | "school"
  | "cafe"
  | "home"
  | "shop"
  | "office"
  | "apartment"
  | "temple"
  | "forest"
  | "beach"
  | "bridge"
  | "landmark"
  | "custom";

export interface Location {
  id: LocationId;
  name: string;
  /** Hint for Ren'Py scene image, e.g. bg station_night */
  imageTag?: string;
  description?: string;
  tags?: string[];
  /** Story-map coordinates */
  mapX?: number;
  mapY?: number;
  elementKind?: MapElementKind;
  /** Emoji / short glyph shown on map */
  icon?: string;
  color?: string;
  scale?: number;
  rotation?: number;
  /** 其它叫法：别称、俗称 —— AI 检索时一并命中 */
  aliases?: string[];
}

/**
 * 设定条目：一条可被 AI 检索的设定（门派 / 系统 / 规则 / 组织 / 历史事件…）。
 *
 * 为什么需要它：`bible` 那五个字段各有几百字预算，装不下大体量设定。
 * 条目可以堆很多条，每条自带**触发词**；提问命中哪条就带哪条进上下文，
 * 所以设定再大，单次进去的也只有相关的那几条。
 */
/** 设定条目的实体链接：这条设定讲的是谁 / 在哪 / 属于哪一章 */
export interface LoreLink {
  toType: "character" | "location" | "chapter";
  toId: string;
  note?: string;
}

export interface LoreEntry {
  id: string;
  title: string;
  body: string;
  /** 触发词 / 别名：提问里出现就命中（比正文里恰好撞词可靠得多） */
  keywords?: string[];
  tags?: string[];
  /** 钉住：不管问什么，每轮都带上（"绝不能写错"的那几条） */
  pinned?: boolean;
  /** 同分时排序权重，大的优先 */
  priority?: number;
  /** 实体链接：检索会沿着它多走一步（命中条目带出关联实体，反之亦然） */
  links?: LoreLink[];
}

export interface CustomMapElementDef {
  id: string;
  name: string;
  icon: string;
  color: string;
}

export interface LocationLink {
  id: string;
  fromId: LocationId;
  toId: LocationId;
  relation: LocationRelation;
  note?: string;
  lineStyle?: MapLineStyle;
}

export interface GameVariable {
  id: string;
  name: string;
  /** Ren'Py / code identifier */
  key: string;
  type: "number" | "bool" | "string";
  value: number | boolean | string;
  /** e.g. affection toward character id */
  bindCharacterId?: string;
  note?: string;
}

interface SpriteExpression {
  id: string;
  name: string;
  /** Ren'Py image tag suffix, e.g. sad */
  tag: string;
  note?: string;
}

export interface SpriteDef {
  id: string;
  name: string;
  /** Base Ren'Py image name, e.g. linxia */
  imageTag: string;
  characterId?: string;
  expressions: SpriteExpression[];
}

interface ProjectSnapshot {
  id: string;
  label: string;
  createdAt: string;
  /** Content-addressed object, or legacy JSON string */
  payload: Record<string, unknown> | string;
  contentHash?: string;
}

export interface ChapterIndexEntry {
  chapterId: string;
  title: string;
  hash: string;
  synopsis?: string;
  speakers?: string[];
  openHook?: string;
  closeHook?: string;
}

/** 章节事实（账本）：保存时自动入库，纯本地抽取，不调模型 */
export interface LedgerChapterFact {
  id?: string;
  chapterId: string;
  title?: string;
  facts?: string[];
  keyQuotes?: string[];
  /** 入库时的正文内容指纹 —— 变了才会重算 */
  sourceHash?: string;
  updatedAt?: string;
}

/** 角色状态快照（账本）：最近一次情绪 / 动作 / 关系 */
export interface LedgerCharacterState {
  id?: string;
  chapterId?: string;
  chapterTitle?: string;
  characterId?: string;
  characterName?: string;
  emotion?: string;
  body?: string;
  relations?: string;
  updatedAt?: string;
}

/** 伏笔（账本）：章末钩子自动记为 open，可在提示词里让续写回收 */
export interface LedgerForeshadow {
  id?: string;
  hook?: string;
  plantedChapter?: string;
  /** open | paid */
  status?: string;
  /** 在哪一章被回收（有了它才能说"埋了 N 章才收"） */
  paidInChapter?: string | null;
  note?: string;
  updatedAt?: string;
}

interface LedgerEvent {
  id?: string;
  chapterId?: string;
  summary?: string;
  updatedAt?: string;
}

/** 写作账本：保存时由服务端自动维护（见 backend/app/core/pipeline/ledger.py） */
interface WritingLedger {
  chapterFacts?: LedgerChapterFact[];
  characterStates?: LedgerCharacterState[];
  foreshadows?: LedgerForeshadow[];
  events?: LedgerEvent[];
  updatedAt?: string;
}

interface FactEvidence {
  /** script | bible | card | paste | upload | agent */
  source: string;
  chapterId?: string;
  quote?: string;
  field?: string;
  fingerprint?: string;
}

export interface CharacterLink {
  id: string;
  fromId: CharacterId;
  toId: CharacterId;
  label: string;
  evidence?: FactEvidence[];
  stale?: boolean;
  staleReason?: string;
  acceptedAt?: string;
}

export interface TimelineEvent {
  id: string;
  title: string;
  /** Free-form time label, e.g. 第一晚 / Day 3 */
  when?: string;
  chapterRef?: string;
  summary?: string;
  order: number;
  evidence?: FactEvidence[];
  stale?: boolean;
  staleReason?: string;
  acceptedAt?: string;
}

interface AnalysisMeta {
  chapterFingerprints?: Record<string, string>;
  bibleFingerprint?: string;
  characterFingerprints?: Record<string, string>;
  lastScanAt?: string;
  lastReconcileAt?: string;
}

export interface FactInboxItem {
  id: string;
  kind: "character_link" | "timeline_event" | "source_snippet" | string;
  payload: Record<string, unknown>;
  evidence: FactEvidence[];
  status: string;
  dedupeKey: string;
  createdAt?: string | null;
}

/** 地图测距的比例尺与默认交通方式（作品数据，跨设备同步） */
export interface MapMeasure {
  /** 地图尺度预设：城市 / 地区 / 大陆 */
  scale: "urban" | "regional" | "continental";
  /** 多少像素 */
  px: number;
  /** 等于多少公里 */
  km: number;
  /** 默认交通方式 id */
  transport: string;
}

/** 写作目标（可选）：三个口径的字数目标；留空 = 不显示进度 */
export interface WritingGoals {
  /** 日更目标（按写作统计的当日净增字数算） */
  daily?: number;
  /** 单章目标（按当前章节实时字数算） */
  chapter?: number;
  /** 单卷目标（按写作统计的该卷累计字数算） */
  volume?: number;
}

export interface VnProject {
  id: string;
  title: string;
  logline?: string;
  genre?: string;
  characters: Character[];
  chapters: SceneChapter[];
  /** 卷（可选）：章节按 volumeId 归属；空/缺省 = 平铺章节 */
  volumes?: Volume[];
  /** @deprecated Mirror of bible.world for older saves — UI edits bible.world only */
  lore?: string;
  bible?: StoryBible;
  locations?: Location[];
  locationLinks?: LocationLink[];
  mapStyle?: MapStyleId;
  /** 地图测距的比例尺与默认交通方式（作品数据；缺省时用本机默认） */
  mapMeasure?: MapMeasure;
  customMapElements?: CustomMapElementDef[];
  mapStrokes?: MapStroke[];
  characterLinks?: CharacterLink[];
  /** 设定条目：可无上限地堆，AI 按触发词/正文检索，只有命中的进上下文 */
  loreEntries?: LoreEntry[];
  timeline?: TimelineEvent[];
  variables?: GameVariable[];
  sprites?: SpriteDef[];
  snapshots?: ProjectSnapshot[];
  /** Extractive chapter digests / content hashes (server-refreshed on save) */
  chapterIndex?: ChapterIndexEntry[];
  writingLedger?: WritingLedger;
  /** Recent harness / pipeline run summaries (capped) */
  harnessRuns?: Array<Record<string, unknown>>;
  /** Active writing mentor packs (methodology; cannot override style_guide) */
  writingMentors?: {
    activeIds?: string[];
    customPacks?: Array<{
      id: string;
      name: string;
      markdown: string;
      updatedAt?: string;
    }>;
  };
  /** Optional author lenses for multi-perspective review/plot (default off) */
  authorLenses?: {
    activeIds?: string[];
    customPacks?: Array<{
      id: string;
      name: string;
      markdown: string;
      updatedAt?: string;
    }>;
  };
  analysisMeta?: AnalysisMeta;
  /** 写作目标（可选）：写作页显示进度与"还差多少"；缺省 = 不显示 */
  writingGoals?: WritingGoals;
  /**
   * 作品体裁：决定界面用哪套词（剧本 / 正文·分卷·投稿）。
   * 缺省或 `"auto"` = 按 `genre` 关键词推断；作者选定后以这里为准。
   */
  writingGenre?: "auto" | "vn" | "novel";
  /** Phase 2: persisted voice-check reports */
  voiceReports?: Array<Record<string, unknown>>;
  /** Author style memory: LLM-learned writing-style guide from this novel */
  styleMemory?: {
    guide?: string;
    samples?: string[];
    updatedAt?: string;
  };
  /** Local read-only share id */
  shareId?: string;
  updatedAt: string;
}

/** Structured operations the studio Agent may return */
export type AgentAction =
  | {
      op: "add_character";
      displayName: string;
      defineName?: string;
      color?: string;
      voice?: string;
      bio?: string;
      relationships?: string;
    }
  | {
      op: "update_character";
      ref: string;
      patch: Partial<
        Pick<
          Character,
          "displayName" | "defineName" | "color" | "voice" | "bio" | "relationships"
        >
      >;
    }
  | { op: "delete_character"; ref: string }
  | {
      op: "add_location";
      name: string;
      imageTag?: string;
      description?: string;
      mapX?: number;
      mapY?: number;
      tags?: string[];
    }
  | {
      op: "update_location";
      ref: string;
      patch: Partial<
        Pick<Location, "name" | "imageTag" | "description" | "tags" | "mapX" | "mapY">
      >;
    }
  | { op: "delete_location"; ref: string }
  | {
      op: "add_location_link";
      fromRef: string;
      toRef: string;
      relation?: LocationRelation;
      note?: string;
    }
  | { op: "delete_location_link"; fromRef: string; toRef: string }
  | { op: "add_chapter"; title: string; synopsis?: string }
  | { op: "delete_chapter"; ref: string }
  | { op: "rename_chapter"; ref: string; title: string }
  | { op: "append_script"; chapterRef?: string; text: string }
  | { op: "replace_script"; chapterRef?: string; text: string }
  | { op: "update_bible"; patch: Partial<StoryBible> }
  | { op: "update_meta"; title?: string; logline?: string; genre?: string }
  | {
      op: "propose_character_link";
      fromRef: string;
      toRef: string;
      label?: string;
      quote?: string;
    }
  | {
      op: "propose_timeline_event";
      title: string;
      when?: string;
      summary?: string;
      chapterRef?: string;
      order?: number;
    }
  | {
      /** 设定条目只能提议：接受后才写进 loreEntries */
      op: "propose_lore_entries";
      entries: Array<{ title: string; body?: string; keywords?: string[] }>;
      quote?: string;
    }
  | {
      op: "add_character_link";
      fromRef: string;
      toRef: string;
      label?: string;
    }
  | {
      op: "update_character_link";
      id?: string;
      ref?: string;
      fromRef?: string;
      toRef?: string;
      label?: string;
    }
  | {
      op: "delete_character_link";
      id?: string;
      ref?: string;
      fromRef?: string;
      toRef?: string;
    }
  | {
      op: "add_timeline_event";
      title: string;
      when?: string;
      summary?: string;
      chapterRef?: string;
      order?: number;
    }
  | {
      op: "update_timeline_event";
      id?: string;
      ref?: string;
      title?: string;
      when?: string;
      summary?: string;
      chapterRef?: string;
      order?: number;
    }
  | { op: "delete_timeline_event"; id?: string; ref?: string; title?: string }
  | { op: "scan_facts"; chapterRef?: string; includePaste?: boolean };

export interface AgentTraceEvent {
  type: "thought" | "tool_call" | "tool_result" | "actions" | "done" | "memory" | string;
  text?: string;
  id?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  ok?: boolean;
  preview?: string;
  actions?: AgentAction[];
  skipped?: string[];
  message?: string;
  note?: string;
}

export interface AgentChatMessage {
  role: "user" | "assistant";
  content: string;
  /** Optional action chip under assistant bubble (persisted with conversation). */
  action?: {
    type: "open_revise_review";
    chapterId: string;
    label?: string;
  };
  /** Multi-step tool trajectory for this assistant turn */
  trace?: AgentTraceEvent[];
}

/** Writing-task mode for Agent retrieval + prompt bias */
export type AgentTaskKind =
  | "chat"
  | "continue"
  | "rewrite"
  | "polish"
  | "branch"
  | "outline"
  | "voice"
  | "consistency"
  | "scene";

/** 资料块的人话名（后端给 `label`，前端不在本地维护一份对照表）。 */
export interface AgentSectionRef {
  key: string;
  label: string;
}

/** 因为篇幅被整块省去的一块资料：怎么取回来说在 `retrieve` 里（可执行）。 */
export interface AgentDroppedSection extends AgentSectionRef {
  retrieve: string;
}

/** 被截断/压缩的一块内容（正文、其他章摘录、中段）。 */
export interface AgentTrimmedPart {
  kind: "focus" | "otherChapters" | "middle" | string;
  label: string;
  detail: string;
  retrieve: string;
  keptChars?: number;
  totalChars?: number;
}

export interface AgentBudgetReport {
  usedChars: number;
  budgetChars: number;
  usageRatio: number;
  /** 因为篇幅没装下（要处理） */
  droppedSections: AgentDroppedSection[];
  trimmedParts: AgentTrimmedPart[];
  /** 按任务省去（属于设计，不是"没装下"） */
  excludedByTask: AgentSectionRef[];
  /** 这次真的带上的资料块 */
  includedSections: AgentSectionRef[];
  truncated: boolean;
}

export interface AgentContextMeta {
  task: AgentTaskKind;
  charsUsed: number;
  /** 本次上下文预算（字符）：跟 charsUsed 一起才能说清"用满了没有" */
  budgetChars?: number;
  /** 这次是否被裁过（正文截断 / 整块让位 / 中段压缩任一发生） */
  truncated?: boolean;
  /**
   * 「这次怎么拼的、有没有没装下的」的结构化报告。
   *
   * 有一条重要的区分（后端保证的）：`droppedSections`/`trimmedParts` 是**因为篇幅没装下**
   * （要处理），`excludedByTask` 是**按任务省去**（立绘/变量这类机制资料对写散文没用，
   * 属于设计，不该拿来吓作者）。
   */
  budgetReport?: AgentBudgetReport;
  included: string[];
  /** 「证明它记得」：这次实际依据的资料与摘录（可展开看原文） */
  includedDetails?: Array<{ label?: string; preview?: string }>;
  /** 这次没带的资料块 key（作者摘掉的 / 按任务自动省去的） */
  excludedSections?: string[];
  /** own = 作者自己的 Key；shared = 站内免费档（前端据此提示长任务配 Key） */
  credentialsMode?: string;
  craftMode?: "off" | "lite" | "full";
  craftReason?: string;
  mentorIds?: string[];
  lensIds?: string[];
  /** Self-review outcome note */
  selfReview?: string;
}

interface VoiceIssue {
  character: string;
  severity: string;
  quote: string;
  note: string;
  suggestion?: string;
}

export interface VoiceReport {
  summary: string;
  model: string;
  issues: VoiceIssue[];
}
