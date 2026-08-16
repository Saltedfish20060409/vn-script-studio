import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  Location,
  MapElementKind,
  MapLineStyle,
  MapStroke,
} from "../types/vn";
import { presetByKind } from "../lib/mapCatalog";
import { findLocationOccurrences } from "../lib/mapOccurrences";
import { planRoadCurves } from "../lib/mapRoads";
import { uid } from "../lib/vnLocal";
import {
  WORLD_W,
  WORLD_H,
  STAGE_W,
  STAGE_H,
  STAGE_X,
  STAGE_Y,
  clamp,
  clampCamera,
  labelOffsets,
  lineDash,
  resolvePin,
  strokeHitsPoint,
} from "../lib/mapWorld";
import { MapPinGlyph, isGlyphKey } from "./MapPinGlyph";
import type { MapStudioProps, Tool } from "./mapStudioTypes";
import { MapStage } from "./MapStage";
import { MapPalette } from "./MapPalette";
import { MapToolbar } from "./MapToolbar";
import { MapInspector } from "./MapInspector";
import { MapEmptyOverlay } from "./MapEmptyOverlay";
import styles from "./MapStudio.module.css";

export function MapStudio({
  locations,
  links,
  chapters,
  customElements,
  strokes,
  onChangeLocations,
  onChangeLinks,
  onChangeCustomElements,
  onChangeStrokes,
  onJumpToChapter,
  focusLocationId = null,
  focusTick = 0,
  onExtractFromScript,
  onExtractRulesOnly,
}: MapStudioProps) {
  const studioRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState<Tool>("pan");
  const [placeKind, setPlaceKind] = useState<MapElementKind>("landmark");
  const [placeCustomId, setPlaceCustomId] = useState<string | null>(null);
  const [lineStyle, setLineStyle] = useState<MapLineStyle>("solid");
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [cam, setCam] = useState({ x: 0, y: 0, zoom: 0.5 });
  const [didFit, setDidFit] = useState(false);
  const [, setPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, camX: 0, camY: 0 });
  const [dragIds, setDragIds] = useState<string[]>([]);
  const dragPointerStart = useRef({ x: 0, y: 0 });
  const dragPosStart = useRef<Map<string, { x: number; y: number }>>(new Map());
  const [drawing, setDrawing] = useState(false);
  const draftStroke = useRef<MapStroke | null>(null);
  const [draftPts, setDraftPts] = useState<{ x: number; y: number }[]>([]);
  const [brushColor, setBrushColor] = useState("#002fa7");
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
    icon: "custom",
    color: "#002fa7",
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
  const occurrences = useMemo(
    () => (selected ? findLocationOccurrences(selected, chapters) : []),
    [selected, chapters]
  );
  const offsets = useMemo(() => labelOffsets(nodes), [nodes]);
  const roadCurves = useMemo(() => {
    const pts = new Map(nodes.map((n) => [n.id, { x: n.x, y: n.y }] as const));
    return planRoadCurves(links, pts);
  }, [nodes, links]);

  const applyCam = useCallback((next: { x: number; y: number; zoom: number }) => {
    const el = viewportRef.current;
    if (!el) {
      setCam(next);
      return;
    }
    const { width, height } = el.getBoundingClientRect();
    setCam(clampCamera(next, width, height));
  }, []);

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
    const zoom = clamp(Math.min(width / bw, height / bh) * 0.78, 0.32, 1.1);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    applyCam({
      zoom,
      x: cx * zoom - width / 2,
      y: cy * zoom - height / 2,
    });
    setDidFit(true);
  }, [nodes, applyCam]);

  const focusPin = useCallback(
    (id: string) => {
      const n = nodes.find((x) => x.id === id);
      if (!n) return;
      const el = viewportRef.current;
      if (!el) return;
      const { width, height } = el.getBoundingClientRect();
      if (width < 40 || height < 40) return;
      const zoom = clamp(0.85, 0.4, 1.2);
      applyCam({
        zoom,
        x: n.x * zoom - width / 2,
        y: n.y * zoom - height / 2,
      });
      setSelectedIds([id]);
      setTool("select");
      setDidFit(true);
    },
    [nodes, applyCam]
  );

  useEffect(() => {
    if (!focusLocationId || !focusTick) return;
    const id = window.requestAnimationFrame(() => {
      focusPin(focusLocationId);
    });
    return () => window.cancelAnimationFrame(id);
  }, [focusLocationId, focusTick, focusPin]);

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
          icon = isGlyphKey(c.icon) ? c.icon : "custom";
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
      onChangeLinks(links.filter((l) => !idSet.has(l.fromId) && !idSet.has(l.toId)));
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
        const next = live.strokes.filter((s) => !strokeHitsPoint(s, x, y, radius));
        if (next.length !== live.strokes.length) {
          if (!eraseSessionStarted.current) {
            strokeHistory.current = [...strokeHistory.current.slice(-40), live.strokes];
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
          strokeHistory.current = [...strokeHistory.current.slice(-40), live.strokes];
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
          live.placeAt(clamp(w.x, 48, WORLD_W - 48), clamp(w.y, 48, WORLD_H - 48));
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
        tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable
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

    const forcePan = e.button === 1 || e.altKey || spaceHeldRef.current || spaceHeld;

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

  function onPinPointerDown(e: React.PointerEvent, id: string, nx: number, ny: number) {
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
            relation: "adjacent",
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
    onChangeLocations(locations.map((l) => (l.id === id ? { ...l, ...patch } : l)));
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
        icon: "custom",
        color: customForm.color || "#002fa7",
      },
    ]);
    setPlaceKind("custom");
    setPlaceCustomId(id);
    setTool("place");
  }

  function handleSelectTool(next: Tool) {
    setTool(next);
    setLinkFrom(null);
    if (next === "draw") setBrushMode("pen");
  }

  function handleClearStrokes() {
    if (strokes.length === 0) return;
    pushStrokeHistory(strokes);
    onChangeStrokes([]);
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
    <div className={styles.studio} ref={studioRef}>
      <MapPalette
        tool={tool}
        placeKind={placeKind}
        placeCustomId={placeCustomId}
        customElements={customElements}
        customForm={customForm}
        onSetTool={setTool}
        onSetPlaceKind={setPlaceKind}
        onSetPlaceCustomId={setPlaceCustomId}
        onSetCustomForm={setCustomForm}
        onChangeCustomElements={onChangeCustomElements}
        onAddCustom={addCustomDef}
      />
      <div className={styles.center}>
        <MapToolbar
          tool={tool}
          linkFrom={linkFrom}
          lineStyle={lineStyle}
          brushMode={brushMode}
          brushColor={brushColor}
          brushWidth={brushWidth}
          strokes={strokes}
          onSelectTool={handleSelectTool}
          onSetLineStyle={setLineStyle}
          onSetBrushMode={setBrushMode}
          onSetBrushColor={setBrushColor}
          onSetBrushWidth={setBrushWidth}
          onUndoStroke={undoStroke}
          onClearStrokes={handleClearStrokes}
          onFit={fitToContent}
          onExtractFromScript={onExtractFromScript}
          onExtractRulesOnly={onExtractRulesOnly}
        />
        <div
          ref={viewportRef}
          className={styles.viewport}
          tabIndex={0}
          onPointerDown={onViewportPointerDown}
          onContextMenu={(e) => e.preventDefault()}
        >
          {locations.length === 0 && strokes.length === 0 ? (
            <MapEmptyOverlay onExtractFromScript={onExtractFromScript} />
          ) : null}
          <div
            className={styles.world}
            style={{
              width: WORLD_W,
              height: WORLD_H,
              transform: `translate(${-cam.x}px, ${-cam.y}px) scale(${cam.zoom})`,
              transformOrigin: "0 0",
            }}
          >
            <MapStage />
            <svg className={styles.roads} width={WORLD_W} height={WORLD_H} aria-hidden>
              {strokes.map((s) => renderPath(s.points, s.color, s.width, s.id))}
              {draftPts.length > 1 &&
                renderPath(draftPts, brushColor, brushWidth, "draft")}
              {links.map((link) => {
                const a = byId.get(link.fromId);
                const b = byId.get(link.toId);
                if (!a || !b) return null;
                const curve = roadCurves.get(link.id);
                const mx = curve?.mx ?? (a.x + b.x) / 2;
                const my = curve?.my ?? (a.y + b.y) / 2;
                const ls = link.lineStyle ?? "solid";
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
                  </g>
                );
              })}
            </svg>
            <div className={styles.pinLayer}>
              {nodes.map((n) => {
                const { glyph, color } = resolvePin(n, customElements);
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
                    <span className={styles.pinBadge}>
                      <MapPinGlyph kind={glyph} color={color} active={active} />
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
      <MapInspector
        selectedIds={selectedIds}
        selected={selected}
        customElements={customElements}
        occurrences={occurrences}
        links={links}
        nameOf={(id) => byId.get(id)?.name ?? "?"}
        onPatchSelected={updateSelected}
        onDeleteSelected={deleteSelected}
        onJumpToChapter={onJumpToChapter}
        onRemoveLink={(id) => onChangeLinks(links.filter((x) => x.id !== id))}
      />
    </div>
  );
}
