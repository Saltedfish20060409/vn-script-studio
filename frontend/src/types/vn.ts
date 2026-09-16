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

export interface VnProject {
  id: string;
  title: string;
  logline?: string;
  genre?: string;
  characters: Character[];
  chapters: SceneChapter[];
  /** @deprecated Mirror of bible.world for older saves — UI edits bible.world only */
  lore?: string;
  bible?: StoryBible;
  locations?: Location[];
  locationLinks?: LocationLink[];
  mapStyle?: MapStyleId;
  customMapElements?: CustomMapElementDef[];
  mapStrokes?: MapStroke[];
  characterLinks?: CharacterLink[];
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

export interface AgentContextMeta {
  task: AgentTaskKind;
  charsUsed: number;
  included: string[];
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
