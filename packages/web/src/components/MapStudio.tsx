"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LOCATION_RELATION_LABELS,
  MAP_ELEMENT_PRESETS,
  MAP_LINE_STYLE_LABELS,
  MAP_STYLES,
  normalizeMapStyle,
  presetByKind,
  uid,
  type CustomMapElementDef,
  type Location,
  type LocationLink,
  type LocationRelation,
  type MapElementKind,
  type MapLineStyle,
  type MapStroke,
  type MapStyleId,
} from "@vnss/core";
import styles from "./MapStudio.module.css";

/** Large playable world — camera clamps so you never see empty void */
const WORLD_W = 4800;
const WORLD_H = 3600;
/** Thematic stage (bulletin / letter / HUD…) sits in the center of the world */
const STAGE_W = 2200;
const STAGE_H = 1500;
const STAGE_X = (WORLD_W - STAGE_W) / 2;
const STAGE_Y = (WORLD_H - STAGE_H) / 2;

type Tool = "pan" | "place" | "link" | "select" | "draw";

type Props = {
  locations: Location[];
  links: LocationLink[];
  mapStyle: MapStyleId;
  customElements: CustomMapElementDef[];
  strokes: MapStroke[];
  onChangeLocations: (locations: Location[]) => void;
  onChangeLinks: (links: LocationLink[]) => void;
  onChangeStyle: (style: MapStyleId) => void;
  onChangeCustomElements: (defs: CustomMapElementDef[]) => void;
  onChangeStrokes: (strokes: MapStroke[]) => void;
  onExtractFromScript?: () => void;
};

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}

function distToSegment(
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

function strokeHitsPoint(
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
    if (
      distToSegment(x, y, pts[i - 1].x, pts[i - 1].y, pts[i].x, pts[i].y) <=
      thr
    ) {
      return true;
    }
  }
  return false;
}

function resolveIcon(
  loc: Location,
  customs: CustomMapElementDef[]
): { icon: string; color: string } {
  if (loc.icon && loc.color) return { icon: loc.icon, color: loc.color };
  if (loc.elementKind === "custom" && loc.tags?.[0]) {
    const c = customs.find((x) => x.id === loc.tags![0]);
    if (c) return { icon: c.icon, color: c.color };
  }
  const p = presetByKind(loc.elementKind);
  return {
    icon: loc.icon || p.icon,
    color: loc.color || p.color,
  };
}

function lineDash(style: MapLineStyle | undefined): string | undefined {
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

function clampCamera(
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
function labelOffsets(
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

export function MapStudio({
  locations,
  links,
  mapStyle,
  customElements,
  strokes,
  onChangeLocations,
  onChangeLinks,
  onChangeStyle,
  onChangeCustomElements,
  onChangeStrokes,
  onExtractFromScript,
}: Props) {
  const styleId = normalizeMapStyle(mapStyle);
  const studioRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState<Tool>("pan");
  const [placeKind, setPlaceKind] = useState<MapElementKind>("landmark");
  const [placeCustomId, setPlaceCustomId] = useState<string | null>(null);
  const [relation, setRelation] = useState<LocationRelation>("leads_to");
  const [lineStyle, setLineStyle] = useState<MapLineStyle>("solid");
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [cam, setCam] = useState({ x: 0, y: 0, zoom: 0.5 });
  const [didFit, setDidFit] = useState(false);
  const [panning, setPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, camX: 0, camY: 0 });
  const [dragIds, setDragIds] = useState<string[]>([]);
  const dragPointerStart = useRef({ x: 0, y: 0 });
  const dragPosStart = useRef<Map<string, { x: number; y: number }>>(new Map());
  const [drawing, setDrawing] = useState(false);
  const draftStroke = useRef<MapStroke | null>(null);
  const [draftPts, setDraftPts] = useState<{ x: number; y: number }[]>([]);
  const [brushColor, setBrushColor] = useState("#5b6b7a");
  const [brushWidth, setBrushWidth] = useState(6);
  const [brushMode, setBrushMode] = useState<"pen" | "eraser">("pen");
  const strokeHistory = useRef<MapStroke[][]>([]);
  const eraseSessionStarted = useRef(false);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const spaceHeldRef = useRef(false);
  const [marquee, setMarquee] = useState<{
    x0: number;
    y0: number;
    x1: number;
    y1: number;
  } | null>(null);
  const marqueeRef = useRef<{
    x0: number;
    y0: number;
    x1: number;
    y1: number;
  } | null>(null);
  /** place tool: empty-down may become pan if moved >8px */
  const placeGesture = useRef<{
    clientX: number;
    clientY: number;
    becamePan: boolean;
  } | null>(null);
  const selectGesture = useRef<{
    mode: "pending" | "marquee";
    x0: number;
    y0: number;
  } | null>(null);
  const sessionRef = useRef<
    null | "pan" | "draw" | "erase" | "drag" | "place" | "select"
  >(null);
  const liveRef = useRef<{
    cam: { x: number; y: number; zoom: number };
    locations: Location[];
    nodes: { id: string; x: number; y: number; name: string }[];
    strokes: MapStroke[];
    brushColor: string;
    brushWidth: number;
    brushMode: "pen" | "eraser";
    screenToWorld: (clientX: number, clientY: number) => { x: number; y: number };
    onChangeLocations: (locations: Location[]) => void;
    onChangeStrokes: (strokes: MapStroke[]) => void;
    placeAt: (x: number, y: number) => void;
  } | null>(null);

  const [customForm, setCustomForm] = useState({
    name: "秘密地点",
    icon: "✦",
    color: "#8b7bb8",
  });

  const nodes = useMemo(
    () =>
      locations.map((loc, i) => ({
        ...loc,
        x: loc.mapX ?? STAGE_X + 180 + (i % 6) * 300,
        y: loc.mapY ?? STAGE_Y + 220 + Math.floor(i / 6) * 240,
      })),
    [locations]
  );
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selected =
    selectedIds.length === 1
      ? (locations.find((l) => l.id === selectedIds[0]) ?? null)
      : null;
  const offsets = useMemo(() => labelOffsets(nodes), [nodes]);

  const applyCam = useCallback(
    (next: { x: number; y: number; zoom: number }) => {
      const el = viewportRef.current;
      if (!el) {
        setCam(next);
        return;
      }
      const { width, height } = el.getBoundingClientRect();
      setCam(clampCamera(next, width, height));
    },
    []
  );

  const screenToWorld = useCallback(
    (clientX: number, clientY: number) => {
      const el = viewportRef.current;
      if (!el) return { x: 0, y: 0 };
      const rect = el.getBoundingClientRect();
      return {
        x: (clientX - rect.left + cam.x) / cam.zoom,
        y: (clientY - rect.top + cam.y) / cam.zoom,
      };
    },
    [cam]
  );

  /** 初次进入：对准地点群，避免大世界 + 错误相机看起来像「一片黑」 */
  const fitToContent = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    if (width < 40 || height < 40) return;
    // 略缩小：露出公告板/信纸外框与背景一圈，不只贴满视口
    const minX = STAGE_X + 20;
    const minY = STAGE_Y + 20;
    const maxX = STAGE_X + STAGE_W - 20;
    const maxY = STAGE_Y + STAGE_H - 20;
    const pad = 120;
    const bw = Math.max(maxX - minX + pad * 2, 900);
    const bh = Math.max(maxY - minY + pad * 2, 700);
    const zoom = clamp(
      Math.min(width / bw, height / bh) * 0.78,
      0.32,
      1.1
    );
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    applyCam({
      zoom,
      x: cx * zoom - width / 2,
      y: cy * zoom - height / 2,
    });
    setDidFit(true);
  }, [nodes, applyCam]);

  useEffect(() => {
    setDidFit(false);
  }, [styleId]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onResize = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width < 40 || height < 40) return;
      if (!didFit) {
        fitToContent();
        return;
      }
      setCam((c) => clampCamera(c, width, height));
    };
    // 双 rAF：等 flex 高度算完再复位（系统浏览器布局时常比 Cursor 内嵌更快/更慢）
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        if (!didFit) fitToContent();
      });
    });
    const ro = new ResizeObserver(onResize);
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      ro.disconnect();
    };
  }, [didFit, fitToContent]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      setCam((c) => {
        const nextZoom = clamp(c.zoom * (e.deltaY > 0 ? 0.9 : 1.1), 0.22, 2.6);
        const worldX = (mx + c.x) / c.zoom;
        const worldY = (my + c.y) / c.zoom;
        return clampCamera(
          {
            zoom: nextZoom,
            x: worldX * nextZoom - mx,
            y: worldY * nextZoom - my,
          },
          rect.width,
          rect.height
        );
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const beginPan = useCallback(
    (clientX: number, clientY: number) => {
      sessionRef.current = "pan";
      setPanning(true);
      panStart.current = {
        x: clientX,
        y: clientY,
        camX: cam.x,
        camY: cam.y,
      };
    },
    [cam.x, cam.y]
  );

  const viewportLocal = useCallback((clientX: number, clientY: number) => {
    const el = viewportRef.current;
    if (!el) return { x: 0, y: 0 };
    const rect = el.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }, []);

  const placeAt = useCallback(
    (x: number, y: number) => {
      const preset = presetByKind(placeKind);
      let icon = preset.icon;
      let color = preset.color;
      let name = preset.name;
      let tags: string[] | undefined;
      if (placeKind === "custom" && placeCustomId) {
        const c = customElements.find((e) => e.id === placeCustomId);
        if (c) {
          icon = c.icon;
          color = c.color;
          name = c.name;
          tags = [c.id];
        }
      }
      const id = uid("loc");
      onChangeLocations([
        ...locations,
        {
          id,
          name: `${name}${locations.filter((l) => l.elementKind === placeKind).length + 1}`,
          mapX: x,
          mapY: y,
          elementKind: placeKind,
          icon,
          color,
          scale: 1,
          rotation: 0,
          imageTag: "",
          description: "",
          tags,
        },
      ]);
      setSelectedIds([id]);
      setTool("select");
    },
    [placeKind, placeCustomId, customElements, locations, onChangeLocations]
  );

  const deleteSelectedIds = useCallback(
    (ids: string[]) => {
      if (ids.length === 0) return;
      const idSet = new Set(ids);
      onChangeLocations(locations.filter((l) => !idSet.has(l.id)));
      onChangeLinks(
        links.filter((l) => !idSet.has(l.fromId) && !idSet.has(l.toId))
      );
      setSelectedIds([]);
      setLinkFrom((from) => (from && idSet.has(from) ? null : from));
    },
    [locations, links, onChangeLocations, onChangeLinks]
  );

  const pushStrokeHistory = useCallback((current: MapStroke[]) => {
    strokeHistory.current = [...strokeHistory.current.slice(-40), current];
  }, []);

  const undoStroke = useCallback(() => {
    const prev = strokeHistory.current.pop();
    if (prev) {
      onChangeStrokes(prev);
      return;
    }
    if (strokes.length > 0) {
      onChangeStrokes(strokes.slice(0, -1));
    }
  }, [strokes, onChangeStrokes]);

  liveRef.current = {
    cam,
    locations,
    nodes,
    strokes,
    brushColor,
    brushWidth,
    brushMode,
    screenToWorld,
    onChangeLocations,
    onChangeStrokes,
    placeAt,
  };

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const session = sessionRef.current;
      if (!session) return;
      const live = liveRef.current;
      if (!live) return;

      if (session === "place" && placeGesture.current) {
        if (!placeGesture.current.becamePan) {
          const dx = e.clientX - placeGesture.current.clientX;
          const dy = e.clientY - placeGesture.current.clientY;
          if (Math.hypot(dx, dy) > 8) {
            placeGesture.current.becamePan = true;
            sessionRef.current = "pan";
            setPanning(true);
            panStart.current = {
              x: placeGesture.current.clientX,
              y: placeGesture.current.clientY,
              camX: live.cam.x,
              camY: live.cam.y,
            };
          } else {
            return;
          }
        }
      }

      if (session === "select" && selectGesture.current) {
        const el = viewportRef.current;
        if (!el) return;
        const rect = el.getBoundingClientRect();
        const loc = { x: e.clientX - rect.left, y: e.clientY - rect.top };
        const g = selectGesture.current;
        if (g.mode === "pending") {
          const dx = loc.x - g.x0;
          const dy = loc.y - g.y0;
          if (Math.hypot(dx, dy) > 4) {
            g.mode = "marquee";
            const next = { x0: g.x0, y0: g.y0, x1: loc.x, y1: loc.y };
            marqueeRef.current = next;
            setMarquee(next);
          }
        } else {
          const next = { x0: g.x0, y0: g.y0, x1: loc.x, y1: loc.y };
          marqueeRef.current = next;
          setMarquee(next);
        }
        return;
      }

      if (sessionRef.current === "pan" || placeGesture.current?.becamePan) {
        const el = viewportRef.current;
        const rect = el?.getBoundingClientRect();
        const next = {
          zoom: live.cam.zoom,
          x: panStart.current.camX - (e.clientX - panStart.current.x),
          y: panStart.current.camY - (e.clientY - panStart.current.y),
        };
        if (rect) setCam(clampCamera(next, rect.width, rect.height));
        else setCam(next);
        return;
      }

      if (session === "draw" && draftStroke.current) {
        const w = live.screenToWorld(e.clientX, e.clientY);
        const pts = [
          ...draftStroke.current.points,
          {
            x: clamp(w.x, 0, WORLD_W),
            y: clamp(w.y, 0, WORLD_H),
          },
        ];
        draftStroke.current = { ...draftStroke.current, points: pts };
        setDraftPts(pts);
        return;
      }

      if (session === "erase") {
        const w = live.screenToWorld(e.clientX, e.clientY);
        const x = clamp(w.x, 0, WORLD_W);
        const y = clamp(w.y, 0, WORLD_H);
        const radius = Math.max(live.brushWidth * 1.2, 10);
        const next = live.strokes.filter(
          (s) => !strokeHitsPoint(s, x, y, radius)
        );
        if (next.length !== live.strokes.length) {
          if (!eraseSessionStarted.current) {
            strokeHistory.current = [
              ...strokeHistory.current.slice(-40),
              live.strokes,
            ];
            eraseSessionStarted.current = true;
          }
          live.onChangeStrokes(next);
        }
        return;
      }

      if (session === "drag") {
        const w = live.screenToWorld(e.clientX, e.clientY);
        const dx = w.x - dragPointerStart.current.x;
        const dy = w.y - dragPointerStart.current.y;
        const starts = dragPosStart.current;
        live.onChangeLocations(
          live.locations.map((l) => {
            const s = starts.get(l.id);
            if (!s) return l;
            return {
              ...l,
              mapX: clamp(s.x + dx, 48, WORLD_W - 48),
              mapY: clamp(s.y + dy, 48, WORLD_H - 48),
            };
          })
        );
      }
    };

    const onUp = (e: PointerEvent) => {
      const session = sessionRef.current;
      if (!session) return;
      const live = liveRef.current;
      if (!live) return;

      if (session === "draw" && draftStroke.current) {
        if (draftStroke.current.points.length > 1) {
          strokeHistory.current = [
            ...strokeHistory.current.slice(-40),
            live.strokes,
          ];
          live.onChangeStrokes([...live.strokes, draftStroke.current]);
        }
        draftStroke.current = null;
        setDraftPts([]);
        setDrawing(false);
      }

      if (session === "erase") {
        eraseSessionStarted.current = false;
      }

      if (session === "place" || placeGesture.current) {
        if (placeGesture.current && !placeGesture.current.becamePan) {
          const w = live.screenToWorld(e.clientX, e.clientY);
          live.placeAt(
            clamp(w.x, 48, WORLD_W - 48),
            clamp(w.y, 48, WORLD_H - 48)
          );
        }
        placeGesture.current = null;
      }

      if (session === "select" && selectGesture.current) {
        const g = selectGesture.current;
        if (g.mode === "marquee" && marqueeRef.current) {
          const r = marqueeRef.current;
          const left = Math.min(r.x0, r.x1);
          const right = Math.max(r.x0, r.x1);
          const top = Math.min(r.y0, r.y1);
          const bottom = Math.max(r.y0, r.y1);
          const { cam: c, nodes: ns } = live;
          const box = {
            minX: (left + c.x) / c.zoom,
            maxX: (right + c.x) / c.zoom,
            minY: (top + c.y) / c.zoom,
            maxY: (bottom + c.y) / c.zoom,
          };
          setSelectedIds(
            ns
              .filter(
                (n) =>
                  n.x >= box.minX &&
                  n.x <= box.maxX &&
                  n.y >= box.minY &&
                  n.y <= box.maxY
              )
              .map((n) => n.id)
          );
        } else {
          setSelectedIds([]);
        }
        selectGesture.current = null;
        marqueeRef.current = null;
        setMarquee(null);
      }

      sessionRef.current = null;
      setPanning(false);
      setDragIds([]);
      setDrawing(false);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  useEffect(() => {
    const isTypingTarget = (t: EventTarget | null) => {
      if (!(t instanceof HTMLElement)) return false;
      const tag = t.tagName;
      return (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        t.isContentEditable
      );
    };

    const studioFocused = () => {
      const root = studioRef.current;
      if (!root) return false;
      const ae = document.activeElement;
      return !!ae && root.contains(ae);
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      if (!studioFocused()) return;

      if (e.code === "Space") {
        if (!spaceHeldRef.current) {
          spaceHeldRef.current = true;
          setSpaceHeld(true);
        }
        e.preventDefault();
        return;
      }

      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setSelectedIds(nodes.map((n) => n.id));
        return;
      }
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        undoStroke();
        return;
      }
      if ((mod && e.key === "0") || e.key === "Home") {
        e.preventDefault();
        fitToContent();
        return;
      }

      if (e.key === "Escape") {
        setSelectedIds([]);
        setLinkFrom(null);
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        if (selectedIds.length === 0) return;
        e.preventDefault();
        deleteSelectedIds(selectedIds);
        return;
      }

      const k = e.key.toLowerCase();
      if (k === "v") setTool("select");
      else if (k === "h") setTool("pan");
      else if (k === "p") setTool("place");
      else if (k === "l") setTool("link");
      else if (k === "b") {
        setTool("draw");
        setBrushMode("pen");
      } else if (k === "e") {
        setTool("draw");
        setBrushMode("eraser");
      }
    };

    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        spaceHeldRef.current = false;
        setSpaceHeld(false);
      }
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", onKeyUp);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keyup", onKeyUp);
    };
  }, [nodes, selectedIds, fitToContent, deleteSelectedIds, undoStroke]);

  function onViewportPointerDown(e: React.PointerEvent) {
    if ((e.target as Element).closest("[data-pin]")) return;
    viewportRef.current?.focus();

    const forcePan =
      e.button === 1 || e.altKey || spaceHeldRef.current || spaceHeld;

    if (forcePan) {
      e.preventDefault();
      beginPan(e.clientX, e.clientY);
      return;
    }

    if (tool === "draw") {
      const w = screenToWorld(e.clientX, e.clientY);
      const x = clamp(w.x, 0, WORLD_W);
      const y = clamp(w.y, 0, WORLD_H);
      if (brushMode === "eraser") {
        eraseSessionStarted.current = false;
        sessionRef.current = "erase";
        setDrawing(true);
        // 立刻擦触碰点
        const radius = Math.max(brushWidth * 1.2, 10);
        const next = strokes.filter((s) => !strokeHitsPoint(s, x, y, radius));
        if (next.length !== strokes.length) {
          pushStrokeHistory(strokes);
          eraseSessionStarted.current = true;
          onChangeStrokes(next);
        }
        return;
      }
      const stroke: MapStroke = {
        id: uid("stroke"),
        points: [{ x, y }],
        color: brushColor,
        width: brushWidth,
        kind: "path",
      };
      draftStroke.current = stroke;
      setDraftPts(stroke.points);
      sessionRef.current = "draw";
      setDrawing(true);
      return;
    }

    if (tool === "select") {
      const loc = viewportLocal(e.clientX, e.clientY);
      selectGesture.current = { mode: "pending", x0: loc.x, y0: loc.y };
      marqueeRef.current = null;
      setMarquee(null);
      sessionRef.current = "select";
      return;
    }

    if (tool === "place") {
      placeGesture.current = {
        clientX: e.clientX,
        clientY: e.clientY,
        becamePan: false,
      };
      sessionRef.current = "place";
      return;
    }

    // pan / link: empty drag pans
    if (tool === "pan" || tool === "link") {
      beginPan(e.clientX, e.clientY);
    }
  }

  function onPinPointerDown(
    e: React.PointerEvent,
    id: string,
    nx: number,
    ny: number
  ) {
    e.stopPropagation();
    viewportRef.current?.focus();

    if (tool === "link") {
      setSelectedIds([id]);
      if (!linkFrom) setLinkFrom(id);
      else if (linkFrom === id) setLinkFrom(null);
      else {
        onChangeLinks([
          ...links,
          {
            id: uid("link"),
            fromId: linkFrom,
            toId: id,
            relation,
            lineStyle,
          },
        ]);
        setLinkFrom(null);
      }
      return;
    }
    if (tool === "draw") return;

    if (e.shiftKey) {
      setSelectedIds((prev) =>
        prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
      );
      return;
    }

    let nextSelection = selectedIds;
    if (!selectedIds.includes(id)) {
      nextSelection = [id];
      setSelectedIds([id]);
    }

    if (tool === "pan" || tool === "select" || tool === "place") {
      const w = screenToWorld(e.clientX, e.clientY);
      dragPointerStart.current = { x: w.x, y: w.y };
      const starts = new Map<string, { x: number; y: number }>();
      for (const sid of nextSelection) {
        const n = byId.get(sid);
        if (n) starts.set(sid, { x: n.x, y: n.y });
      }
      if (!starts.has(id)) starts.set(id, { x: nx, y: ny });
      dragPosStart.current = starts;
      sessionRef.current = "drag";
      setDragIds([...starts.keys()]);
      if (tool === "place") setTool("select");
    }
  }

  function updateSelected(patch: Partial<Location>) {
    if (selectedIds.length !== 1) return;
    const id = selectedIds[0];
    onChangeLocations(
      locations.map((l) => (l.id === id ? { ...l, ...patch } : l))
    );
  }

  function deleteSelected() {
    deleteSelectedIds(selectedIds);
  }

  function addCustomDef() {
    const id = uid("mel");
    onChangeCustomElements([
      ...customElements,
      {
        id,
        name: customForm.name.trim() || "自定义",
        icon: customForm.icon.trim() || "✦",
        color: customForm.color || "#8b7bb8",
      },
    ]);
    setPlaceKind("custom");
    setPlaceCustomId(id);
    setTool("place");
  }

  function renderPath(
    pts: { x: number; y: number }[],
    color: string,
    width: number,
    key: string
  ) {
    if (pts.length < 2) return null;
    const d = pts.map((p, i) => `${i ? "L" : "M"} ${p.x} ${p.y}`).join(" ");
    return (
      <path
        key={key}
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={width}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    );
  }

  return (
    <div className={styles.studio} data-style={styleId} ref={studioRef}>
      <aside className={styles.left}>
        <p className={styles.label}>题材风格</p>
        <div className={styles.styleGrid}>
          {MAP_STYLES.map((s) => (
            <button
              key={s.id}
              type="button"
              className={
                styleId === s.id ? styles.styleActive : styles.styleBtn
              }
              onClick={() => onChangeStyle(s.id)}
              title={`${s.genre} · ${s.desc}`}
            >
              <span data-swatch={s.id} />
              <strong>{s.name}</strong>
              <em>{s.genre}</em>
            </button>
          ))}
        </div>

        <p className={styles.label}>场景元素</p>
        <div className={styles.palette}>
          {MAP_ELEMENT_PRESETS.filter((p) => p.kind !== "custom").map((p) => (
            <button
              key={p.kind}
              type="button"
              className={
                tool === "place" && placeKind === p.kind && !placeCustomId
                  ? styles.palActive
                  : styles.palBtn
              }
              onClick={() => {
                setPlaceKind(p.kind);
                setPlaceCustomId(null);
                setTool("place");
              }}
              title={p.hint}
            >
              <span>{p.icon}</span>
              {p.name}
            </button>
          ))}
          {customElements.map((c) => (
            <div
              key={c.id}
              className={
                tool === "place" && placeCustomId === c.id
                  ? styles.palCustomActive
                  : styles.palCustom
              }
            >
              <button
                type="button"
                className={styles.palCustomMain}
                onClick={() => {
                  setPlaceKind("custom");
                  setPlaceCustomId(c.id);
                  setTool("place");
                }}
                title="选中以放置"
              >
                <span>{c.icon}</span>
                {c.name}
              </button>
              <button
                type="button"
                className={styles.palCustomDel}
                title="从图鉴删除（已放置的图钉仍保留）"
                onClick={(e) => {
                  e.stopPropagation();
                  if (placeCustomId === c.id) {
                    setPlaceCustomId(null);
                    setPlaceKind("landmark");
                  }
                  onChangeCustomElements(
                    customElements.filter((x) => x.id !== c.id)
                  );
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        {customElements.length > 0 && (
          <p className={styles.hintTiny}>
            内置元素不可删；自定义项点 × 可移除图鉴
          </p>
        )}

        <p className={styles.label}>自定义要素</p>
        <div className={styles.customForm}>
          <input
            value={customForm.name}
            onChange={(e) =>
              setCustomForm((f) => ({ ...f, name: e.target.value }))
            }
            placeholder="名称"
          />
          <div className={styles.customRow}>
            <input
              value={customForm.icon}
              onChange={(e) =>
                setCustomForm((f) => ({ ...f, icon: e.target.value }))
              }
              placeholder="图标"
              maxLength={4}
            />
            <input
              type="color"
              value={customForm.color}
              onChange={(e) =>
                setCustomForm((f) => ({ ...f, color: e.target.value }))
              }
            />
          </div>
          <button type="button" className={styles.primary} onClick={addCustomDef}>
            加入图鉴并放置
          </button>
        </div>
      </aside>

      <div className={styles.center}>
        <div className={styles.toolbar}>
          {(
            [
              ["pan", "漫游"],
              ["select", "选择"],
              ["place", "放置"],
              ["link", "通路"],
              ["draw", "画笔"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={tool === id ? styles.toolActive : styles.toolBtn}
              onClick={() => {
                setTool(id);
                setLinkFrom(null);
                if (id === "draw") setBrushMode("pen");
              }}
            >
              {label}
            </button>
          ))}
          {tool === "link" && (
            <>
              <select
                value={relation}
                onChange={(e) =>
                  setRelation(e.target.value as LocationRelation)
                }
              >
                {(
                  Object.keys(LOCATION_RELATION_LABELS) as LocationRelation[]
                ).map((r) => (
                  <option key={r} value={r}>
                    {LOCATION_RELATION_LABELS[r]}
                  </option>
                ))}
              </select>
              <select
                value={lineStyle}
                onChange={(e) =>
                  setLineStyle(e.target.value as MapLineStyle)
                }
                title="连线样式"
              >
                {(Object.keys(MAP_LINE_STYLE_LABELS) as MapLineStyle[]).map(
                  (ls) => (
                    <option key={ls} value={ls}>
                      {MAP_LINE_STYLE_LABELS[ls]}
                    </option>
                  )
                )}
              </select>
            </>
          )}
          {tool === "draw" && (
            <>
              <button
                type="button"
                className={
                  brushMode === "pen" ? styles.toolActive : styles.toolBtn
                }
                onClick={() => setBrushMode("pen")}
              >
                画笔
              </button>
              <button
                type="button"
                className={
                  brushMode === "eraser" ? styles.toolActive : styles.toolBtn
                }
                onClick={() => setBrushMode("eraser")}
              >
                橡皮
              </button>
              <input
                type="color"
                value={brushColor}
                onChange={(e) => setBrushColor(e.target.value)}
                title="笔色"
                disabled={brushMode === "eraser"}
              />
              <input
                type="range"
                min={2}
                max={24}
                value={brushWidth}
                onChange={(e) => setBrushWidth(Number(e.target.value))}
                title={brushMode === "eraser" ? "橡皮半径" : "笔粗"}
              />
              <button
                type="button"
                className={styles.toolBtn}
                onClick={undoStroke}
                title="Ctrl+Z"
              >
                撤回
              </button>
              <button
                type="button"
                className={styles.toolBtn}
                onClick={() => {
                  if (strokes.length === 0) return;
                  pushStrokeHistory(strokes);
                  onChangeStrokes([]);
                }}
              >
                清空笔迹
              </button>
            </>
          )}
          <span className={styles.hint}>
            {tool === "pan" && "拖空白平移 · 滚轮缩放"}
            {tool === "select" && "框选 / Shift+点切换 · 拖动可多移"}
            {tool === "place" && "单击放置 · 拖空白则平移"}
            {tool === "link" &&
              (linkFrom ? "再点终点" : "先点起点 · 空白拖动画布")}
            {tool === "draw" &&
              (brushMode === "eraser"
                ? "拖过笔迹擦除 · Ctrl+Z 撤回 · E 橡皮"
                : "拖动画线 · Ctrl+Z 撤回 · E 切橡皮")}
          </span>
          <button
            type="button"
            className={styles.toolBtn}
            onClick={() => fitToContent()}
          >
            复位
          </button>
          {onExtractFromScript && (
            <button
              type="button"
              className={styles.toolBtn}
              onClick={onExtractFromScript}
            >
              从剧本提取
            </button>
          )}
        </div>
        <p className={styles.shortcuts}>
          Del / Backspace 删除 · Ctrl+Z 撤回笔迹 · B画笔 E橡皮 · V选择 H漫游
        </p>

        <div
          ref={viewportRef}
          className={styles.viewport}
          data-style={styleId}
          tabIndex={0}
          onPointerDown={onViewportPointerDown}
          onContextMenu={(e) => e.preventDefault()}
        >
          <div
            className={styles.world}
            data-style={styleId}
            style={{
              width: WORLD_W,
              height: WORLD_H,
              transform: `translate(${-cam.x}px, ${-cam.y}px) scale(${cam.zoom})`,
              transformOrigin: "0 0",
            }}
          >
            <MapStage styleId={styleId} />
            <svg
              className={styles.roads}
              width={WORLD_W}
              height={WORLD_H}
              aria-hidden
            >
              {strokes.map((s) =>
                renderPath(s.points, s.color, s.width, s.id)
              )}
              {draftPts.length > 1 &&
                renderPath(draftPts, brushColor, brushWidth, "draft")}
              {links.map((link) => {
                const a = byId.get(link.fromId);
                const b = byId.get(link.toId);
                if (!a || !b) return null;
                const mx = (a.x + b.x) / 2;
                const my = (a.y + b.y) / 2 - 40;
                const ls = link.lineStyle ?? "solid";
                const label = LOCATION_RELATION_LABELS[link.relation];
                const dash = lineDash(ls);
                const strokeW = ls === "rail" ? 10 : ls === "double" ? 5 : 7;
                return (
                  <g key={link.id}>
                    {ls === "double" && (
                      <path
                        d={`M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`}
                        className={styles.road}
                        strokeWidth={12}
                        opacity={0.35}
                      />
                    )}
                    <path
                      d={`M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`}
                      className={`${styles.road} ${styles[`line_${ls}`] ?? ""}`}
                      strokeWidth={strokeW}
                      strokeDasharray={dash}
                    />
                    <rect
                      x={mx - label.length * 5.5}
                      y={my - 14}
                      width={label.length * 11}
                      height={18}
                      rx={4}
                      className={styles.roadLabelBg}
                    />
                    <text x={mx} y={my} className={styles.roadLabel}>
                      {label}
                    </text>
                  </g>
                );
              })}
            </svg>
            <div className={styles.pinLayer}>
              {nodes.map((n) => {
                const { icon, color } = resolveIcon(n, customElements);
                const active =
                  selectedIds.includes(n.id) ||
                  n.id === linkFrom ||
                  dragIds.includes(n.id);
                const sc = n.scale ?? 1;
                const labelDy = offsets.get(n.id) ?? 0;
                return (
                  <button
                    key={n.id}
                    type="button"
                    data-pin
                    className={active ? styles.pinActive : styles.pin}
                    style={{
                      left: n.x,
                      top: n.y,
                      transform: `translate(-50%, -100%) scale(${sc}) rotate(${n.rotation ?? 0}deg)`,
                      ["--pin-color" as string]: color,
                      ["--label-dy" as string]: `${labelDy}px`,
                    }}
                    onPointerDown={(e) => onPinPointerDown(e, n.id, n.x, n.y)}
                    title={n.description || n.name}
                  >
                    <span
                      className={styles.pinBadge}
                      style={{ borderColor: color }}
                    >
                      {icon}
                    </span>
                    <span className={styles.pinLabel}>{n.name}</span>
                  </button>
                );
              })}
            </div>
          </div>
          {marquee && (
            <div
              className={styles.marquee}
              style={{
                left: Math.min(marquee.x0, marquee.x1),
                top: Math.min(marquee.y0, marquee.y1),
                width: Math.abs(marquee.x1 - marquee.x0),
                height: Math.abs(marquee.y1 - marquee.y0),
              }}
            />
          )}
        </div>
      </div>

      <aside className={styles.right}>
        <p className={styles.label}>要素属性</p>
        {selectedIds.length > 1 ? (
          <div className={styles.inspector}>
            <p className={styles.empty}>已选 {selectedIds.length} 个要素</p>
            <button
              type="button"
              className={styles.danger}
              onClick={deleteSelected}
            >
              删除全部选中
            </button>
          </div>
        ) : !selected ? (
          <p className={styles.empty}>选中地图上的图钉以编辑</p>
        ) : (
          <div className={styles.inspector}>
            <label>
              名称
              <input
                value={selected.name}
                onChange={(e) => updateSelected({ name: e.target.value })}
              />
            </label>
            <label>
              图标
              <input
                value={selected.icon ?? ""}
                onChange={(e) => updateSelected({ icon: e.target.value })}
              />
            </label>
            <label>
              颜色
              <input
                type="color"
                value={selected.color ?? "#6b7280"}
                onChange={(e) => updateSelected({ color: e.target.value })}
              />
            </label>
            <label>
              scene 标签
              <input
                value={selected.imageTag ?? ""}
                onChange={(e) => updateSelected({ imageTag: e.target.value })}
                placeholder="bg station_night"
              />
            </label>
            <label>
              描述
              <textarea
                rows={3}
                value={selected.description ?? ""}
                onChange={(e) =>
                  updateSelected({ description: e.target.value })
                }
              />
            </label>
            <label>
              缩放 {Math.round((selected.scale ?? 1) * 100)}%
              <input
                type="range"
                min={0.6}
                max={1.8}
                step={0.05}
                value={selected.scale ?? 1}
                onChange={(e) =>
                  updateSelected({ scale: Number(e.target.value) })
                }
              />
            </label>
            <label>
              旋转 {Math.round(selected.rotation ?? 0)}°
              <input
                type="range"
                min={-45}
                max={45}
                step={1}
                value={selected.rotation ?? 0}
                onChange={(e) =>
                  updateSelected({ rotation: Number(e.target.value) })
                }
              />
            </label>
            <button
              type="button"
              className={styles.danger}
              onClick={deleteSelected}
            >
              删除此要素
            </button>
          </div>
        )}

        <p className={styles.label}>通路列表</p>
        <ul className={styles.linkList}>
          {links.map((l) => {
            const from = byId.get(l.fromId)?.name ?? "?";
            const to = byId.get(l.toId)?.name ?? "?";
            const ls = l.lineStyle ?? "solid";
            return (
              <li key={l.id}>
                <span>
                  {from} —{LOCATION_RELATION_LABELS[l.relation]}→ {to}
                  <small> · {MAP_LINE_STYLE_LABELS[ls]}</small>
                </span>
                <button
                  type="button"
                  onClick={() =>
                    onChangeLinks(links.filter((x) => x.id !== l.id))
                  }
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      </aside>
    </div>
  );
}

/** Thematic map body — bulletin board / letter / HUD dialog / etc. */
function MapStage({ styleId }: { styleId: MapStyleId }) {
  const box = {
    left: STAGE_X,
    top: STAGE_Y,
    width: STAGE_W,
    height: STAGE_H,
  };

  if (styleId === "campus") {
    return (
      <div className={styles.stage} style={box} data-style="campus" aria-hidden>
        <div className={styles.campusFrame}>
          <div className={styles.campusHeader}>学生会 · 校园导览公告板</div>
          <div className={styles.campusCork}>
            <span className={styles.scrap} style={{ left: "6%", top: "8%", transform: "rotate(-4deg)" }}>
              社团招募
            </span>
            <span className={styles.scrap} style={{ right: "8%", top: "12%", transform: "rotate(3deg)" }}>
              天台开放日
            </span>
            <span className={styles.scrap} style={{ left: "12%", bottom: "10%", transform: "rotate(2deg)" }}>
              失物招领
            </span>
            <span className={styles.scrap} style={{ right: "14%", bottom: "14%", transform: "rotate(-2deg)" }}>
              文化祭地图
            </span>
            <div className={styles.campusGrid} />
          </div>
        </div>
      </div>
    );
  }

  if (styleId === "romance") {
    return (
      <div className={styles.stage} style={box} data-style="romance" aria-hidden>
        <div className={styles.letterSheet}>
          <div className={styles.letterLines} />
          <div className={styles.letterStamp}>♡</div>
          <div className={styles.letterSeal} />
          <p className={styles.letterTitle}>致你的场景手记</p>
          <p className={styles.letterHint}>把约会地点钉在信纸上…</p>
        </div>
      </div>
    );
  }

  if (styleId === "cyber") {
    return (
      <div className={styles.stage} style={box} data-style="cyber" aria-hidden>
        <div className={styles.cyberDialog}>
          <div className={styles.cyberChrome}>
            <span>LOC_MAP.exe</span>
            <span className={styles.cyberDots}>● ● ●</span>
          </div>
          <div className={styles.cyberBody}>
            <div className={styles.cyberBracket} data-corner="tl" />
            <div className={styles.cyberBracket} data-corner="tr" />
            <div className={styles.cyberBracket} data-corner="bl" />
            <div className={styles.cyberBracket} data-corner="br" />
            <p className={styles.cyberPrompt}>{">"} sync_scene_graph — waiting input_</p>
            <div className={styles.cyberScan} />
          </div>
        </div>
      </div>
    );
  }

  if (styleId === "isekai") {
    return (
      <div className={styles.stage} style={box} data-style="isekai" aria-hidden>
        <div className={styles.scrollSheet}>
          <div className={styles.scrollRoll} data-side="top" />
          <div className={styles.scrollBody}>
            <p className={styles.scrollTitle}>✦ 大陆旅图 ✦</p>
            <div className={styles.scrollOrnament} />
          </div>
          <div className={styles.scrollRoll} data-side="bottom" />
        </div>
      </div>
    );
  }

  if (styleId === "urban") {
    return (
      <div className={styles.stage} style={box} data-style="urban" aria-hidden>
        <div className={styles.blueprint}>
          <p className={styles.blueTitle}>CITY ROUTE DRAFT</p>
          <div className={styles.blueGrid} />
          <div className={styles.blueCompass}>N</div>
        </div>
      </div>
    );
  }

  if (styleId === "mystery") {
    return (
      <div className={styles.stage} style={box} data-style="mystery" aria-hidden>
        <div className={styles.caseBoard}>
          <div className={styles.caseTab}>CASE FILE</div>
          <div className={styles.caseCork}>
            <span className={styles.polaroid} style={{ left: "8%", top: "10%", transform: "rotate(-6deg)" }}>
              证人
            </span>
            <span className={styles.polaroid} style={{ right: "10%", top: "16%", transform: "rotate(5deg)" }}>
              物证
            </span>
            <span className={styles.polaroid} style={{ left: "18%", bottom: "12%", transform: "rotate(3deg)" }}>
              时间线
            </span>
            <svg className={styles.caseStrings} viewBox="0 0 100 100" preserveAspectRatio="none">
              <line x1="20" y1="25" x2="75" y2="30" />
              <line x1="75" y1="30" x2="30" y2="75" />
              <line x1="20" y1="25" x2="30" y2="75" />
            </svg>
          </div>
        </div>
      </div>
    );
  }

  // horror
  return (
    <div className={styles.stage} style={box} data-style="horror" aria-hidden>
      <div className={styles.horrorWall}>
        <div className={styles.horrorCrack} />
        <span className={styles.horrorPhoto} style={{ left: "10%", top: "14%", transform: "rotate(-8deg)" }}>
          ?
        </span>
        <span className={styles.horrorPhoto} style={{ right: "12%", top: "22%", transform: "rotate(6deg)" }}>
          …
        </span>
        <span className={styles.horrorPhoto} style={{ left: "40%", bottom: "16%", transform: "rotate(-3deg)" }}>
          勿入
        </span>
        <p className={styles.horrorTitle}>此处无路标</p>
      </div>
    </div>
  );
}
