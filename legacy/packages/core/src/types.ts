export type CharacterId = string;
export type LabelId = string;
export type LocationId = string;

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
  | { type: "raw"; code: string };

export interface MenuChoice {
  text: string;
  jump?: LabelId;
  blocks?: ScriptBlock[];
}

export interface SceneChapter {
  id: string;
  title: string;
  synopsis?: string;
  blocks: ScriptBlock[];
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

export type LocationRelation =
  | "adjacent"
  | "contains"
  | "inside"
  | "above"
  | "below"
  | "leads_to"
  | "visible_from"
  | "other";

export const LOCATION_RELATION_LABELS: Record<LocationRelation, string> = {
  adjacent: "相邻",
  contains: "包含",
  inside: "位于其内",
  above: "上方",
  below: "下方",
  leads_to: "通往",
  visible_from: "可见于",
  other: "其他",
};

export type MapStyleId =
  | "campus"
  | "romance"
  | "cyber"
  | "isekai"
  | "urban"
  | "mystery"
  | "horror"
  /** @deprecated migrated */
  | "ink"
  | "soft"
  | "neon"
  | "parchment"
  | "slate";

export type MapLineStyle =
  | "solid"
  | "dashed"
  | "dotted"
  | "double"
  | "rail"
  | "magic";

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

export interface SpriteExpression {
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

export interface ProjectSnapshot {
  id: string;
  label: string;
  createdAt: string;
  /** Full project JSON string to avoid circular typing weight */
  payload: string;
}

export interface CharacterLink {
  id: string;
  fromId: CharacterId;
  toId: CharacterId;
  label: string;
}

export interface TimelineEvent {
  id: string;
  title: string;
  /** Free-form time label, e.g. 第一晚 / Day 3 */
  when?: string;
  chapterRef?: string;
  summary?: string;
  order: number;
}

export interface VnProject {
  id: string;
  title: string;
  logline?: string;
  genre?: string;
  characters: Character[];
  chapters: SceneChapter[];
  /** @deprecated prefer bible.world — kept for older saves */
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
  /** Local read-only share id */
  shareId?: string;
  updatedAt: string;
}

export type AiAction =
  | "continue"
  | "rewrite"
  | "choices"
  | "polish"
  | "outline"
  | "character_voice";

export interface AiRequest {
  action: AiAction;
  project: VnProject;
  selection?: string;
  instruction?: string;
  format?: "renpy" | "blocks-json";
}

export interface AiResponse {
  content: string;
  model: string;
}

/** Structured operations the studio Agent may return */
export type AgentAction =
  | { op: "add_character"; displayName: string; defineName?: string; color?: string; voice?: string; bio?: string; relationships?: string }
  | { op: "update_character"; ref: string; patch: Partial<Pick<Character, "displayName" | "defineName" | "color" | "voice" | "bio" | "relationships">> }
  | { op: "delete_character"; ref: string }
  | { op: "add_location"; name: string; imageTag?: string; description?: string; mapX?: number; mapY?: number; tags?: string[] }
  | { op: "update_location"; ref: string; patch: Partial<Pick<Location, "name" | "imageTag" | "description" | "tags" | "mapX" | "mapY">> }
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
  | { op: "update_meta"; title?: string; logline?: string; genre?: string };

export interface AgentChatMessage {
  role: "user" | "assistant";
  content: string;
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

export interface AgentRequest {
  project: VnProject;
  messages: AgentChatMessage[];
  chapterId?: string;
  selection?: string;
  /** Specialized task — drives context retrieval and system hints */
  task?: AgentTaskKind;
  /** Rolling chat memory (extractive) for long conversations */
  chatMemory?: string;
  /** Writing craft injection: auto | off | lite | full */
  craftMode?: "auto" | "off" | "lite" | "full";
  /** Second-pass narrative/social self-review: auto | on | off */
  selfReview?: "auto" | "on" | "off";
  /** Optional separate critic model (cross-model review reduces self-bias) */
  criticApiKey?: string;
  criticApiBaseUrl?: string;
  criticApiModel?: string;
  /** Optional client-provided credentials (override server env) */
  apiKey?: string;
  apiBaseUrl?: string;
  apiModel?: string;
}

export interface AgentContextMeta {
  task: AgentTaskKind;
  charsUsed: number;
  included: string[];
  craftMode?: "off" | "lite" | "full";
  craftReason?: string;
  /** Self-review outcome note */
  selfReview?: string;
}

export interface AgentResponse {
  message: string;
  actions: AgentAction[];
  model: string;
  /** What context slices were injected (transparency for long-form) */
  contextMeta?: AgentContextMeta;
}
