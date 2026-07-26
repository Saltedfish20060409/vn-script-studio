import type { MapElementKind, MapStyleId } from "./types.js";

export interface MapElementPreset {
  kind: MapElementKind;
  name: string;
  icon: string;
  color: string;
  hint: string;
}

export const MAP_STYLES: {
  id: MapStyleId;
  name: string;
  genre: string;
  desc: string;
}[] = [
  {
    id: "campus",
    name: "学院清亮",
    genre: "校园",
    desc: "木框软木公告板为主体，贴纸条与图钉",
  },
  {
    id: "romance",
    name: "恋粉色纸",
    genre: "恋爱",
    desc: "粉信纸、邮戳与火漆印为主体",
  },
  {
    id: "cyber",
    name: "赛博夜城",
    genre: "科幻",
    desc: "科技对话框 HUD 为主体，扫描线与角标",
  },
  {
    id: "isekai",
    name: "异世界羊皮",
    genre: "奇幻",
    desc: "卷轴羊皮纸为主体，纹章装饰",
  },
  {
    id: "urban",
    name: "都市线稿",
    genre: "现代",
    desc: "城市蓝图图纸为主体",
  },
  {
    id: "mystery",
    name: "悬疑案卷",
    genre: "推理",
    desc: "案件板 + 拍立得与红线为主体",
  },
  {
    id: "horror",
    name: "惊悚暗室",
    genre: "恐怖",
    desc: "斑驳墙面与歪斜旧照片为主体",
  },
];

const KNOWN = new Set(MAP_STYLES.map((s) => s.id));

export function normalizeMapStyle(style?: MapStyleId): MapStyleId {
  const map: Record<string, MapStyleId> = {
    ink: "urban",
    soft: "romance",
    neon: "cyber",
    parchment: "isekai",
    slate: "urban",
  };
  if (!style) return "campus";
  const next = map[style] ?? style;
  return KNOWN.has(next) ? next : "campus";
}

/** Common visual-novel scene markers */
export const MAP_ELEMENT_PRESETS: MapElementPreset[] = [
  { kind: "station", name: "车站", icon: "🚉", color: "#5b8def", hint: "月台 / 换乘" },
  { kind: "plaza", name: "广场", icon: "🏛️", color: "#c4a574", hint: "集会 / 喷泉" },
  { kind: "park", name: "公园", icon: "🌳", color: "#5a9a6a", hint: "散步 / 约会" },
  { kind: "hospital", name: "医院", icon: "🏥", color: "#e07070", hint: "病房 / 走廊" },
  { kind: "school", name: "学校", icon: "🏫", color: "#6b8cae", hint: "教室 / 天台" },
  { kind: "cafe", name: "咖啡馆", icon: "☕", color: "#b08968", hint: "闲谈场景" },
  { kind: "home", name: "自宅", icon: "🏠", color: "#d4a017", hint: "主角房间" },
  { kind: "shop", name: "商店", icon: "🏪", color: "#7eb8da", hint: "便利店 / 街边" },
  { kind: "office", name: "公司", icon: "🏢", color: "#6b7280", hint: "写字楼" },
  { kind: "apartment", name: "公寓", icon: "🏬", color: "#8b7bb8", hint: "合租 / 邻居" },
  { kind: "temple", name: "神社/寺", icon: "⛩️", color: "#c45c4a", hint: "祈愿 / 祭典" },
  { kind: "forest", name: "树林", icon: "🌲", color: "#3d6b4f", hint: "秘密小路" },
  { kind: "beach", name: "海边", icon: "🌊", color: "#4a90a4", hint: "度假线" },
  { kind: "bridge", name: "桥", icon: "🌉", color: "#7a8b99", hint: "分手 / 重逢" },
  { kind: "landmark", name: "地标", icon: "📍", color: "#b85c38", hint: "标志建筑" },
  { kind: "custom", name: "自定义", icon: "✦", color: "#8b7bb8", hint: "自订图标" },
];

export function presetByKind(kind?: MapElementKind): MapElementPreset {
  return (
    MAP_ELEMENT_PRESETS.find((p) => p.kind === kind) ??
    MAP_ELEMENT_PRESETS.find((p) => p.kind === "landmark")!
  );
}
