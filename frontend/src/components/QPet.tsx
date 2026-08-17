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

type PetMode = "dock" | "corner" | "free";

const PET_W = 108;
const PET_H = 152;
const DOCK_GAP = 10;

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

/** 站姿：站在编辑器右侧沿，脚底对齐编辑器底部 */
function dockFromEditorRect(rect: DOMRect): { x: number; y: number } {
  return {
    x: clampX(rect.right + DOCK_GAP),
    y: clampY(rect.bottom - PET_H),
  };
}

function cornerPos(): { x: number; y: number } {
  return { x: clampX(window.innerWidth - PET_W - 16), y: clampY(window.innerHeight - PET_H - 16) };
}

/** 姿态 → dock 位置：坐/趴框顶（sit_contact 贴框顶）、探头（贴框顶上方）、其余站右侧 */
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

type Props = {
  editorRef?: React.RefObject<HTMLTextAreaElement | null>;
  cheerSignal?: number;
};

/**
 * Q 版桌宠：多套待机不规律切换 + 趴在文本框上 + 缓慢移动 + 点击反应 + 拖拽。
 * 美术逐帧 PNG 按 docs/mascot-pet-art-brief.md 命名放入 /pet/ 后自动生效，
 * 缺帧时用 Q 版占位（PetPlaceholder）。
 */
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
  const dragRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const lineTimer = useRef<number | null>(null);
  const idleTimer = useRef<number | null>(null);
  const wanderTimer = useRef<number | null>(null);
  const clickTimer = useRef<number | null>(null);
  const prevCheer = useRef(cheerSignal ?? 0);

  // 设置开关同步
  useEffect(() => {
    const onStore = () => {
      const st = getDeskPetState();
      setEnabled(st.enabled);
      if (st.enabled) {
        setPos(cornerPos());
        setStance("breath_idle");
      }
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

  // 动画循环：按每帧停留时长推进；循环 / 单次停帧 / 单次播完回呼吸
  useEffect(() => {
    if (!framesReady) return; // 占位由 CSS 浮动动画负责
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

  // 姿态 → dock 位置联动（含单次动作播完回呼吸时自动归位）
  useEffect(() => {
    if (mode !== "dock" || !enabled) return;
    const el = editorRef?.current;
    if (!el) return;
    setPos(dockPosFor(stance, el.getBoundingClientRect()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stance, mode, enabled]);

  // 多套待机不规律切换
  useEffect(() => {
    if (!enabled) return;
    idleTimer.current = window.setTimeout(() => {
      const pool = mode === "dock" ? IDLE_POOL_DOCK : IDLE_POOL_CORNER;
      const next = pool[Math.floor(Math.random() * pool.length)];
      setStance(next);
    }, 5000 + Math.random() * 7000);
    return () => {
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
    };
  }, [enabled, mode, stance]);

  // 一段时间后缓慢移动（wander）
  useEffect(() => {
    if (!enabled || mode === "free") return;
    wanderTimer.current = window.setTimeout(
      () => {
        const el = editorRef?.current;
        if (mode === "dock" && el) {
          const topish =
            stance === "perch_top" || stance === "peek_over" || stance === "fall_asleep";
          setStance(topish ? "breath_idle" : "perch_top"); // 位置由上面的联动 effect 处理
        } else if (mode === "corner") {
          const base = cornerPos();
          setPos({
            x: clampX(base.x + (Math.random() - 0.5) * 90),
            y: clampY(base.y + (Math.random() - 0.5) * 60),
          });
        }
      },
      22000 + Math.random() * 20000
    );
    return () => {
      if (wanderTimer.current) window.clearTimeout(wanderTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, mode, stance]);

  // 编辑器可见 → dock（趴在框顶为主）；不可见 → corner；拖拽中不干预
  useEffect(() => {
    if (!enabled || mode === "free") return;
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
      // 默认趴到文本框顶（不打扰写作，符合"平时趴在框上"）
      if (stance === "breath_idle" && Math.random() < 0.7) {
        setStance("perch_top");
      }
    } else {
      setMode("corner");
      setPos(cornerPos());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, mode, editorRef]);

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

  // 拖拽 / 点击
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
    if (d?.moved) {
      const finalPos = { x: clampX(d.originX + (e.clientX - d.startX)), y: clampY(d.originY + (e.clientY - d.startY)) };
      setPos(finalPos);
      setDeskPetPos(finalPos);
      setStance("drop_land");
      window.setTimeout(() => {
        setMode("free");
        setStance("breath_idle");
      }, 320);
    } else {
      // 单击：延迟判定，双击则改为摸头
      if (clickTimer.current) window.clearTimeout(clickTimer.current);
      clickTimer.current = window.setTimeout(() => {
        const pick = CLICK_POOL[Math.floor(Math.random() * CLICK_POOL.length)];
        setStance(pick.stance);
        if (pick.text) say(isLateNight() ? `（深夜）${pick.text}` : pick.text);
        window.setTimeout(() => {
          if (pick.stance !== "breath_idle") setStance("breath_idle");
        }, 600);
      }, 240);
    }
  };
  const onDoubleClick = () => {
    if (clickTimer.current) window.clearTimeout(clickTimer.current);
    setStance("react_cheer");
    say("摸头杀……开心。");
    window.setTimeout(() => setStance("breath_idle"), 700);
  };

  const dockHome = () => {
    setMenuOpen(false);
    setMode("dock");
    setStance("breath_idle");
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
    },
    []
  );

  if (!enabled) return null;

  return (
    <div
      className={`${styles.pet} ${dragging ? styles.dragging : ""}`}
      style={{ left: pos.x, top: pos.y, width: showW }}
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
        title="点击互动 · 双击摸头 · 右键菜单 · 拖动挪位"
      >
        {framesReady ? (
          <img
            key={`${stance}-${frameIdx}`}
            className={styles.frame}
            src={petFrameUrl(spec, frameIdx)}
            alt=""
            draggable={false}
            onError={() => markFrameResult(stance, false)}
            onLoad={() => markFrameResult(stance, true)}
          />
        ) : (
          <PetPlaceholder mood={mood} />
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

function isLateNight(): boolean {
  const h = new Date().getHours();
  return h >= 23 || h < 5;
}
