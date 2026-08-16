import type {
  CustomMapElementDef,
  Location,
  MapLineStyle,
  MapStroke,
} from "../types/vn";
import { presetByKind } from "./mapCatalog";
import { isGlyphKey } from "./mapGlyph";

/** Large playable world — camera clamps so you never see empty void */
export const WORLD_W = 4800;
export const WORLD_H = 3600;
/** Persona LOC_MAP HUD stage sits in the center of the world */
export const STAGE_W = 2200;
export const STAGE_H = 1500;
export const STAGE_X = (WORLD_W - STAGE_W) / 2;
export const STAGE_Y = (WORLD_H - STAGE_H) / 2;

export function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}

export function distToSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number
) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-6) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = clamp(t, 0, 1);
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export function strokeHitsPoint(
  stroke: MapStroke,
  x: number,
  y: number,
  radius: number
): boolean {
  const thr = radius + stroke.width / 2;
  const pts = stroke.points;
  if (pts.length === 1) {
    return Math.hypot(pts[0].x - x, pts[0].y - y) <= thr;
  }
  for (let i = 1; i < pts.length; i++) {
    if (distToSegment(x, y, pts[i - 1].x, pts[i - 1].y, pts[i].x, pts[i].y) <= thr) {
      return true;
    }
  }
  return false;
}

export function resolvePin(
  loc: Location,
  customs: CustomMapElementDef[]
): { glyph: string; color: string } {
  if (loc.elementKind === "custom" && loc.tags?.[0]) {
    const c = customs.find((x) => x.id === loc.tags![0]);
    if (c) {
      return {
        glyph: isGlyphKey(c.icon) ? c.icon! : "custom",
        color: loc.color || c.color || presetByKind("custom").color,
      };
    }
  }
  const p = presetByKind(loc.elementKind);
  const glyph =
    (isGlyphKey(loc.icon) && loc.icon) ||
    (loc.elementKind && loc.elementKind !== "custom" ? loc.elementKind : null) ||
    p.icon;
  return {
    glyph,
    color: loc.color || p.color,
  };
}

export function lineDash(style: MapLineStyle | undefined): string | undefined {
  switch (style ?? "solid") {
    case "dashed":
      return "18 14";
    case "dotted":
      return "3 10";
    case "rail":
      return "28 10 4 10";
    case "magic":
      return "6 8 2 8";
    default:
      return undefined;
  }
}

export function clampCamera(
  cam: { x: number; y: number; zoom: number },
  vw: number,
  vh: number
) {
  const zw = WORLD_W * cam.zoom;
  const zh = WORLD_H * cam.zoom;
  let x = cam.x;
  let y = cam.y;
  if (zw <= vw) x = (zw - vw) / 2;
  else x = clamp(x, 0, zw - vw);
  if (zh <= vh) y = (zh - vh) / 2;
  else y = clamp(y, 0, zh - vh);
  return { ...cam, x, y };
}

/** Push overlapping name labels apart in world space */
export function labelOffsets(
  nodes: { id: string; x: number; y: number; name: string }[]
): Map<string, number> {
  const sorted = [...nodes].sort((a, b) => a.y - b.y || a.x - b.x);
  const out = new Map<string, number>();
  const placed: { x: number; y: number; w: number }[] = [];
  for (const n of sorted) {
    const w = Math.min(120, 24 + n.name.length * 8);
    let dy = 0;
    let guard = 0;
    while (guard++ < 12) {
      const ly = n.y + 8 + dy;
      const hit = placed.some(
        (p) => Math.abs(p.x - n.x) < (p.w + w) / 2 && Math.abs(p.y - ly) < 22
      );
      if (!hit) {
        placed.push({ x: n.x, y: ly, w });
        out.set(n.id, dy);
        break;
      }
      dy += 20;
    }
    if (!out.has(n.id)) out.set(n.id, dy);
  }
  return out;
}
