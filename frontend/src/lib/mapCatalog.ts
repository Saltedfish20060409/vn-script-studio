import type { MapElementKind, MapStyleId } from "../types/vn";

export interface MapElementPreset {
  kind: MapElementKind;
  name: string;
  /** Glyph key (usually same as kind); never emoji. */
  icon: string;
  color: string;
  hint: string;
}

/** Sole Persona LOC_MAP board — genre skins were removed. */
export const DEFAULT_MAP_STYLE: MapStyleId = "default";

/** @deprecated Multi-skin list retired; kept for any stray imports. */
export const MAP_STYLES: {
  id: MapStyleId;
  name: string;
  genre: string;
  desc: string;
}[] = [
  {
    id: "default",
    name: "作战图",
    genre: "Persona",
    desc: "统一 LOC_MAP 底板",
  },
];

/** Collapse any legacy / unknown style id to the single board. */
export function normalizeMapStyle(_style?: string | null): MapStyleId {
  return DEFAULT_MAP_STYLE;
}

/** Common visual-novel scene markers — geometric glyphs, not emoji */
export const MAP_ELEMENT_PRESETS: MapElementPreset[] = [
  {
    kind: "station",
    name: "车站",
    icon: "station",
    color: "#002fa7",
    hint: "月台 / 换乘",
  },
  { kind: "plaza", name: "广场", icon: "plaza", color: "#4a5568", hint: "集会 / 喷泉" },
  { kind: "park", name: "公园", icon: "park", color: "#0f766e", hint: "散步 / 约会" },
  {
    kind: "hospital",
    name: "医院",
    icon: "hospital",
    color: "#be123c",
    hint: "病房 / 走廊",
  },
  {
    kind: "school",
    name: "学校",
    icon: "school",
    color: "#1d4ed8",
    hint: "教室 / 天台",
  },
  { kind: "cafe", name: "咖啡馆", icon: "cafe", color: "#9a3412", hint: "闲谈场景" },
  { kind: "home", name: "自宅", icon: "home", color: "#a16207", hint: "主角房间" },
  { kind: "shop", name: "商店", icon: "shop", color: "#0369a1", hint: "便利店 / 街边" },
  { kind: "office", name: "公司", icon: "office", color: "#475569", hint: "写字楼" },
  {
    kind: "apartment",
    name: "公寓",
    icon: "apartment",
    color: "#6d28d9",
    hint: "合租 / 邻居",
  },
  {
    kind: "temple",
    name: "神社/寺",
    icon: "temple",
    color: "#b91c1c",
    hint: "祈愿 / 祭典",
  },
  { kind: "forest", name: "树林", icon: "forest", color: "#166534", hint: "秘密小路" },
  { kind: "beach", name: "海边", icon: "beach", color: "#0e7490", hint: "度假线" },
  { kind: "bridge", name: "桥", icon: "bridge", color: "#64748b", hint: "分手 / 重逢" },
  {
    kind: "landmark",
    name: "地标",
    icon: "landmark",
    color: "#c2410c",
    hint: "标志建筑",
  },
  {
    kind: "custom",
    name: "自定义",
    icon: "custom",
    color: "#002fa7",
    hint: "自订地点",
  },
];

export function presetByKind(kind?: MapElementKind): MapElementPreset {
  return (
    MAP_ELEMENT_PRESETS.find((p) => p.kind === kind) ??
    MAP_ELEMENT_PRESETS.find((p) => p.kind === "landmark")!
  );
}
