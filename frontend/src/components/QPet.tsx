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
  PET_CANVAS,
  petFrameUrl,
  type PetActionId,
} from "../lib/petAnimations";
import type { MascotMood } from "./MascotFigure";
import { PetPlaceholder } from "./PetPlaceholder";
import styles from "./QPet.module.css";

type PetMode = "dock" | "corner" | "free" | "edge-left" | "edge-right";

const PET_W = 120;
const PET_H = 168;
const DOCK_GAP = 10;
/** 无交互多久触发打瞌睡（至少 3 分钟） */
const SLEEP_AFTER_MS = 3 * 60 * 1000;

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

/** 原地小动作池（占位阶段也有动画/表情） */
const MINI_ACTIONS: PetActionId[] = [
  "react_cheer", // 跳一下
  "read_over_shoulder", // 张望
  "hide_corner", // 坐下蜷
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

/** 姿态 → 编辑器对齐位置（到达框边目标时用） */
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

/** 自由游走目标：普通游走保持当前高度（纯水平）；框边目标（趴框顶/
 *  站两侧/探头）需要改变高度时才斜向移动。编辑器可见时偏好框边。 */
function pickTarget(
  editorRef: React.RefObject<HTMLTextAreaElement | null> | undefined,
  from: { x: number; y: number }
): { x: number; y: number; onArrive: "perch" | "peek" | "stand" } {
  const vw = window.innerWidth;
  const targets: Array<{ x: number; y: number; onArrive: "perch" | "peek" | "stand" }> = [];
  const el = editorRef?.current;
  const r = el ? el.getBoundingClientRect() : null;
  if (r && r.width > 40) {
    targets.push({
      x: clampX(r.left + r.width / 2 - PET_W / 2),
      y: clampY(r.top - 96),
      onArrive: "perch",
    }); // 趴框顶（斜向上去）
    targets.push({
      x: clampX(r.right + DOCK_GAP),
      y: clampY(r.bottom - PET_H),
      onArrive: "stand",
    }); // 框右侧
    targets.push({
      x: clampX(r.left - PET_W - 10),
      y: clampY(r.bottom - PET_H),
      onArrive: "stand",
    }); // 框左侧
    targets.push({
      x: clampX(r.left + r.width / 2 - 48, 96),
      y: clampY(r.top - 56, 96),
      onArrive: "peek",
    }); // 框顶探头（斜向上去）
  }
  // 普通游走：保持当前高度 → 纯水平移动
  targets.push({
    x: clampX(vw * (0.08 + Math.random() * 0.84)),
    y: from.y,
    onArrive: "stand",
  });
  targets.push({
    x: clampX(vw * (0.08 + Math.random() * 0.84)),
    y: from.y,
    onArrive: "stand",
  });
  return targets[Math.floor(Math.random() * targets.length)];
}

type Props = {
  editorRef?: React.RefObject<HTMLTextAreaElement | null>;
  cheerSignal?: number;
};

/** Q 版桌宠：像桌宠模拟器一样在屏幕上自由游走 —— 随机走向各处、
 *  停停走走、做小动作、被戳有反应、可拖拽、会打瞌睡。 */
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
  const [behaviorTick, setBehaviorTick] = useState(0);
  const [eyePos, setEyePos] = useState({ x: 0, y: 0 });
  const posRef = useRef(pos);
  const stanceRef = useRef(stance);
  useEffect(() => {
    posRef.current = pos;
    stanceRef.current = stance;
  }, [pos, stance]);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const prevEnabledRef = useRef(getDeskPetState().enabled);
  const lineTimer = useRef<number | null>(null);
  const blinkTimer = useRef<number | null>(null);
  const behaviorTimer = useRef<number | null>(null);
  const clickTimer = useRef<number | null>(null);
  const moveTimer = useRef<number | null>(null);
  const segTimers = useRef<number[]>([]);
  const sleepTimer = useRef<number | null>(null);
  const lastActivityRef = useRef(Date.now());
  const prevCheer = useRef(cheerSignal ?? 0);
  /** 走位/行为进行中：防止重复调度 */
  const wanderingRef = useRef(false);

  // 设置开关同步：只在「关→开」时归位
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

  // 呼吸时随机眨眼
  useEffect(() => {
    if (!enabled || stance !== "breath_idle") return;
    blinkTimer.current = window.setTimeout(() => {
      setStance("blink");
    }, 2600 + Math.random() * 3600);
    return () => {
      if (blinkTimer.current) window.clearTimeout(blinkTimer.current);
    };
  }, [enabled, stance]);

  // 占位眼珠跟随鼠标：让 Q 版小人更「活」
  useEffect(() => {
    if (!enabled) return;
    const onMove = (e: MouseEvent) => {
      const p = posRef.current;
      const cx = p.x + showW / 2;
      const cy = p.y + 60;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const dist = Math.max(1, Math.abs(dx) + Math.abs(dy));
      const k = Math.min(1, 40 / dist); // 距离越近看得越“聚”
      setEyePos({
        x: Math.max(-4, Math.min(4, (dx / dist) * 4 * k)),
        y: Math.max(-4, Math.min(4, (dy / dist) * 4 * k)),
      });
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [enabled, showW]);

  // 行为循环：像桌宠模拟器一样自由活动 —— 每 8~20s 随机决定
  // 「走向某处 / 原地小动作 / 待机呼吸」。free（拖放摆放）与 edge 不活动。
  useEffect(() => {
    if (!enabled || isEdge || dragging || wanderingRef.current) return;
    if (mode === "free") return; // 拖到哪停哪，尊重摆放
    if (stanceRef.current === "fall_asleep") return; // 睡着（wakeUp 恢复）
    behaviorTimer.current = window.setTimeout(
      () => {
        const roll = Math.random();
        if (roll < 0.5) {
          // 走向目标（普通目标纯水平；框边目标平滑斜向）
          const from = posRef.current;
          const target = pickTarget(editorRef, from);
          const dx = target.x - from.x;
          setWalkDir(dx < -4 ? -1 : 1);
          wanderingRef.current = true;
          setStance("walk_side_r");

          const finish = () => {
            wanderingRef.current = false;
            setMoveMs(1500);
            setStance(
              target.onArrive === "perch"
                ? "perch_top"
                : target.onArrive === "peek"
                  ? "peek_over"
                  : "breath_idle"
            );
            setBehaviorTick((t) => t + 1); // 调度下一个行为
          };

          if (Math.abs(dx) < 8) {
            // 几乎没水平位移：直接平滑过渡到位（x、y 一起）
            setMoveMs(800);
            setPos({ x: target.x, y: target.y });
            moveTimer.current = window.setTimeout(finish, 1000);
            return;
          }

          // 分小段走（每小段 ≤ 屏 1/24，走 950ms + 停 450ms）：
          // x、y 都按比例分摊进每一段 → 平滑斜向，不会「走完突然纵跳」
          const seg = Math.max(36, window.innerWidth / 24);
          const n = Math.max(2, Math.ceil(Math.abs(dx) / seg));
          const stepMs = 950;
          const pauseMs = 450;
          const dy = target.y - from.y;
          for (let i = 1; i <= n; i++) {
            const timer = window.setTimeout(() => {
              setMoveMs(stepMs);
              setPos({
                x: from.x + (dx * i) / n,
                y: from.y + (dy * i) / n,
              });
            }, (i - 1) * (stepMs + pauseMs));
            segTimers.current.push(timer);
          }
          moveTimer.current = window.setTimeout(
            finish,
            n * (stepMs + pauseMs) + 200
          );
        } else if (roll < 0.75) {
          // 原地小动作（跳一下 / 张望 / 坐下蜷），2.5s 后回呼吸
          const act = MINI_ACTIONS[Math.floor(Math.random() * MINI_ACTIONS.length)];
          setStance(act);
          moveTimer.current = window.setTimeout(() => {
            setStance("breath_idle");
            setBehaviorTick((t) => t + 1);
          }, 2500);
        } else {
          // 待机呼吸（静静站一会儿）
          setStance("breath_idle");
          setBehaviorTick((t) => t + 1);
        }
      },
      8000 + Math.random() * 12000
    );
    return () => {
      if (behaviorTimer.current) window.clearTimeout(behaviorTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, mode, isEdge, dragging, behaviorTick]);

  // 编辑器可见 → dock（行为目标偏框边）；不可见 → corner（自由游走）
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
      if (mode !== "dock") setBehaviorTick((t) => t + 1); // 进入写作页后尽快活动
      setMode("dock");
    } else {
      setMode("corner");
    }
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

  // 打瞌睡：≥3 分钟【不与桌宠交互】触发，睡着时长随机（45~120s）
  const wakeUp = useCallback(
    (withLine: boolean) => {
      if (sleepTimer.current) window.clearTimeout(sleepTimer.current);
      sleepTimer.current = null;
      setStance("breath_idle");
      setBehaviorTick((t) => t + 1); // 睡醒恢复行为循环
      if (withLine) say("（揉揉眼睛）我睡着了吗？……嗯，醒了。");
    },
    [say]
  );

  const bumpPetActivity = useCallback(() => {
    lastActivityRef.current = Date.now();
    if (stanceRef.current === "fall_asleep") wakeUp(false);
  }, [wakeUp]);

  useEffect(() => {
    if (!enabled) return;
    const check = () => {
      if (stance === "fall_asleep") return; // 已在睡
      if (isEdge || dragging || wanderingRef.current) return;
      const idleMs = Date.now() - lastActivityRef.current;
      if (idleMs >= SLEEP_AFTER_MS) {
        setStance("fall_asleep");
        const sleepMs = 45000 + Math.random() * 75000; // 45~120s 随机
        sleepTimer.current = window.setTimeout(() => wakeUp(true), sleepMs);
      }
    };
    const t = window.setInterval(check, 15000);
    return () => window.clearInterval(t);
  }, [enabled, stance, isEdge, dragging, wakeUp]);

  // 菜单打开时：点菜单外任意处关闭（菜单内按钮 stopPropagation 不受影响）
  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [menuOpen]);

  // 拖拽 / 点击 / 贴边
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    bumpPetActivity();
    // 打断进行中的走位/小动作
    wanderingRef.current = false;
    segTimers.current.forEach((t) => window.clearTimeout(t));
    segTimers.current = [];
    if (moveTimer.current) window.clearTimeout(moveTimer.current);
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
      // 1) 贴屏幕边缘 → 吸附成「探出头」
      const vw = window.innerWidth;
      if (finalPos.x <= 6) {
        setMode("edge-left");
        setStance("peek_side_r");
        setPos({ x: -showW * 0.55, y: finalPos.y });
        setDeskPetPos({ x: -showW * 0.55, y: finalPos.y });
        return;
      }
      if (finalPos.x >= vw - showW - 6) {
        setMode("edge-right");
        setStance("peek_side_r");
        setPos({ x: vw - showW * 0.45, y: finalPos.y });
        setDeskPetPos({ x: vw - showW * 0.45, y: finalPos.y });
        return;
      }
      // 2) 拖到文本框上沿/框后 → 触发姿态；水平位置跟随落点
      const el = editorRef?.current;
      const r = el ? el.getBoundingClientRect() : null;
      const inView = r && r.width > 40;
      if (inView) {
        const overlapX =
          finalPos.x > r.left - 40 && finalPos.x < r.right + 40 - showW;
        const onTop = Math.abs(finalPos.y - r.top) < 60;
        const behind =
          finalPos.y >= r.top - 130 && finalPos.y <= r.top + 60;
        const nearRight =
          Math.abs(finalPos.x - r.right) < 130 &&
          finalPos.y > r.top - 80 &&
          finalPos.y < r.bottom + 80;
        if (overlapX && onTop) {
          const s = PET_ANIMATIONS.perch_top;
          const c = PET_CANVAS[s.canvas];
          const h = (PET_W / c.w) * c.h;
          const ratio = (s.anchor?.sit_contact?.y ?? c.h / 2) / c.h;
          const p = { x: clampX(finalPos.x), y: clampY(r.top - h * ratio) };
          setMode("dock");
          setStance("perch_top");
          setPos(p);
          setDeskPetPos(p);
          say("那我趴这儿陪你写。");
          return;
        }
        if (overlapX && behind) {
          const p = { x: clampX(finalPos.x, 96), y: clampY(r.top - 56, 96) };
          setMode("dock");
          setStance("peek_over");
          setPos(p);
          setDeskPetPos(p);
          say("躲在这儿偷看你写……");
          return;
        }
        if (nearRight) {
          const p = dockFromEditorRect(r);
          setMode("dock");
          setStance("breath_idle");
          setPos(p);
          setDeskPetPos(p);
          return;
        }
      }
      // 3) 其他位置 → 自由停留（拖到哪停在哪）
      setPos(finalPos);
      setDeskPetPos(finalPos);
      setStance("drop_land");
      window.setTimeout(() => {
        setStance("breath_idle");
      }, 320);
      return;
    }
    // 单击
    if (clickTimer.current) window.clearTimeout(clickTimer.current);
    clickTimer.current = window.setTimeout(() => {
      if (stance === "fall_asleep") {
        wakeUp(true);
        return;
      }
      if (isEdge) {
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
    bumpPetActivity();
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
    setBehaviorTick((t) => t + 1); // 立即恢复行为循环
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
      if (blinkTimer.current) window.clearTimeout(blinkTimer.current);
      if (behaviorTimer.current) window.clearTimeout(behaviorTimer.current);
      if (clickTimer.current) window.clearTimeout(clickTimer.current);
      if (moveTimer.current) window.clearTimeout(moveTimer.current);
      if (sleepTimer.current) window.clearTimeout(sleepTimer.current);
      segTimers.current.forEach((t) => window.clearTimeout(t));
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
          bumpPetActivity();
          setMenuOpen((v) => !v);
        }}
        title="点击互动 · 双击摸头 · 拖到框边/屏幕边缘 · 右键菜单"
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
          <div className={animClass} style={{ transform: `scaleX(${flip})` }}>
            <PetPlaceholder mood={mood} eyeX={eyePos.x} eyeY={eyePos.y} />
          </div>
        )}
      </div>
      {menuOpen && (
        <div
          className={styles.menu}
          onPointerDown={(e) => e.stopPropagation()}
        >
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
    case "read_over_shoulder":
      return styles.petLean;
    default:
      return "";
  }
}

function isLateNight(): boolean {
  const h = new Date().getHours();
  return h >= 23 || h < 5;
}
