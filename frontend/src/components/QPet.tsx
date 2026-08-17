import { useCallback, useEffect, useRef, useState } from "react";
import {
  getDeskPetState,
  setDeskPetEnabled,
  setDeskPetPos,
  subscribeDeskPet,
} from "../lib/deskPet";
import { mascotLine } from "../lib/mascotCopy";
import {
  PET_ANIMATIONS,
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

function dockFromEditorRect(rect: DOMRect): { x: number; y: number } {
  return {
    x: Math.min(rect.right + DOCK_GAP, window.innerWidth - PET_W - 8),
    y: Math.min(rect.bottom - PET_H, window.innerHeight - PET_H - 8),
  };
}

function cornerPos(): { x: number; y: number } {
  return { x: window.innerWidth - PET_W - 16, y: window.innerHeight - PET_H - 16 };
}

type Props = {
  /** 写作编辑器（textarea）ref —— dock 模式的锚点 */
  editorRef?: React.RefObject<HTMLTextAreaElement | null>;
  /** 每次 +1 触发一次「庆祝」（保存/导出成功等外部事件） */
  cheerSignal?: number;
};

/**
 * Q 版桌宠：逐帧动画播放器（美术 PNG 按 docs/mascot-pet-art-brief.md 命名，
 * 缺帧时回退 Q 版占位）+ 编辑器锚定 + 拖拽 + 点击反应。
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
  const dragRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const lineTimer = useRef<number | null>(null);
  const blinkTimer = useRef<number | null>(null);
  const peekTimer = useRef<number | null>(null);
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
          setFrameIdx(spec.stopAt - 1); // 停在指定帧（如 peek 停 03）
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

  // 呼吸中随机眨眼
  useEffect(() => {
    if (!enabled || stance !== "breath_idle") return;
    blinkTimer.current = window.setTimeout(() => {
      setStance("blink");
    }, 2600 + Math.random() * 3400);
    return () => {
      if (blinkTimer.current) window.clearTimeout(blinkTimer.current);
    };
  }, [enabled, stance]);

  // 编辑器可见 → dock；不可见 → corner；free（拖拽）不自动归位
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
      setPos(dockFromEditorRect(rect));
      // 每 9～15s 从框顶探头 / 坐框顶（贴编辑器顶部中线）
      if (!peekTimer.current) {
        peekTimer.current = window.setTimeout(() => {
          peekTimer.current = null;
          const r = editorRef.current?.getBoundingClientRect();
          if (!r || r.width <= 40) return;
          if (Math.random() < 0.6) {
            setStance("peek_over");
            setPos({ x: r.left + r.width / 2 - 48, y: r.top - 56 });
          } else {
            setStance("perch_top");
            setPos({ x: r.left + r.width / 2 - 54, y: r.top - 92 });
          }
        }, 9000 + Math.random() * 6000);
      }
    } else {
      setMode("corner");
      setPos(cornerPos());
    }
    return () => {
      if (peekTimer.current) {
        window.clearTimeout(peekTimer.current);
        peekTimer.current = null;
      }
    };
  }, [enabled, mode, editorRef]);

  // 外部庆祝信号
  useEffect(() => {
    if (cheerSignal !== undefined && cheerSignal !== prevCheer.current) {
      prevCheer.current = cheerSignal;
      if (enabled) {
        setStance("react_cheer");
        say("保存成功，写得漂亮。");
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
      setPos({
        x: Math.max(0, Math.min(d.originX + dx, window.innerWidth - PET_W - 8)),
        y: Math.max(0, Math.min(d.originY + dy, window.innerHeight - PET_H - 8)),
      });
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (d?.moved) {
      const finalPos = {
        x: Math.max(
          0,
          Math.min(d.originX + (e.clientX - d.startX), window.innerWidth - PET_W - 8)
        ),
        y: Math.max(
          0,
          Math.min(d.originY + (e.clientY - d.startY), window.innerHeight - PET_H - 8)
        ),
      };
      setPos(finalPos);
      setDeskPetPos(finalPos);
      setStance("drop_land");
      window.setTimeout(() => {
        setMode("free");
        setStance("breath_idle");
      }, 320);
    } else {
      // 单击：受惊反应 + 气泡
      setStance("react_fluster");
      say(mascotLine("deskPet"));
      window.setTimeout(() => {
        setStance("breath_idle");
      }, 560);
    }
  };

  const dockHome = () => {
    setMenuOpen(false);
    setMode("dock");
    setStance("breath_idle");
    const el = editorRef?.current;
    if (el) setPos(dockFromEditorRect(el.getBoundingClientRect()));
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
      if (blinkTimer.current) window.clearTimeout(blinkTimer.current);
      if (peekTimer.current) window.clearTimeout(peekTimer.current);
    },
    []
  );

  if (!enabled) return null;

  const isPeek = spec.canvas === "B";
  const mood = MOOD_FOR_STANCE[stance];

  return (
    <div
      className={styles.pet}
      style={{ left: pos.x, top: pos.y, width: isPeek ? 96 : PET_W }}
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
        onContextMenu={(e) => {
          e.preventDefault();
          setMenuOpen((v) => !v);
        }}
        title="点击互动 · 右键菜单 · 拖动挪位"
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
