/**
 * 地图测距与行程时间（纯计算）。
 *
 * ## 为什么是"速度"而不是"一天走多远"
 *
 * 第一版按「一天走多远」算，于是所有读数都落在"天"上：日常题材（家→学校→商场只差几百米）
 * 会得到"不到半天"这种没用的结果，交通方式也只有步行/马车/船那类长途选项。
 * 现在按**速度 + 每次出行的固定耗时**算真实时长（分钟），再**自适应地**用
 * 分钟 / 小时 / 天 表达——城市题材出"约 8 分钟"，大陆题材出"约 3.3 天"，同一套公式。
 *
 * 距离同理：小于 1 公里用米，10 公里内保留一位小数，再往上取整公里。
 */

import type { MapMeasurePrefs } from "./mapFeatures";

export type TransportMode = {
  id: string;
  label: string;
  /** 平均时速（公里/小时） */
  kmh: number;
  /** 一天实际行进多少小时（决定"几天"怎么折算；城市通勤用不到） */
  hoursPerDay: number;
  /** 每次出行的固定开销（分钟）：等车、上下楼、系马之类 */
  overheadMin: number;
};

/** 全部交通方式。`urban` 组适合城市/日常，`long` 组适合长途与异世界。 */
export const TRANSPORT_MODES: TransportMode[] = [
  { id: "walk", label: "步行", kmh: 5, hoursPerDay: 8, overheadMin: 0 },
  { id: "bike", label: "自行车", kmh: 15, hoursPerDay: 8, overheadMin: 2 },
  { id: "transit", label: "公交/地铁", kmh: 25, hoursPerDay: 14, overheadMin: 8 },
  { id: "car", label: "开车", kmh: 40, hoursPerDay: 12, overheadMin: 5 },
  { id: "horse", label: "骑马", kmh: 12, hoursPerDay: 7, overheadMin: 5 },
  { id: "cart", label: "马车", kmh: 6, hoursPerDay: 8, overheadMin: 10 },
  { id: "ship", label: "船", kmh: 15, hoursPerDay: 24, overheadMin: 30 },
  { id: "airship", label: "飞艇", kmh: 60, hoursPerDay: 24, overheadMin: 60 },
];

/** 每个「地图尺度」推荐先显示哪几种交通方式（列表里仍然可以选全部） */
export const URBAN_MODE_IDS = ["walk", "bike", "transit", "car"];
export const LONG_MODE_IDS = ["walk", "horse", "cart", "ship", "airship"];

export function transportById(id: string): TransportMode {
  return TRANSPORT_MODES.find((m) => m.id === id) ?? TRANSPORT_MODES[0];
}

export function recommendedModes(scale: MapScaleId | string): TransportMode[] {
  const ids = scale === "urban" ? URBAN_MODE_IDS : LONG_MODE_IDS;
  const picked = ids.map(transportById);
  // 其余方式排在后面（仍可选，别把它们藏起来）
  const rest = TRANSPORT_MODES.filter((m) => !ids.includes(m.id));
  return [...picked, ...rest];
}

/** 两点之间的像素距离（世界坐标）。 */
export function pixelDistance(
  a: { x: number; y: number },
  b: { x: number; y: number }
): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** 像素 → 公里。`measure.px` 像素等于 `measure.km` 公里。 */
export function kmFromPixels(
  px: number,
  measure: Pick<MapMeasurePrefs, "px" | "km">
): number {
  const unitPx = measure.px > 0 ? measure.px : 100;
  const unitKm = measure.km > 0 ? measure.km : 10;
  return (px / unitPx) * unitKm;
}

export function distanceKm(
  a: { x: number; y: number },
  b: { x: number; y: number },
  measure: Pick<MapMeasurePrefs, "px" | "km">
): number {
  return kmFromPixels(pixelDistance(a, b), measure);
}

/** 这一段路要多久（分钟，含该方式的固定开销）。 */
export function travelMinutes(km: number, mode: TransportMode | string): number {
  const resolved = typeof mode === "string" ? transportById(mode) : mode;
  const kmh = resolved.kmh > 0 ? resolved.kmh : 5;
  return (km / kmh) * 60 + Math.max(0, resolved.overheadMin);
}

/** 需要几个"行进日"（按该方式一天走几小时折算）。 */
export function travelDays(km: number, mode: TransportMode | string): number {
  const resolved = typeof mode === "string" ? transportById(mode) : mode;
  const perDay = resolved.hoursPerDay > 0 ? resolved.hoursPerDay : 8;
  return travelMinutes(km, resolved) / 60 / perDay;
}

/** 距离显示：<1 公里用米，<10 公里一位小数，其余取整公里。 */
export function formatKm(km: number): string {
  if (!Number.isFinite(km) || km <= 0) return "0 米";
  if (km < 1) {
    const meters = Math.max(10, Math.round((km * 1000) / 10) * 10);
    return `${meters} 米`;
  }
  if (km < 10) return `${km.toFixed(1)} 公里`;
  return `${Math.round(km)} 公里`;
}

/**
 * 时长显示：分钟 → 小时 → 天，按实际时长挑单位。
 * 半天以内（<12 小时）仍用小时；再长才折算成"天"，而且按该方式"一天走几小时"折算
 * （步行 80 小时是 10 天，不是 3.3 天）。
 */
export function formatDuration(minutes: number, mode: TransportMode | string): string {
  const resolved = typeof mode === "string" ? transportById(mode) : mode;
  if (!Number.isFinite(minutes) || minutes <= 0) return "0 分钟";
  if (minutes < 1) return "不到 1 分钟";
  if (minutes < 60) return `约 ${Math.round(minutes)} 分钟`;
  if (minutes < 60 * 12) return `约 ${(minutes / 60).toFixed(1)} 小时`;
  const perDay = resolved.hoursPerDay > 0 ? resolved.hoursPerDay : 8;
  const days = minutes / 60 / perDay;
  return days < 10 ? `约 ${days.toFixed(1)} 天` : `约 ${Math.round(days)} 天`;
}

/** 兼容旧调用：从公里直接得到"几天"的字符串（内部仍走真实时长）。 */
export function formatDays(days: number): string {
  if (!Number.isFinite(days) || days <= 0) return "0 天";
  if (days < 0.02) return "不到 1 分钟";
  if (days < 1 / 24) return `约 ${Math.round(days * 24 * 60)} 分钟`;
  if (days < 0.5) return `约 ${Math.round(days * 24)} 小时`;
  return days < 10 ? `约 ${days.toFixed(1)} 天` : `约 ${Math.round(days)} 天`;
}

/** 一行读法：约 3.2 公里 · 步行约 40 分钟 / 约 400 公里 · 骑马约 3.3 天 */
export function formatLegLabel(
  km: number,
  mode: TransportMode | string,
  opts: { includeKm?: boolean } = {}
): string {
  const resolved = typeof mode === "string" ? transportById(mode) : mode;
  const parts: string[] = [];
  if (opts.includeKm !== false) parts.push(`约 ${formatKm(km)}`);
  parts.push(`${resolved.label}${formatDuration(travelMinutes(km, resolved), resolved)}`);
  return parts.join(" · ");
}

/** 类型别名（放这里避免循环 import 的困扰） */
export type MapScaleId = "urban" | "regional" | "continental";
