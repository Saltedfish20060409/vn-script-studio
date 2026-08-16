import type { LocationLink } from "../types/vn";

export type RoadPoint = { x: number; y: number };

export type RoadCurve = {
  linkId: string;
  mx: number;
  my: number;
};

/**
 * Assign quadratic control points so parallel / hub edges fan apart
 * instead of stacking on the same arc.
 */
export function planRoadCurves(
  links: LocationLink[],
  nodes: Map<string, RoadPoint>
): Map<string, RoadCurve> {
  const out = new Map<string, RoadCurve>();
  const usable = links.filter((l) => nodes.has(l.fromId) && nodes.has(l.toId));

  // Lane index among edges sharing the same undirected pair
  const pairBuckets = new Map<string, LocationLink[]>();
  for (const l of usable) {
    const key = pairKey(l.fromId, l.toId);
    const bucket = pairBuckets.get(key) ?? [];
    bucket.push(l);
    pairBuckets.set(key, bucket);
  }
  const pairLane = new Map<string, number>();
  for (const bucket of pairBuckets.values()) {
    bucket
      .slice()
      .sort((a, b) => a.id.localeCompare(b.id))
      .forEach((l, i) => pairLane.set(l.id, i));
  }

  // At each hub, order incident edges by angle and give them staggered bends
  const hubRank = new Map<string, number>();
  const byNode = new Map<string, LocationLink[]>();
  for (const l of usable) {
    for (const nid of [l.fromId, l.toId]) {
      const arr = byNode.get(nid) ?? [];
      arr.push(l);
      byNode.set(nid, arr);
    }
  }
  for (const [hub, incident] of byNode) {
    const hubPt = nodes.get(hub);
    if (!hubPt || incident.length < 2) continue;
    const ranked = incident
      .map((l) => {
        const other = l.fromId === hub ? l.toId : l.fromId;
        const o = nodes.get(other)!;
        return { l, ang: Math.atan2(o.y - hubPt.y, o.x - hubPt.x) };
      })
      .sort((a, b) => a.ang - b.ang);
    ranked.forEach((item, i) => {
      const prev = hubRank.get(item.l.id);
      // Keep the stronger (more central) rank when edge appears in two hubs
      const rank = i - (ranked.length - 1) / 2;
      if (prev === undefined || Math.abs(rank) > Math.abs(prev)) {
        hubRank.set(item.l.id, rank);
      }
    });
  }

  for (const link of usable) {
    const a = nodes.get(link.fromId)!;
    const b = nodes.get(link.toId)!;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const px = -dy / len;
    const py = dx / len;

    const lane = pairLane.get(link.id) ?? 0;
    const hub = hubRank.get(link.id) ?? 0;
    const sideFromHash = hashSide(link.id);

    // Base bend grows with length; lanes / hub rank fan further out
    const base = Math.min(140, Math.max(56, len * 0.14));
    const laneSpread = lane * 28;
    const hubSpread = Math.abs(hub) * 22;
    const bend = base + laneSpread + hubSpread;

    let side = hub !== 0 ? Math.sign(hub) || sideFromHash : sideFromHash;
    if (lane > 0) {
      side = lane % 2 === 0 ? side : -side;
    }

    // Nudge side if the straight chord already crosses many others
    const crossBias = crossingBias(link, usable, nodes);
    if (crossBias !== 0) side = crossBias;

    out.set(link.id, {
      linkId: link.id,
      mx: (a.x + b.x) / 2 + px * bend * side,
      my: (a.y + b.y) / 2 + py * bend * side,
    });
  }

  return out;
}

function pairKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

function hashSide(id: string): 1 | -1 {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return h & 1 ? 1 : -1;
}

function orient(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  cx: number,
  cy: number
): number {
  return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
}

function crosses(a1: RoadPoint, a2: RoadPoint, b1: RoadPoint, b2: RoadPoint): boolean {
  const o1 = orient(a1.x, a1.y, a2.x, a2.y, b1.x, b1.y);
  const o2 = orient(a1.x, a1.y, a2.x, a2.y, b2.x, b2.y);
  const o3 = orient(b1.x, b1.y, b2.x, b2.y, a1.x, a1.y);
  const o4 = orient(b1.x, b1.y, b2.x, b2.y, a2.x, a2.y);
  if (o1 === 0 || o2 === 0 || o3 === 0 || o4 === 0) return false;
  return o1 > 0 !== o2 > 0 && o3 > 0 !== o4 > 0;
}

/** Prefer the bend side that reduces straight-chord crossings. */
function crossingBias(
  link: LocationLink,
  all: LocationLink[],
  nodes: Map<string, RoadPoint>
): 0 | 1 | -1 {
  const a = nodes.get(link.fromId)!;
  const b = nodes.get(link.toId)!;
  let leftHits = 0;
  let rightHits = 0;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const px = -dy / len;
  const py = dx / len;
  const probe = 72;

  for (const side of [1, -1] as const) {
    const ctrl = {
      x: (a.x + b.x) / 2 + px * probe * side,
      y: (a.y + b.y) / 2 + py * probe * side,
    };
    // Approximate curve by two segments A-ctrl, ctrl-B vs other chords
    let hits = 0;
    for (const other of all) {
      if (other.id === link.id) continue;
      const c = nodes.get(other.fromId);
      const d = nodes.get(other.toId);
      if (!c || !d) continue;
      const ends = new Set([link.fromId, link.toId, other.fromId, other.toId]);
      if (ends.size < 4) continue;
      if (crosses(a, ctrl, c, d) || crosses(ctrl, b, c, d)) hits += 1;
    }
    if (side === 1) rightHits = hits;
    else leftHits = hits;
  }
  if (leftHits === rightHits) return 0;
  return leftHits < rightHits ? -1 : 1;
}
