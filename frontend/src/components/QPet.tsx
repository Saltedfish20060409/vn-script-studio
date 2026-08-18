import { useCallback, useEffect, useRef, useState } from "react";
import {
  getDeskPetState,
  setDeskPetEnabled,
  setDeskPetPos,
  subscribeDeskPet,
} from "../lib/deskPet";
import { mascotLine } from "../lib/mascotCopy";
import {
  IDLE_POOL_CORNER,
  IDLE_POOL_DOCK,
  PET_ANIMATIONS,
  PET_CANVAS,
  petFrameUrl,
  type PetActionId,
} from "../lib/petAnimations";
import type { MascotMood } from "./MascotFigure";
import { PetPlaceholder } from "./PetPlaceholder";
import styles from "./QPet.module.css";

type PetMode = "dock" | "corner" | "free" | "edge-left" | "edge-right";

const PET_W = 108;
const PET_H = 152;
const DOCK_GAP = 10;
/** 散步移动的过渡时长（ms）：要「慢」，所以比普通换位长 */
const WALK_MS = 4200;

const MOOD_FOR_STANCE: Record<PetActionId, MascotMood> = {
  breath_idle: "idle",
  blink: "idle",
  walk_side_r: "idle",
  perch_top: "idle",
  peek_over: "idle",
  peek_side_r: "idle",
  perch_side_r: "idle",
  peek_under: "idle",
  hide_corner: "worry",
  slip_r: "idle",
  react_fluster: "fluster",
  react_cheer: "cheer",
  fall_asleep: "idle",
  drag_held: "fluster",
  drop_land: "fluster",
  read_over_shoulder: "think",
};

/** 点击反应池：不规律触发 */
const CLICK_POOL: Array<{ stance: PetActionId; text: string | null }> = [
  { stance: "react_fluster", text: null },
  { stance: "react_cheer", text: "嘿嘿。" },
  { stance: "breath_idle", text: mascotLine("deskPet") },
  { stance: "read_over_shoulder", text: "在看我吗？" },
];

function clampX(x: number, w = PET_W): number {
  return Math.max(0, Math.min(x, window.innerWidth - w - 8));
}
function clampY(y: number, h = PET_H): number {
  return Math.max(0, Math.min(y, window.innerHeight - h - 8));
}

function dockFromEditorRect(rect: DOMRect): { x: number; y: number } {
  return {
    x: clampX(rect.right + DOCK_GAP),
    y: clampY(rect.bottom - PET_H),
  };
}

function cornerPos(): { x: number; y: number } {
  return {
    x: clampX(window.innerWidth - PET_W - 16),
    y: clampY(window.innerHeight - PET_H - 16),
  };
}

/** 姿态 → dock 位置：坐/趴框顶、探头贴框顶、其余站右侧 */
function dockPosFor(stance: PetActionId, rect: DOMRect): { x: number; y: number } {
  const s = PET_ANIMATIONS[stance];
  const c = PET_CANVAS[s.canvas];
  const h = (PET_W / c.w) * c.h;
  if (s.anchor?.sit_contact) {
    const ratio = s.anchor.sit_contact.y / c.h;
    return {
      x: clampX(rect.left + rect.width / 2 - PET_W / 2),
      y: clampY(rect.top - h * ratio),
    };
  }
  if (s.canvas === "B") {
    return {
      x: clampX(rect.left + rect.width / 2 - 48, 96),
      y: clampY(rect.top - 56, 96),
    };
  }
  return dockFromEditorRect(rect);
}

/** 散步兴趣点：文本框顶 / 框右侧 / 页面底部中间 / 页面中部左右 */
function walkTargets(editorRef?: React.RefObject<HTMLTextAreaElement | null>) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const spots: Array<{ x: number; y: number; stance: PetActionId }> = [
    { x: clampX(vw / 2 - PET_W / 2), y: clampY(vh - PET_H - 20), stance: "breath_idle" }, // 页面底部中间
    { x: clampX(vw * 0.16), y: clampY(vh * 0.55), stance: "breath_idle" }, // 页面中部偏左
    { x: clampX(vw - PET_W - 20), y: clampY(vh * 0.42), stance: "breath_idle" }, // 右侧中部
    { x: clampX(vw * 0.5 - PET_W / 2), y: clampY(vh * 0.2), stance: "breath_idle" }, // 中上部
  ];
  const el = editorRef?.current;
  if (el) {
    const r = el.getBoundingClientRect();
    if (r.width > 40) {
      spots.push({
        x: clampX(r.left + r.width / 2 - PET_W / 2),
        y: clampY(r.top - 96),
        stance: "perch_top",
      }); // 趴回文本框顶
      spots.push({
        x: clampX(r.right + DOCK_GAP),
        y: clampY(r.bottom - PET_H),
        stance: "breath_idle",
      }); // 框右侧
    }
  }
  return spots;
}

type Props = {
  editorRef?: React.RefObject<HTMLTextAreaElement | null>;
  cheerSignal?: number;
};

/** Q 版桌宠：散步 / 贴边探头 / 多待机 / 点击反应 / 拖拽。 */
export function QPet({ editorRef, cheerSignal }: Props) {
  const [enabled, setEnabled] = useState(getDeskPetState().enabled);
  const [mode, setMode] = useState<PetMode>("corner");
  const [pos, setPos] = useState<{ x: number; y: number }>(() => cornerPos());
  const [stance, setStance] = useState<PetActionId>("breath_idle");
  const [frameIdx, setFrameIdx] = useState(0);
  const [hasFrames, setHasFrames] = useState<Record<string, boolean>>({});
  const [line, setLine] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [moveMs, setMoveMs] = useState(1500);
  const [walkDir, setWalkDir] = useState<1 | -1>(1);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const prevEnabledRef = useRef(getDeskPetState().enabled);
  const lineTimer = useRef<number | null>(null);
  const idleTimer = useRef<number | null>(null);
  const wanderTimer = useRef<number | null>(null);
  const clickTimer = useRef<number | null>(null);
  const moveTimer = useRef<number | null>(null);
  const prevCheer = useRef(cheerSignal ?? 0);

  // 设置开关同步：只在「关→开」时归位，位置更新（拖拽保存）不重置
  useEffect(() => {
    const onStore = () => {
      const st = getDeskPetState();
      if (st.enabled !== prevEnabledRef.current) {
        if (st.enabled) {
          setPos(cornerPos());
          setStance("breath_idle");
          setMode("corner");
        }
        prevEnabledRef.current = st.enabled;
      }
      setEnabled(st.enabled);
    };
    return subscribeDeskPet(onStore);
  }, []);

  const say = useCallback((text: string) => {
    setLine(text);
    if (lineTimer.current) window.clearTimeout(lineTimer.current);
    lineTimer.current = window.setTimeout(() => setLine(null), 5200);
  }, []);

  const markFrameResult = useCallback((action: string, ok: boolean) => {
    setHasFrames((prev) => {
      if (prev[action] === ok) return prev;
      return { ...prev, [action]: ok };
    });
  }, []);

  const spec = PET_ANIMATIONS[stance];
  const framesReady = hasFrames[stance] === true;
  const isPeek = spec.canvas === "B";
  const showW = isPeek ? 96 : PET_W;
  const mood = MOOD_FOR_STANCE[stance];
  const isEdge = mode === "edge-left" || mode === "edge-right";

  // 动画循环：按每帧停留时长推进；循环 / 单次停帧 / 单次播完回呼吸
  useEffect(() => {
    if (!framesReady) return; // 占位由 CSS 动画负责
    let cancelled = false;
    let idx = frameIdx === 0 ? 0 : frameIdx;
    const step = () => {
      if (cancelled) return;
      const next = idx + 1;
      if (next >= spec.frames) {
        if (spec.loop) {
          idx = 0;
          setFrameIdx(0);
        } else if (spec.stopAt) {
          setFrameIdx(spec.stopAt - 1);
          return;
        } else {
          if (stance !== "breath_idle") setStance("breath_idle");
          return;
        }
      } else {
        idx = next;
        setFrameIdx(next);
      }
      window.setTimeout(step, spec.holdMs[idx] ?? 400);
    };
    const t = window.setTimeout(step, spec.holdMs[idx] ?? 400);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stance, framesReady]);

  // 姿态 → dock 位置联动
  useEffect(() => {
    if (mode !== "dock" || !enabled) return;
    const el = editorRef?.current;
    if (!el) return;
    setPos(dockPosFor(stance, el.getBoundingClientRect()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stance, mode, enabled]);

  // 多套待机不规律切换（edge 模式保持探头，不切换）
  useEffect(() => {
    if (!enabled || isEdge) return;
    idleTimer.current = window.setTimeout(() => {
      const pool = mode === "dock" ? IDLE_POOL_DOCK : IDLE_POOL_CORNER;
      const next = pool[Math.floor(Math.random() * pool.length)];
      setStance(next);
    }, 5000 + Math.random() * 7000);
    return () => {
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
    };
  }, [enabled, mode, stance, isEdge]);

  // 一段时间后散步：慢速走向兴趣点（walk 姿态 + 方向）
  useEffect(() => {
    if (!enabled || mode === "free" || isEdge) return;
    wanderTimer.current = window.setTimeout(
      () => {
        const spots = walkTargets(editorRef);
        const target = spots[Math.floor(Math.random() * spots.length)];
        const dx = target.x - pos.x;
        setWalkDir(dx < -4 ? -1 : 1); // 目标在左 → 朝左走（镜像）
        setMoveMs(WALK_MS);
        setStance("walk_side_r");
        setPos(target);
        if (moveTimer.current) window.clearTimeout(moveTimer.current);
        moveTimer.current = window.setTimeout(() => {
          setMoveMs(1500);
          setStance(target.stance);
        }, WALK_MS + 200);
      },
      18000 + Math.random() * 22000
    );
    return () => {
      if (wanderTimer.current) window.clearTimeout(wanderTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, mode, pos, isEdge]);

  // 编辑器可见 → dock（趴框顶为主）；不可见 → corner；free/edge 不干预
  useEffect(() => {
    if (!enabled || mode === "free" || isEdge) return;
    const el = editorRef?.current;
    if (!el) {
      setMode("corner");
      setPos(cornerPos());
      return;
    }
    const rect = el.getBoundingClientRect();
    const inView =
      rect.width > 40 &&
      rect.top < window.innerHeight &&
      rect.bottom > 0 &&
      rect.left < window.innerWidth &&
      rect.right > 0;
    if (inView) {
      setMode("dock");
      if (stance === "breath_idle" && Math.random() < 0.7) {
        setStance("perch_top");
      }
    } else {
      setMode("corner");
      setPos(cornerPos());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, mode, editorRef, isEdge]);

  // 外部庆祝信号
  useEffect(() => {
    if (cheerSignal !== undefined && cheerSignal !== prevCheer.current) {
      prevCheer.current = cheerSignal;
      if (enabled) {
        setStance("react_cheer");
        say(isLateNight() ? "这么晚还保存，辛苦了。" : "保存成功，写得漂亮。");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cheerSignal, enabled]);

  // 拖拽 / 点击 / 贴边
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      originX: pos.x,
      originY: pos.y,
      moved: false,
    };
    setMode("free");
    setDragging(true);
    setMoveMs(0);
    setStance("drag_held");
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true;
    if (d.moved) {
      setPos({ x: clampX(d.originX + dx), y: clampY(d.originY + dy) });
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current;
    dragRef.current = null;
    setDragging(false);
    setMoveMs(1500);
    if (d?.moved) {
      const finalPos = {
        x: clampX(d.originX + (e.clientX - d.startX)),
        y: clampY(d.originY + (e.clientY - d.startY)),
      };
      // 贴边 → 吸附成「探出头」：拖到左右边缘留一半在屏幕内
      const vw = window.innerWidth;
      if (finalPos.x <= 6) {
        setMode("edge-left");
        setStance("peek_side_r");
        setPos({ x: -showW * 0.55, y: finalPos.y });
        setDeskPetPos({ x: -showW * 0.55, y: finalPos.y });
      } else if (finalPos.x >= vw - showW - 6) {
        setMode("edge-right");
        setStance("peek_side_r");
        setPos({ x: vw - showW * 0.45, y: finalPos.y });
        setDeskPetPos({ x: vw - showW * 0.45, y: finalPos.y });
      } else {
        setPos(finalPos);
        setDeskPetPos(finalPos);
        setStance("drop_land");
        window.setTimeout(() => {
          setMode("free");
          setStance("breath_idle");
        }, 320);
      }
      return;
    }
    // 单击
    if (clickTimer.current) window.clearTimeout(clickTimer.current);
    clickTimer.current = window.setTimeout(() => {
      if (isEdge) {
        // 贴边时点击 → 从边缘探出跳回屏幕内
        const vw = window.innerWidth;
        setMode("free");
        setStance("react_cheer");
        setPos({ x: mode === "edge-left" ? 24 : vw - showW - 24, y: pos.y });
        say("被发现了！");
        window.setTimeout(() => setStance("breath_idle"), 900);
        return;
      }
      const pick = CLICK_POOL[Math.floor(Math.random() * CLICK_POOL.length)];
      setStance(pick.stance);
      if (pick.text) say(isLateNight() ? `（深夜）${pick.text}` : pick.text);
      window.setTimeout(() => {
        if (pick.stance !== "breath_idle") setStance("breath_idle");
      }, 1000);
    }, 240);
  };
  const onDoubleClick = () => {
    if (clickTimer.current) window.clearTimeout(clickTimer.current);
    setStance("react_cheer");
    say("摸头杀……开心。");
    window.setTimeout(() => setStance("breath_idle"), 1000);
  };

  const dockHome = () => {
    setMenuOpen(false);
    setMode("dock");
    setStance("breath_idle");
    setMoveMs(1500);
    const el = editorRef?.current;
    if (el) setPos(dockPosFor("breath_idle", el.getBoundingClientRect()));
    else setPos(cornerPos());
  };
  const goCorner = () => {
    setMenuOpen(false);
    setMode("corner");
    setStance("hide_corner");
    setPos(cornerPos());
    window.setTimeout(() => setStance("breath_idle"), 900);
  };
  const hide = () => {
    setMenuOpen(false);
    setDeskPetEnabled(false);
  };

  useEffect(
    () => () => {
      if (lineTimer.current) window.clearTimeout(lineTimer.current);
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
      if (wanderTimer.current) window.clearTimeout(wanderTimer.current);
      if (clickTimer.current) window.clearTimeout(clickTimer.current);
      if (moveTimer.current) window.clearTimeout(moveTimer.current);
    },
    []
  );

  if (!enabled) return null;

  // 朝向：walk 朝左镜像；edge-left 探头朝右、edge-right 探头朝左（探回屏幕）
  const flip =
    stance === "walk_side_r"
      ? walkDir
      : mode === "edge-left"
        ? 1
        : mode === "edge-right"
          ? -1
          : 1;
  const animClass = placeholderAnim(stance);

  return (
    <div
      className={`${styles.pet} ${dragging ? styles.dragging : ""}`}
      style={{
        left: pos.x,
        top: pos.y,
        width: showW,
        transitionDuration: `${moveMs}ms, ${moveMs}ms`,
      }}
      data-mode={mode}
      data-stance={stance}
      data-testid="q-pet"
    >
      {line && (
        <div className={styles.bubble} role="status" aria-live="polite">
          {line}
        </div>
      )}
      <div
        className={styles.body}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
        onContextMenu={(e) => {
          e.preventDefault();
          setMenuOpen((v) => !v);
        }}
        title="点击互动 · 双击摸头 · 拖到边缘探头 · 右键菜单"
      >
        {framesReady ? (
          <img
            key={`${stance}-${frameIdx}`}
            className={styles.frame}
            style={{ transform: `scaleX(${flip})` }}
            src={petFrameUrl(spec, frameIdx)}
            alt=""
            draggable={false}
            onError={() => markFrameResult(stance, false)}
            onLoad={() => markFrameResult(stance, true)}
          />
        ) : (
          <div className={animClass}>
            <PetPlaceholder mood={mood} />
          </div>
        )}
      </div>
      {menuOpen && (
        <div className={styles.menu}>
          <button type="button" onClick={dockHome}>
            回到编辑器
          </button>
          <button type="button" onClick={goCorner}>
            缩到角落
          </button>
          <button type="button" onClick={hide}>
            隐藏桌宠
          </button>
        </div>
      )}
    </div>
  );
}

/** 占位模式下的动作动画 class（无美术帧时也能看出"额外动画"） */
function placeholderAnim(stance: PetActionId): string {
  switch (stance) {
    case "react_fluster":
      return styles.petShake;
    case "react_cheer":
      return styles.petJump;
    case "fall_asleep":
      return styles.petNod;
    case "walk_side_r":
      return styles.petBob;
    case "peek_over":
    case "peek_side_r":
    case "peek_under":
      return styles.petLean;
    default:
      return "";
  }
}

function isLateNight(): boolean {
  const h = new Date().getHours();
  return h >= 23 || h < 5;
}
