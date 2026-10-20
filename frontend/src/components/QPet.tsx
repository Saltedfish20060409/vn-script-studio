import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  getDeskPetState,
  setDeskPetEnabled,
  setDeskPetPos,
  subscribeDeskPet,
  type PetWanderInterval,
} from "../lib/deskPet";
import { subscribePet } from "../lib/petBridge";
import { petLine } from "../lib/petCopy";
import { masterPxPerSec } from "../lib/petMotion";
import {
  createPetState,
  petReducer,
  type PetMood,
  type PetPlacement,
  type PetState,
} from "../lib/petMachine";
import {
  loadPetManifest,
  preloadPetAssets,
  type PetManifest,
  type PetWalkDir,
} from "../lib/petManifest";
import {
  FRAME_EDGE_BAND_PX,
  PET_DISPLAY,
  anchorOf,
  bodyMetrics,
  boxAt,
  canPeekAt,
  canPeekUnderAt,
  canPerchAt,
  canPerchSideAt,
  classifyDrop,
  mirroredAnchor,
  petScale,
  petVisual,
  upsideDownAnchor,
  type PetBodyMetrics,
  type PetBox,
  type PetViewport,
  type PetVisual,
} from "../lib/petVisual";
import type { MascotMood } from "./MascotFigure";
import { PetPlaceholder } from "./PetPlaceholder";
import { PetSprite } from "./PetSprite";
import styles from "./QPet.module.css";

const DOCK_GAP = 10;
/** 底部固定音乐条的高度预留：桌宠角落/游走不上遮挡区（条高约 43px，这里留点余量） */
const BAR_RESERVE = 50;
const CORNER_GAP = 16;
const WALK_PX_PER_S = 60;
const TICK_MS = 1000;
const CLICK_DELAY_MS = 240;
const DRAG_THRESHOLD_PX = 4;
/** 气泡出现后播口型的时长：每字约 90ms，封顶 1.6s */
const BUBBLE_TALK_MS_PER_CHAR = 90;
const BUBBLE_TALK_MAX_MS = 1600;

/** 清单加载失败时占位小人用的画布：A 套站姿 */
const FALLBACK_METRICS: PetBodyMetrics = {
  w: 320,
  h: 480,
  anchor: { x: 160, y: 450 },
  emote: { size: 42, above_right: [250, 7], zzz: [264, 1], temple: [268, 52] },
};

const PLACEHOLDER_MOOD: Record<PetMood, MascotMood> = {
  neutral: "idle",
  happy: "cheer",
  sad: "worry",
  think: "think",
  fluster: "fluster",
};

/** 会自己走动的位置；自由摆放和贴边尊重用户的摆放，不走 */
const WANDER_FROM: ReadonlySet<PetPlacement> = new Set<PetPlacement>([
  "corner",
  "dock",
  "perchTop",
  "peekOver",
]);

/** 挂在编辑框上的位置：滚动时跟着框，框消失就落地 */
const ON_FRAME: ReadonlySet<PetPlacement> = new Set<PetPlacement>([
  "perchTop",
  "peekOver",
  "peekUnder",
  "perchSideLeft",
  "perchSideRight",
]);

const GROUND: ReadonlySet<PetPlacement> = new Set<PetPlacement>(["corner", "dock", "free"]);

type WalkPlan = {
  from: PetBox;
  to: PetBox;
  dir: PetWalkDir;
  placement: PetPlacement;
  /** 走到后要用的画布位置（坐框顶 / 探头会换画布） */
  arrive: PetBox;
};

type Props = {
  editorRef?: React.RefObject<HTMLTextAreaElement | null>;
  cheerSignal?: number;
};

function viewport(): PetViewport {
  return { w: window.innerWidth, h: window.innerHeight, bottomReserve: BAR_RESERVE };
}

function displayWidth(): number {
  return window.innerWidth < 768 ? PET_DISPLAY.small : PET_DISPLAY.medium;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function isLateNight(): boolean {
  const h = new Date().getHours();
  return h >= 23 || h < 5;
}

function reactionActive(s: PetState, now: number): boolean {
  return s.reaction !== null && s.reaction.until > now;
}

/** 与 petReducer 的 walkStart 条件一致：先判断，避免改了位置却没走成 */
function canWalk(s: PetState, now: number): boolean {
  return !s.reducedMotion && s.body !== "sleep" && s.body !== "held" && !reactionActive(s, now);
}

function isResting(s: PetState): boolean {
  return (
    s.body === "idle" ||
    s.body === "perchTop" ||
    s.body === "peekOver" ||
    s.body === "peekSide" ||
    s.body === "hideCorner"
  );
}

/** 同一句气泡的随机数固定，重渲染不换词 */
function bubbleRand(id: number): number {
  return ((id * 9301 + 49297) % 233280) / 233280;
}

/** Q 版桌宠：状态由 petMachine 决定，这里负责屏幕位置、走动、拖拽和输入。 */
export function QPet({ editorRef, cheerSignal }: Props) {
  const [enabled, setEnabled] = useState(getDeskPetState().enabled);
  const [manifest, setManifest] = useState<PetManifest | null | undefined>(undefined);
  const [state, dispatch] = useReducer(petReducer, undefined, () =>
    createPetState(Date.now(), { placement: "corner", reducedMotion: prefersReducedMotion() })
  );
  const [box, setBox] = useState<PetBox | null>(null);
  const [moveMs, setMoveMs] = useState(0);
  const [walkDir, setWalkDir] = useState<PetWalkDir>("r");
  const [displayW, setDisplayW] = useState(displayWidth);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [bubbleTalk, setBubbleTalk] = useState(false);
  const [behaviorTick, setBehaviorTick] = useState(0);
  const scale = petScale(displayW);

  const stateRef = useRef(state);
  const boxRef = useRef(box);
  useEffect(() => {
    stateRef.current = state;
    boxRef.current = box;
  });
  const rootRef = useRef<HTMLDivElement>(null);
  const walkPlan = useRef<WalkPlan | null>(null);
  const walking = useRef(false);
  const walkTimers = useRef<number[]>([]);
  const clickTimer = useRef<number | null>(null);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    origin: PetBox;
    moved: boolean;
    sampleX: number;
    sampleT: number;
  } | null>(null);
  const dragSpeed = useRef(0);
  /** 挂在编辑框上时，挂点相对框左缘、上缘的距离 */
  const frameOffset = useRef<{ x: number; y: number } | null>(null);
  const leavingFrame = useRef(false);
  const prevEnabled = useRef(enabled);
  const prevCheer = useRef(cheerSignal ?? 0);

  const metricsOf = useCallback(
    (body: PetVisual["body"], dir: PetWalkDir = "r"): PetBodyMetrics =>
      manifest ? bodyMetrics(manifest, body, dir) : FALLBACK_METRICS,
    [manifest]
  );

  const editorRect = useCallback((): DOMRect | null => {
    const el = editorRef?.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const inView =
      r.width > 40 &&
      r.top < window.innerHeight &&
      r.bottom > 0 &&
      r.left < window.innerWidth &&
      r.right > 0;
    return inView ? r : null;
  }, [editorRef]);

  /** 站立姿势：整张画布留在屏幕内，脚不踩进底部条 */
  const clampGround = useCallback(
    (b: PetBox): PetBox => {
      const met = metricsOf("idle");
      const vp = viewport();
      return {
        left: Math.max(0, Math.min(b.left, vp.w - met.w * scale)),
        top: Math.max(0, Math.min(b.top, vp.h - vp.bottomReserve - met.anchor.y * scale)),
      };
    },
    [metricsOf, scale]
  );

  const groundBoxAt = useCallback(
    (x: number, footY: number) => clampGround(boxAt(metricsOf("idle"), scale, x, footY)),
    [clampGround, metricsOf, scale]
  );

  const cornerBox = useCallback(() => {
    const met = metricsOf("idle");
    const vp = viewport();
    return groundBoxAt(
      vp.w - CORNER_GAP - (met.w - met.anchor.x) * scale,
      vp.h - vp.bottomReserve - 8
    );
  }, [groundBoxAt, metricsOf, scale]);

  const dockBox = useCallback(
    (r: DOMRect) => {
      const met = metricsOf("idle");
      return groundBoxAt(
        r.right + DOCK_GAP + met.anchor.x * scale,
        Math.min(r.bottom, window.innerHeight - BAR_RESERVE - 8)
      );
    },
    [groundBoxAt, metricsOf, scale]
  );

  const perchX = useCallback(
    (r: DOMRect, x: number) => {
      const half = (metricsOf("perch_top").w / 2) * scale;
      return Math.max(r.left + half * 0.6, Math.min(x, r.right - half * 0.6));
    },
    [metricsOf, scale]
  );

  const perchBox = useCallback(
    (r: DOMRect, x: number) => boxAt(metricsOf("perch_top"), scale, perchX(r, x), r.top),
    [metricsOf, perchX, scale]
  );

  const peekBox = useCallback(
    (r: DOMRect, x: number) => boxAt(metricsOf("peek_over"), scale, perchX(r, x), r.top),
    [metricsOf, perchX, scale]
  );

  const peekUnderBox = useCallback(
    (r: DOMRect, x: number) =>
      boxAt(upsideDownAnchor(metricsOf("peek_over")), scale, perchX(r, x), r.bottom),
    [metricsOf, perchX, scale]
  );

  const sideFootY = useCallback((r: DOMRect, y: number) => {
    const lo = r.top + FRAME_EDGE_BAND_PX;
    const hi = Math.max(lo, r.bottom - FRAME_EDGE_BAND_PX);
    return Math.max(lo, Math.min(y, hi));
  }, []);

  const perchSideBox = useCallback(
    (side: "perchSideLeft" | "perchSideRight", r: DOMRect, y: number) => {
      const met = metricsOf("perch_side");
      const yy = sideFootY(r, y);
      if (side === "perchSideRight") return boxAt(met, scale, r.right, yy);
      return boxAt(mirroredAnchor(met), scale, r.left, yy);
    },
    [metricsOf, scale, sideFootY]
  );

  const edgeBox = useCallback(
    (side: "edgeLeft" | "edgeRight", y: number) => {
      const met = metricsOf(side === "edgeLeft" ? "peek_side_l" : "peek_side_r");
      const vp = viewport();
      const lo = met.anchor.y * scale * 0.6;
      const hi = vp.h - vp.bottomReserve - (met.h - met.anchor.y) * scale;
      const yy = Math.max(lo, Math.min(y, hi));
      return boxAt(met, scale, side === "edgeLeft" ? 0 : vp.w, yy);
    },
    [metricsOf, scale]
  );

  const perchable = useCallback(
    (r: DOMRect) => !manifest || canPerchAt(manifest, scale, r.top, viewport()),
    [manifest, scale]
  );
  const peekable = useCallback(
    (r: DOMRect) => !manifest || canPeekAt(manifest, scale, r.top),
    [manifest, scale]
  );
  const peekUnderable = useCallback(
    (r: DOMRect) => !manifest || canPeekUnderAt(manifest, scale, r.bottom, viewport()),
    [manifest, scale]
  );
  const sideable = useCallback(
    (side: "perchSideLeft" | "perchSideRight", r: DOMRect) =>
      !manifest || canPerchSideAt(side, manifest, scale, side === "perchSideLeft" ? r.left : r.right, viewport()),
    [manifest, scale]
  );

  const homePlacement = useCallback(
    (): PetPlacement => (editorRect() ? "dock" : "corner"),
    [editorRect]
  );

  const place = useCallback((b: PetBox, ms = 0) => {
    setMoveMs(ms);
    setBox(b);
  }, []);

  // 清单
  useEffect(() => {
    let alive = true;
    loadPetManifest().then((m) => {
      if (!alive) return;
      setManifest(m);
      if (m) preloadPetAssets(m);
    });
    return () => {
      alive = false;
    };
  }, []);

  // 首次摆放（清单到了之后，挂点才准）
  useEffect(() => {
    if (!enabled || manifest === undefined || boxRef.current) return;
    const r = editorRect();
    if (r) {
      dispatch({ type: "arrive", now: Date.now(), placement: "dock" });
      place(dockBox(r));
    } else {
      place(cornerBox());
    }
  }, [enabled, manifest, editorRect, dockBox, cornerBox, place]);

  // 设置开关同步：只在「关→开」时归位
  useEffect(
    () =>
      subscribeDeskPet(() => {
        const st = getDeskPetState();
        if (st.enabled && !prevEnabled.current) {
          dispatch({ type: "arrive", now: Date.now(), placement: "corner" });
          setBox(null);
        }
        prevEnabled.current = st.enabled;
        setEnabled(st.enabled);
      }),
    []
  );

  // 状态机时钟：没有变化时 reducer 返回原对象，不触发提交
  useEffect(() => {
    if (!enabled) return;
    const t = window.setInterval(
      () => dispatch({ type: "tick", now: Date.now(), r: Math.random() }),
      TICK_MS
    );
    return () => window.clearInterval(t);
  }, [enabled]);

  // 系统「减少动态」
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const on = () => dispatch({ type: "settings", reducedMotion: mq.matches });
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // 外部庆祝信号（保存成功）
  useEffect(() => {
    if (cheerSignal === undefined || cheerSignal === prevCheer.current) return;
    prevCheer.current = cheerSignal;
    if (enabled) {
      dispatch({ type: "app", now: Date.now(), event: "save:ok", lateNight: isLateNight() });
    }
  }, [cheerSignal, enabled]);

  useEffect(() => {
    return subscribePet((signal) => {
      if (!enabled) return;
      const now = Date.now();
      if (signal.kind === "sleep") {
        dispatch({ type: "forceSleep", now });
        return;
      }
      dispatch({
        type: "app",
        now,
        event: signal.event,
        line: signal.line,
        lateNight: isLateNight(),
      });
    });
  }, [enabled]);

  const clearWalkTimers = () => {
    walkTimers.current.forEach((t) => window.clearTimeout(t));
    walkTimers.current = [];
  };

  /** 走到一半被打断：停在当前画面位置，状态机离开 walk */
  const freezeWalk = useCallback(() => {
    if (!walking.current && !walkPlan.current) return;
    clearWalkTimers();
    walking.current = false;
    walkPlan.current = null;
    const el = rootRef.current;
    if (el) {
      const r = el.getBoundingClientRect();
      place({ left: r.left, top: r.top });
    }
    dispatch({ type: "arrive", now: Date.now(), placement: homePlacement() });
  }, [place, homePlacement]);

  // 走路：状态机进入 walk 后才开始位移；身体不再是 walk 时停下
  useEffect(() => {
    if (state.body !== "walk") {
      if (walking.current) freezeWalk();
      return;
    }
    const plan = walkPlan.current;
    if (!plan || walking.current) return;
    walking.current = true;
    setWalkDir(plan.dir);
    place(plan.from);
    const dist = Math.hypot(plan.to.left - plan.from.left, plan.to.top - plan.from.top);
    const ms = Math.max(400, (dist / WALK_PX_PER_S) * 1000);
    const raf = requestAnimationFrame(() =>
      requestAnimationFrame(() => place(plan.to, ms))
    );
    walkTimers.current.push(
      window.setTimeout(() => {
        walking.current = false;
        walkPlan.current = null;
        place(plan.arrive);
        dispatch({ type: "arrive", now: Date.now(), placement: plan.placement });
        setBehaviorTick((t) => t + 1);
      }, ms + 60)
    );
    return () => cancelAnimationFrame(raf);
  }, [state.body, freezeWalk, place]);

  /** 当前挂点的屏幕位置：站姿是脚底；坐框顶 / 探头的挂点就在框顶线上，正好当站立点 */
  const currentFoot = useCallback(() => {
    const b = boxRef.current;
    if (!b) return null;
    return anchorOf(metricsOf(petVisual(stateRef.current).body, walkDir), scale, b);
  }, [metricsOf, scale, walkDir]);

  const planWalk = useCallback(() => {
    const foot = currentFoot();
    if (!foot) return false;
    const r = editorRect();
    const vp = viewport();
    const here: PetPlacement = r ? "dock" : "corner";
    const options: Array<{ x: number; y: number; placement: PetPlacement; arrive?: PetBox }> = [];
    const pick = (lo: number, hi: number) => lo + Math.random() * (hi - lo);
    if (r) {
      const x = pick(r.left + r.width * 0.2, r.right - r.width * 0.2);
      if (perchable(r)) options.push({ x, y: r.top, placement: "perchTop", arrive: perchBox(r, x) });
      if (peekable(r)) options.push({ x, y: r.top, placement: "peekOver", arrive: peekBox(r, x) });
      const d = anchorOf(metricsOf("idle"), scale, dockBox(r));
      options.push({ ...d, placement: "dock" });
    }
    for (let i = 0; i < 2; i++) {
      options.push({ x: pick(vp.w * 0.08, vp.w * 0.92), y: foot.y, placement: here });
    }
    const o = options[Math.floor(Math.random() * options.length)];
    if ((o.placement === "perchTop" || o.placement === "peekOver") && r) {
      frameOffset.current = { x: o.x - r.left, y: 0 };
    }
    const from = groundBoxAt(foot.x, foot.y);
    const to = groundBoxAt(o.x, o.y);
    walkPlan.current = {
      from,
      to,
      dir: to.left < from.left ? "l" : "r",
      placement: o.placement,
      arrive: o.arrive ?? to,
    };
    const now = Date.now();
    dispatch({ type: "arrive", now, placement: here });
    dispatch({ type: "walkStart", now });
    return true;
  }, [currentFoot, editorRect, perchable, peekable, perchBox, peekBox, dockBox, metricsOf, scale, groundBoxAt]);

  // 自主行为：间隔读本地 wanderInterval（normal 8–20s / calm 20–45s / off）
  useEffect(() => {
    if (!enabled || !box || dragging) return;
    const wander = getDeskPetState().wanderInterval as PetWanderInterval;
    if (wander === "off") return;
    const delay =
      wander === "calm" ? 20_000 + Math.random() * 25_000 : 8000 + Math.random() * 12_000;
    const t = window.setTimeout(() => {
      const s = stateRef.current;
      const now = Date.now();
      if (!walking.current && WANDER_FROM.has(s.placement) && isResting(s) && canWalk(s, now)) {
        const roll = Math.random();
        if (roll < 0.5) planWalk();
        else if (roll < 0.65 && GROUND.has(s.placement)) {
          dispatch({ type: "mini", now, body: "hideCorner" });
        }
      }
      // 自主周期里较高概率尝试闲聊（仍受状态机冷却；白天多为写作提醒）
      if (Math.random() < 0.45) dispatch({ type: "chatter", now, lateNight: isLateNight() });
      setBehaviorTick((v) => v + 1);
    }, delay);
    return () => window.clearTimeout(t);
  }, [enabled, box, dragging, behaviorTick, planWalk]);

  // 编辑器打字：10 秒内不闲聊
  useEffect(() => {
    if (!enabled) return;
    const el = editorRef?.current;
    if (!el) return;
    const onType = () => dispatch({ type: "typing", now: Date.now() });
    el.addEventListener("input", onType);
    el.addEventListener("keydown", onType);
    return () => {
      el.removeEventListener("input", onType);
      el.removeEventListener("keydown", onType);
    };
  }, [enabled, editorRef]);

  // 窗口尺寸变化：换显示尺寸，按位置重新摆
  useEffect(() => {
    const onResize = () => {
      setDisplayW(displayWidth());
      const s = stateRef.current;
      const b = boxRef.current;
      if (!b || walking.current) return;
      const r = editorRect();
      if (s.placement === "perchTop" && r) place(perchBox(r, anchorOf(metricsOf("perch_top"), scale, b).x));
      else if (s.placement === "peekOver" && r) place(peekBox(r, anchorOf(metricsOf("peek_over"), scale, b).x));
      else if (s.placement === "peekUnder" && r) {
        place(peekUnderBox(r, anchorOf(upsideDownAnchor(metricsOf("peek_over")), scale, b).x));
      } else if ((s.placement === "perchSideLeft" || s.placement === "perchSideRight") && r) {
        const met = s.placement === "perchSideLeft" ? mirroredAnchor(metricsOf("perch_side")) : metricsOf("perch_side");
        place(perchSideBox(s.placement, r, anchorOf(met, scale, b).y));
      } else if (s.placement === "edgeLeft" || s.placement === "edgeRight") {
        const met = metricsOf(s.placement === "edgeLeft" ? "peek_side_l" : "peek_side_r");
        place(edgeBox(s.placement, anchorOf(met, scale, b).y));
      } else place(clampGround(b));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [editorRect, perchBox, peekBox, peekUnderBox, perchSideBox, edgeBox, clampGround, metricsOf, place, scale]);

  const frameBox = useCallback(
    (placement: PetPlacement, r: DOMRect, off: { x: number; y: number }) => {
      if (placement === "perchTop") return perchBox(r, r.left + off.x);
      if (placement === "peekOver") return peekBox(r, r.left + off.x);
      if (placement === "peekUnder") return peekUnderBox(r, r.left + off.x);
      return perchSideBox(placement === "perchSideLeft" ? "perchSideLeft" : "perchSideRight", r, r.top + off.y);
    },
    [perchBox, peekBox, peekUnderBox, perchSideBox]
  );

  const anchorOnFrame = useCallback(
    (placement: PetPlacement, b: PetBox) => {
      if (placement === "perchTop") return anchorOf(metricsOf("perch_top"), scale, b);
      if (placement === "peekOver") return anchorOf(metricsOf("peek_over"), scale, b);
      if (placement === "peekUnder") return anchorOf(upsideDownAnchor(metricsOf("peek_over")), scale, b);
      const met = placement === "perchSideLeft" ? mirroredAnchor(metricsOf("perch_side")) : metricsOf("perch_side");
      return anchorOf(met, scale, b);
    },
    [metricsOf, scale]
  );

  // 挂在编辑框上时跟着框走。框滚出屏幕、或节点卸掉，就落到地面待机。
  const followFrame = useCallback(() => {
    const s = stateRef.current;
    if (!ON_FRAME.has(s.placement)) return;
    if (dragRef.current?.moved || walking.current || leavingFrame.current) return;
    const el = editorRef?.current;
    const r = el && el.isConnected ? editorRect() : null;
    if (!r) {
      leavingFrame.current = true;
      frameOffset.current = null;
      const b = boxRef.current;
      const x = b
        ? anchorOf(metricsOf(petVisual(s).body, walkDir), scale, b).x
        : window.innerWidth / 2;
      stateRef.current = { ...s, placement: "free", body: "idle" };
      dispatch({ type: "frameGone", now: Date.now() });
      const vp = viewport();
      place(groundBoxAt(x, vp.h - vp.bottomReserve - 8), 420);
      return;
    }
    if (frameOffset.current === null) {
      const b = boxRef.current;
      const grip = b ? anchorOnFrame(s.placement, b) : { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      frameOffset.current = { x: grip.x - r.left, y: grip.y - r.top };
    }
    const next = frameBox(s.placement, r, frameOffset.current);
    const b = boxRef.current;
    if (b && Math.abs(b.left - next.left) < 0.5 && Math.abs(b.top - next.top) < 0.5) return;
    place(next, 0);
  }, [editorRef, editorRect, metricsOf, scale, walkDir, place, groundBoxAt, frameBox, anchorOnFrame]);

  useEffect(() => {
    if (ON_FRAME.has(state.placement)) leavingFrame.current = false;
  }, [state.placement]);

  useEffect(() => {
    if (!enabled || !ON_FRAME.has(state.placement)) return;
    let queued = false;
    const schedule = () => {
      if (queued) return;
      queued = true;
      window.setTimeout(() => {
        queued = false;
        followFrame();
      }, 0);
    };
    document.addEventListener("scroll", schedule, true);
    window.addEventListener("scroll", schedule);
    window.addEventListener("resize", schedule);
    const poll = window.setInterval(schedule, 200);
    schedule();
    return () => {
      document.removeEventListener("scroll", schedule, true);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.clearInterval(poll);
    };
  }, [enabled, state.placement, followFrame]);

  // 菜单打开时：点菜单外任意处关闭（菜单内按钮 stopPropagation 不受影响）
  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [menuOpen]);

  const bubble = state.bubble;
  const bubbleText = useMemo(
    () => (bubble ? petLine(bubble.key, bubble.vars, bubbleRand(bubble.id)) : null),
    [bubble]
  );

  // 气泡出现时播一小段口型
  useEffect(() => {
    if (!bubbleText) {
      setBubbleTalk(false);
      return;
    }
    setBubbleTalk(true);
    const t = window.setTimeout(
      () => setBubbleTalk(false),
      Math.min(BUBBLE_TALK_MAX_MS, bubbleText.length * BUBBLE_TALK_MS_PER_CHAR)
    );
    return () => window.clearTimeout(t);
  }, [bubbleText]);

  /** 松手位置 → 落点（贴屏幕边 / 框顶 / 框后 / 框下 / 框外沿 / 自由） */
  const dropZone = (clientX: number, b: PetBox): { zone: PetPlacement; box: PetBox } => {
    const vp = viewport();
    const met = metricsOf("held");
    const foot = anchorOf(metricsOf("idle"), scale, b);
    const r = editorRect();
    let zone = classifyDrop(foot, clientX, r, vp.w);
    if (zone === "perchTop" && r && !perchable(r)) zone = "free";
    if (zone === "peekOver" && r && !peekable(r)) zone = "free";
    if (zone === "peekUnder" && r && !peekUnderable(r)) zone = "free";
    if ((zone === "perchSideLeft" || zone === "perchSideRight") && r && !sideable(zone, r)) zone = "free";
    if (zone === "edgeLeft") return { zone, box: edgeBox("edgeLeft", b.top + met.h * scale * 0.35) };
    if (zone === "edgeRight") return { zone, box: edgeBox("edgeRight", b.top + met.h * scale * 0.35) };
    if (zone === "perchTop" && r) return { zone, box: perchBox(r, foot.x) };
    if (zone === "peekOver" && r) return { zone, box: peekBox(r, foot.x) };
    if (zone === "peekUnder" && r) return { zone, box: peekUnderBox(r, foot.x) };
    if ((zone === "perchSideLeft" || zone === "perchSideRight") && r) {
      return { zone, box: perchSideBox(zone, r, foot.y) };
    }
    return { zone: "free", box: clampGround(b) };
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || !box) return;
    freezeWalk();
    const el = rootRef.current;
    const r = el?.getBoundingClientRect();
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origin: r ? { left: r.left, top: r.top } : box,
      moved: false,
      sampleX: e.clientX,
      sampleT: performance.now(),
    };
    dragSpeed.current = 0;
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* 指针已失效（如触屏被系统接管）：不捕获也能拖，只是移出元素后收不到事件 */
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD_PX) {
      d.moved = true;
      if (clickTimer.current) window.clearTimeout(clickTimer.current);
      setDragging(true);
      // 拎起姿势的领口对准指针，落点按拎起图的脚位判定
      const met = metricsOf("held");
      d.origin = {
        left: e.clientX - met.anchor.x * scale - dx,
        top: e.clientY - met.anchor.y * scale - dy,
      };
      dispatch({ type: "dragStart", now: Date.now() });
    }
    if (d.moved) {
      const now = performance.now();
      dragSpeed.current = masterPxPerSec(e.clientX - d.sampleX, now - d.sampleT, scale);
      d.sampleX = e.clientX;
      d.sampleT = now;
      place({ left: d.origin.left + dx, top: d.origin.top + dy });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current;
    dragRef.current = null;
    dragSpeed.current = 0;
    if (!d) return;
    if (d.moved) {
      setDragging(false);
      const dropped = {
        left: d.origin.left + (e.clientX - d.startX),
        top: d.origin.top + (e.clientY - d.startY),
      };
      const { zone, box: b } = dropZone(e.clientX, dropped);
      if (ON_FRAME.has(zone)) {
        const el = editorRef?.current;
        if (el) {
          const grip = anchorOnFrame(zone, b);
          const rect = el.getBoundingClientRect();
          frameOffset.current = { x: grip.x - rect.left, y: grip.y - rect.top };
        }
      } else {
        frameOffset.current = null;
      }
      place(b);
      setDeskPetPos({ x: b.left, y: b.top });
      dispatch({ type: "dragEnd", now: Date.now(), zone });
      return;
    }
    if (clickTimer.current) window.clearTimeout(clickTimer.current);
    clickTimer.current = window.setTimeout(() => {
      const s = stateRef.current;
      if (s.placement === "edgeLeft" || s.placement === "edgeRight") {
        const met = metricsOf("idle");
        const vp = viewport();
        const b = boxRef.current;
        const footY = b ? b.top + met.h * scale * 0.9 : vp.h - BAR_RESERVE;
        const x = s.placement === "edgeLeft" ? 24 + met.anchor.x * scale : vp.w - 24 - met.anchor.x * scale;
        place(groundBoxAt(x, footY), 400);
      }
      dispatch({ type: "click", now: Date.now() });
    }, CLICK_DELAY_MS);
  };

  const onDoubleClick = () => {
    if (clickTimer.current) window.clearTimeout(clickTimer.current);
    dispatch({ type: "doubleClick", now: Date.now() });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      dispatch({ type: "click", now: Date.now() });
    } else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
      e.preventDefault();
      setMenuOpen((v) => !v);
    } else if (e.key === "Escape") {
      setMenuOpen(false);
    }
  };

  const dockHome = () => {
    setMenuOpen(false);
    freezeWalk();
    const r = editorRect();
    dispatch({ type: "menu", now: Date.now(), action: "dock" });
    place(r ? dockBox(r) : cornerBox(), 600);
    setBehaviorTick((t) => t + 1);
  };
  const goCorner = () => {
    setMenuOpen(false);
    freezeWalk();
    dispatch({ type: "menu", now: Date.now(), action: "corner" });
    place(cornerBox(), 600);
  };
  const hide = () => {
    setMenuOpen(false);
    setDeskPetEnabled(false);
  };
  const menuAct = (action: "feed" | "play" | "poseCycle" | "headpat") => {
    setMenuOpen(false);
    if (action === "feed" || action === "play") freezeWalk();
    dispatch({ type: "menu", now: Date.now(), action });
  };
  const menuPeekUnder = () => {
    setMenuOpen(false);
    freezeWalk();
    const now = Date.now();
    const r = editorRect();
    const vp = viewport();
    if (manifest && r && canPeekUnderAt(manifest, scale, r.bottom, vp)) {
      const x = r.left + r.width / 2;
      frameOffset.current = { x: x - r.left, y: 0 };
      place(peekUnderBox(r, x), 480);
      dispatch({ type: "menu", now, action: "goZone", zone: "peekUnder" });
      return;
    }
    dispatch({ type: "menu", now, action: "goZone", zone: stateRef.current.placement });
  };
  const menuPerchSide = () => {
    setMenuOpen(false);
    freezeWalk();
    const now = Date.now();
    const r = editorRect();
    const vp = viewport();
    const b = boxRef.current;
    if (r && manifest) {
      const footY = b
        ? anchorOf(metricsOf("perch_side"), scale, b).y
        : r.top + r.height / 2;
      const mid = b ? b.left + metricsOf("idle").w * scale / 2 : r.left;
      const preferLeft = mid < (r.left + r.right) / 2;
      const sides: Array<"perchSideLeft" | "perchSideRight"> = preferLeft
        ? ["perchSideLeft", "perchSideRight"]
        : ["perchSideRight", "perchSideLeft"];
      for (const side of sides) {
        const edgeX = side === "perchSideLeft" ? r.left : r.right;
        if (!canPerchSideAt(side, manifest, scale, edgeX, vp)) continue;
        frameOffset.current = {
          x: side === "perchSideLeft" ? 0 : r.width,
          y: footY - r.top,
        };
        place(perchSideBox(side, r, footY), 480);
        dispatch({ type: "menu", now, action: "goZone", zone: side });
        return;
      }
    }
    dispatch({ type: "menu", now, action: "goZone", zone: stateRef.current.placement });
  };

  useEffect(
    () => () => {
      clearWalkTimers();
      if (clickTimer.current) window.clearTimeout(clickTimer.current);
    },
    []
  );

  if (!enabled || manifest === undefined || !box) return null;

  const visual = petVisual(state);
  const met = metricsOf(visual.body, walkDir);
  const w = met.w * scale;
  const h = met.h * scale;
  const headMark = met.emote.above_right[1];
  const headY = ((visual.upsideDown ? met.h - headMark : headMark) + met.emote.size / 2) * scale;
  const isWalking = visual.body === "walk";
  const popAlign =
    box.left + w / 2 > window.innerWidth / 2 ? { right: 0 } : { left: 0 };

  return (
    <div
      ref={rootRef}
      className={`${styles.pet} ${dragging ? styles.dragging : ""}`}
      style={{
        left: box.left,
        top: box.top,
        transitionDuration: `${moveMs}ms, ${moveMs}ms`,
        transitionTimingFunction: isWalking ? "linear" : undefined,
      }}
      data-body={state.body}
      data-placement={state.placement}
      data-testid="q-pet"
    >
      {bubbleText && (
        <div
          className={styles.bubble}
          style={{ bottom: h - headY + 4, ...popAlign }}
          role="status"
          aria-live="polite"
        >
          {bubbleText}
        </div>
      )}
      <div
        className={styles.body}
        style={{ width: w, height: h }}
        tabIndex={0}
        role="button"
        aria-label="桌宠：Enter 互动，Shift+F10 打开菜单"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
        onContextMenu={(e) => {
          e.preventDefault();
          setMenuOpen((v) => !v);
        }}
        title="点击互动 · 双击摸头 · 拖到框边/屏幕边缘 · 右键菜单"
      >
        {manifest ? (
          <PetSprite
            manifest={manifest}
            visual={visual}
            scale={scale}
            walkDir={walkDir}
            talking={state.talking || bubbleTalk}
            emoteKey={state.reaction?.until ?? 0}
            reducedMotion={state.reducedMotion}
            dragSpeedRef={dragSpeed}
          />
        ) : (
          <PetPlaceholder mood={PLACEHOLDER_MOOD[state.mood]} />
        )}
      </div>
      {menuOpen && (
        <div
          className={styles.menu}
          style={{ bottom: h - headY + 6, ...popAlign }}
          onPointerDown={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.key === "Escape" && setMenuOpen(false)}
        >
          <button type="button" onClick={dockHome}>
            回到编辑器
          </button>
          <button type="button" onClick={goCorner}>
            缩到角落
          </button>
          <button type="button" onClick={() => menuAct("feed")}>
            喂食
          </button>
          <button type="button" onClick={() => menuAct("play")}>
            玩耍
          </button>
          <button type="button" onClick={() => menuAct("poseCycle")}>
            换个姿势
          </button>
          <button type="button" onClick={menuPeekUnder}>
            去框下探头
          </button>
          <button type="button" onClick={menuPerchSide}>
            靠到框边
          </button>
          <button type="button" onClick={() => menuAct("headpat")}>
            摸摸头
          </button>
          <button type="button" onClick={hide}>
            隐藏桌宠
          </button>
        </div>
      )}
    </div>
  );
}
