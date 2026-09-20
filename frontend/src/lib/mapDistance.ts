/**
 * 地图测距与行程时间（纯计算）。
 *
 * 用途：剧情里"从这里到那里要几天"最容易自相矛盾。这里按比例尺把世界坐标的像素距离
 * 换算成公里，再按交通方式给出天数，写正文时可以直接引用。
 */

import type { MapMeasurePrefs } from "./mapFeatures";

export type TransportMode = {
  id: string;
  label: string;
  /** 一天能走多远（公里）。数值是常见设定的量级，可按作品自行改比例尺来校准。 */
  kmPerDay: number;
};

export const TRANSPORT_MODES: TransportMode[] = [
  { id: "walk", label: "步行", kmPerDay: 30 },
  { id: "horse", label: "骑马", kmPerDay: 80 },
  { id: "cart", label: "马车", kmPerDay: 50 },
  { id: "ship", label: "船", kmPerDay: 120 },
  { id: "airship", label: "飞艇", kmPerDay: 300 },
];

export function transportById(id: string): TransportMode {
  return TRANSPORT_MODES.find((m) => m.id === id) ?? TRANSPORT_MODES[0];
}

/** 两点之间的像素距离（世界坐标）。 */
export function pixelDistance(
  a: { x: number; y: number },
  b: { x: number; y: number }
): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/**
 * 像素 → 公里。
 * `measure.px` 像素等于 `measure.km` 公里（默认 100px = 10km）。
 */
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

/** 需要走几天（可以是小数）。 */
export function travelDays(km: number, mode: TransportMode | string): number {
  const resolved = typeof mode === "string" ? transportById(mode) : mode;
  const perDay = resolved.kmPerDay > 0 ? resolved.kmPerDay : 30;
  return km / perDay;
}

/** 公里数的显示：不足 10 公里保留一位小数，其余取整。 */
export function formatKm(km: number): string {
  if (!Number.isFinite(km) || km <= 0) return "0 公里";
  if (km < 10) return `${km.toFixed(1)} 公里`;
  return `${Math.round(km)} 公里`;
}

/** 天数的显示：半天以内说"不到半天"，1 天上下取整，多天保留一位小数。 */
export function formatDays(days: number): string {
  if (!Number.isFinite(days) || days <= 0) return "0 天";
  if (days < 0.5) return "不到半天";
  if (days < 1) return "半天";
  if (days < 10) return `${days.toFixed(1)} 天`;
  return `${Math.round(days)} 天`;
}

/** 一行读法：约 120 公里 · 步行约 4 天 */
export function formatLegLabel(
  km: number,
  mode: TransportMode | string,
  opts: { includeKm?: boolean } = {}
): string {
  const resolved = typeof mode === "string" ? transportById(mode) : mode;
  const parts: string[] = [];
  if (opts.includeKm !== false) parts.push(`约 ${formatKm(km)}`);
  parts.push(`${resolved.label}约 ${formatDays(travelDays(km, resolved))}`);
  return parts.join(" · ");
}
