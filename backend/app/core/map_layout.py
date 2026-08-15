"""Readable auto-layout for story map nodes after extract."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.domain.types import Location, LocationLink, ScriptBlock, VnProject

# Keep in sync with frontend MapStudio stage (world 4800x3600, stage 2200x1500 centered)
STAGE_X = 1300.0
STAGE_Y = 1050.0
STAGE_W = 2200.0
STAGE_H = 1500.0
PAD = 140.0


def _walk_blocks(blocks: Sequence[ScriptBlock], visit) -> None:
    for b in blocks:
        visit(b)
        if b.get("type") == "menu":
            for c in b.get("choices", []) or []:
                child = c.get("blocks") if isinstance(c, dict) else None
                if child:
                    _walk_blocks(child, visit)


def appearance_order(project: VnProject, locations: List[Location]) -> List[str]:
    """Scene / first-mention order across chapters (stable unique ids)."""
    by_tag: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for loc in locations:
        if loc.imageTag:
            by_tag[re_norm(loc.imageTag)] = loc.id
        by_name[re_norm(loc.name)] = loc.id

    ordered: List[str] = []
    seen: Set[str] = set()

    def add(lid: Optional[str]) -> None:
        if lid and lid not in seen:
            seen.add(lid)
            ordered.append(lid)

    for ch in project.chapters:
        scenes: List[str] = []

        def collect(b: ScriptBlock) -> None:
            if b.get("type") == "scene" and str(b.get("image", "")).strip():
                scenes.append(str(b["image"]).strip())

        _walk_blocks(ch.blocks, collect)
        for image in scenes:
            add(by_tag.get(re_norm(image)))

    for loc in locations:
        add(loc.id)
    return ordered


def re_norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _seed_arc(order: List[str], n: int) -> Dict[str, Tuple[float, float]]:
    """Chapter-flow ribbon across the stage (readable left→right story sweep)."""
    left = STAGE_X + PAD + 80
    right = STAGE_X + STAGE_W - PAD - 80
    mid_y = STAGE_Y + STAGE_H / 2
    amp = min(220.0, STAGE_H / 2 - PAD - 40)
    pos: Dict[str, Tuple[float, float]] = {}
    if n == 1:
        pos[order[0]] = ((left + right) / 2, mid_y)
        return pos
    for i, lid in enumerate(order):
        t = i / (n - 1)
        x = left + (right - left) * t
        # Soft wave + alternate bias so sequential edges don't stack
        y = mid_y + math.sin(t * math.pi * 1.15) * amp
        y += (70 if i % 2 else -70) * (0.35 + 0.65 * math.sin(t * math.pi))
        pos[lid] = (x, y)
    return pos


def _clamp(x: float, y: float) -> Tuple[float, float]:
    return (
        min(max(x, STAGE_X + PAD), STAGE_X + STAGE_W - PAD),
        min(max(y, STAGE_Y + PAD), STAGE_Y + STAGE_H - PAD),
    )


def _orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_properly_cross(
    a1: Tuple[float, float],
    a2: Tuple[float, float],
    b1: Tuple[float, float],
    b2: Tuple[float, float],
) -> bool:
    """True when open segments intersect (shared endpoints do not count)."""
    o1 = _orient(a1[0], a1[1], a2[0], a2[1], b1[0], b1[1])
    o2 = _orient(a1[0], a1[1], a2[0], a2[1], b2[0], b2[1])
    o3 = _orient(b1[0], b1[1], b2[0], b2[1], a1[0], a1[1])
    o4 = _orient(b1[0], b1[1], b2[0], b2[1], a2[0], a2[1])
    if o1 == 0 or o2 == 0 or o3 == 0 or o4 == 0:
        return False
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def count_edge_crossings(
    pos: Dict[str, Tuple[float, float]],
    edges: Sequence[Tuple[str, str]],
) -> int:
    n = 0
    for i in range(len(edges)):
        a, b = edges[i]
        if a not in pos or b not in pos:
            continue
        for j in range(i + 1, len(edges)):
            c, d = edges[j]
            if c not in pos or d not in pos:
                continue
            ends = {a, b, c, d}
            if len(ends) < 4:
                continue
            if segments_properly_cross(pos[a], pos[b], pos[c], pos[d]):
                n += 1
    return n


def layout_story_map(
    locations: List[Location],
    links: List[LocationLink],
    *,
    order_ids: Optional[List[str]] = None,
    iterations: int = 90,
    preserve_ids: Optional[Set[str]] = None,
) -> List[Location]:
    """
    Seed along a story ribbon, then gentle force layout so edges spread.
    Soft goals: node separation, hub angle resolution, fewer edge crossings.
    Only rewrites mapX/mapY (keeps ids / metadata).

    Ids in ``preserve_ids`` that already have coordinates stay pinned
    (anchors for new pins) and are never rewritten.
    """
    if not locations:
        return locations

    ids = [l.id for l in locations]
    order = [i for i in (order_ids or ids) if i in set(ids)]
    for i in ids:
        if i not in order:
            order.append(i)

    by_id = {l.id: l for l in locations}
    pinned: Set[str] = set()
    for pid in preserve_ids or set():
        loc = by_id.get(pid)
        if loc is not None and loc.mapX is not None and loc.mapY is not None:
            pinned.add(pid)

    pos: Dict[str, Tuple[float, float]] = {}
    for pid in pinned:
        loc = by_id[pid]
        pos[pid] = (float(loc.mapX), float(loc.mapY))  # type: ignore[arg-type]

    movable = [i for i in order if i not in pinned]
    need_arc: List[str] = []
    for i in movable:
        loc = by_id[i]
        # Warm-start from existing coords so soft untangle can fix bad overlaps
        if loc.mapX is not None and loc.mapY is not None:
            pos[i] = (float(loc.mapX), float(loc.mapY))
        else:
            need_arc.append(i)
    if need_arc:
        pos.update(_seed_arc(need_arc, len(need_arc)))
    for i in ids:
        if i not in pos:
            loc = by_id[i]
            if loc.mapX is not None and loc.mapY is not None:
                pos[i] = (float(loc.mapX), float(loc.mapY))
            else:
                pos[i] = (STAGE_X + STAGE_W / 2, STAGE_Y + STAGE_H / 2)

    undirected: Set[Tuple[str, str]] = set()
    for link in links:
        a, b = link.fromId, link.toId
        if a in pos and b in pos and a != b:
            undirected.add((a, b) if a < b else (b, a))
    edge_list = list(undirected)

    neighbors: Dict[str, List[str]] = {i: [] for i in pos}
    for a, b in undirected:
        neighbors[a].append(b)
        neighbors[b].append(a)

    for step in range(iterations):
        cool = 1.0 - step / max(1, iterations - 1)
        disp = {i: [0.0, 0.0] for i in pos}

        loc_ids = list(pos.keys())
        for i in range(len(loc_ids)):
            for j in range(i + 1, len(loc_ids)):
                a, b = loc_ids[i], loc_ids[j]
                ax, ay = pos[a]
                bx, by = pos[b]
                dx, dy = ax - bx, ay - by
                dist2 = dx * dx + dy * dy
                dist = math.sqrt(dist2) if dist2 > 1e-6 else 1.0
                # Soft separation (~260px preferred)
                force = min((260.0 ** 2) / dist, 520.0)
                fx, fy = (dx / dist) * force, (dy / dist) * force
                disp[a][0] += fx
                disp[a][1] += fy
                disp[b][0] -= fx
                disp[b][1] -= fy

        for a, b in undirected:
            ax, ay = pos[a]
            bx, by = pos[b]
            dx, dy = bx - ax, by - ay
            dist = math.sqrt(dx * dx + dy * dy) or 1.0
            ideal = 480.0
            force = (dist - ideal) * 0.12
            fx, fy = (dx / dist) * force, (dy / dist) * force
            disp[a][0] += fx
            disp[a][1] += fy
            disp[b][0] -= fx
            disp[b][1] -= fy

        # Soft crossing penalty: push endpoints of crossing chords apart
        for i in range(len(edge_list)):
            a, b = edge_list[i]
            for j in range(i + 1, len(edge_list)):
                c, d = edge_list[j]
                if len({a, b, c, d}) < 4:
                    continue
                if not segments_properly_cross(pos[a], pos[b], pos[c], pos[d]):
                    continue
                # Midpoints of the two chords
                mx1 = (pos[a][0] + pos[b][0]) / 2
                my1 = (pos[a][1] + pos[b][1]) / 2
                mx2 = (pos[c][0] + pos[d][0]) / 2
                my2 = (pos[c][1] + pos[d][1]) / 2
                dx, dy = mx1 - mx2, my1 - my2
                dist = math.sqrt(dx * dx + dy * dy) or 1.0
                # Prefer perpendicular separation of the two midlines
                force = 55.0 * cool + 18.0
                fx, fy = (dx / dist) * force, (dy / dist) * force
                for nid, sx, sy in (
                    (a, fx, fy),
                    (b, fx, fy),
                    (c, -fx, -fy),
                    (d, -fx, -fy),
                ):
                    if nid in pinned:
                        continue
                    disp[nid][0] += sx * 0.45
                    disp[nid][1] += sy * 0.45

        # Hub angular resolution: spread neighbors that sit in a tight wedge
        for hub, nbrs in neighbors.items():
            if len(nbrs) < 2:
                continue
            hx, hy = pos[hub]
            angles: List[Tuple[float, str]] = []
            for n in nbrs:
                nx, ny = pos[n]
                angles.append((math.atan2(ny - hy, nx - hx), n))
            angles.sort(key=lambda t: t[0])
            m = len(angles)
            for k in range(m):
                ang0, n0 = angles[k]
                ang1, n1 = angles[(k + 1) % m]
                delta = ang1 - ang0
                if delta <= 0:
                    delta += math.pi * 2
                # Want at least ~40° between spokes when degree is high
                min_gap = max(0.45, (math.pi * 2) / max(m, 3) * 0.55)
                if delta >= min_gap:
                    continue
                push = (min_gap - delta) * 90.0 * cool
                # Push neighbors along tangential directions
                for nid, sign in ((n0, -1.0), (n1, 1.0)):
                    if nid in pinned:
                        continue
                    nx, ny = pos[nid]
                    vx, vy = nx - hx, ny - hy
                    vlen = math.sqrt(vx * vx + vy * vy) or 1.0
                    tx, ty = -vy / vlen, vx / vlen
                    disp[nid][0] += tx * push * sign
                    disp[nid][1] += ty * push * sign

        # Keep the ribbon near stage center / story axis
        cx = STAGE_X + STAGE_W / 2
        cy = STAGE_Y + STAGE_H / 2
        for i, (x, y) in pos.items():
            if i in pinned:
                continue
            disp[i][0] += (cx - x) * 0.012
            disp[i][1] += (cy - y) * 0.04

        max_move = 20.0 * cool + 3.5
        for i in pos:
            if i in pinned:
                continue
            dx, dy = disp[i]
            mag = math.sqrt(dx * dx + dy * dy) or 1.0
            scale = min(max_move, mag) / mag * 0.55
            nx, ny = _clamp(pos[i][0] + dx * scale, pos[i][1] + dy * scale)
            pos[i] = (nx, ny)

    if not pinned:
        # Fit final cloud into the inner stage so nodes don't hug the walls
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        inner_l = STAGE_X + PAD + 60
        inner_r = STAGE_X + STAGE_W - PAD - 60
        inner_t = STAGE_Y + PAD + 60
        inner_b = STAGE_Y + STAGE_H - PAD - 60
        target_w = inner_r - inner_l
        target_h = inner_b - inner_t
        scale = min(target_w / span_x, target_h / span_y, 1.15)
        scale = max(scale, 0.55)
        cx0 = (min_x + max_x) / 2
        cy0 = (min_y + max_y) / 2
        tcx = (inner_l + inner_r) / 2
        tcy = (inner_t + inner_b) / 2
        for i, (x, y) in list(pos.items()):
            nx = tcx + (x - cx0) * scale
            ny = tcy + (y - cy0) * scale
            pos[i] = _clamp(nx, ny)
    else:
        for i in list(pos.keys()):
            if i not in pinned:
                pos[i] = _clamp(pos[i][0], pos[i][1])

    out: List[Location] = []
    for loc in locations:
        if loc.id in pinned:
            out.append(loc)
            continue
        x, y = pos.get(loc.id, (loc.mapX or STAGE_X + 400, loc.mapY or STAGE_Y + 400))
        out.append(loc.model_copy(update={"mapX": round(x, 1), "mapY": round(y, 1)}))
    return out


def layout_project_map(
    project: VnProject,
    locations: List[Location],
    links: List[LocationLink],
    *,
    preserve_ids: Optional[Set[str]] = None,
) -> List[Location]:
    return layout_story_map(
        locations,
        links,
        order_ids=appearance_order(project, locations),
        preserve_ids=preserve_ids,
    )


def pinned_location_ids(locations: Optional[Sequence[Location]]) -> Set[str]:
    """Ids that already have map coordinates and must not be auto-moved."""
    out: Set[str] = set()
    for loc in locations or []:
        if loc.mapX is not None and loc.mapY is not None:
            out.add(loc.id)
    return out
