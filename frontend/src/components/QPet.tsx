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

/** 散步目标：水平带内随机点（像走路一样主要沿左右移动，不做对角线大跳）。
 *  底部带 / 中部带 始终可选；编辑器可见时加「框顶带」（在文本框上走动）。 */
function walkTarget(editorRef?: React.RefObject<HTMLTextAreaElement | null>): {
  x: number;
  y: number;
  stance: PetActionId;
} {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const bands: Array<{
    y: number;
    xMin: number;
    xMax: number;
    stance: PetActionId;
  }> = [
    {
      y: clampY(vh - PET_H - 24),
      xMin: 12,
      xMax: vw - PET_W - 20,
      stance: "breath_idle",
    }, // 页面底部沿
    {
      y: clampY(vh * 0.55),
      xMin: 12,
      xMax: vw - PET_W - 20,
      stance: "breath_idle",
    }, // 页面中部带
  ];
  const el = editorRef?.current;
  if (el) {
    const r = el.getBoundingClientRect();
    if (r.width > 40) {
      bands.push({
        y: clampY(r.top - 96),
        xMin: Math.max(0, r.left - 24),
        xMax: Math.min(vw - PET_W, r.right - PET_W + 24),
        stance: "perch_top",
      }); // 文本框顶带（在上沿来回走）
    }
  }
  const band = bands[Math.floor(Math.random() * bands.length)];
  const span = Math.max(1, band.xMax - band.xMin);
  return {
    x: clampX(band.xMin + Math.random() * span),
    y: band.y,
    stance: band.stance,
  };
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
  const [wanderTick, setWanderTick] = useState(0);
  const posRef = useRef(pos);
  const stanceRef = useRef(stance);
  useEffect(() => {
    stanceRef.current = stance;
  }, [stance]);
  useEffect(() => {
    posRef.current = pos;
  }, [pos]);
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
  const segTimers = useRef<number[]>([]);
  const sleepTimer = useRef<number | null>(null);
  const lastActivityRef = useRef(Date.now());
  const prevCheer = useRef(cheerSignal ?? 0);
  /** 散步进行中：跳过「姿态→dock 位置」联动，否则位置会被拉回编辑器旁 */
  const wanderingRef = useRef(false);
  /** 手动拖放到框边后的一次性抑制：防止姿态联动把落点居中拉走 */
  const suppressDockSyncRef = useRef(false);

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

  // 姿态 → dock 位置联动（散步中、手动拖放后的一次触发内跳过）
  useEffect(() => {
    if (mode !== "dock" || !enabled || wanderingRef.current) return;
    if (suppressDockSyncRef.current) {
      suppressDockSyncRef.current = false; // 消费一次性抑制
      return;
    }
    const el = editorRef?.current;
    if (!el) return;
    setPos(dockPosFor(stance, el.getBoundingClientRect()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stance, mode, enabled]);

  // 多套待机不规律切换（edge 模式保持探头；散步/睡眠中不打断）
  useEffect(() => {
    if (!enabled || isEdge || wanderingRef.current) return;
    if (stance === "fall_asleep") return; // 睡着时不切待机
    idleTimer.current = window.setTimeout(() => {
      const pool = mode === "dock" ? IDLE_POOL_DOCK : IDLE_POOL_CORNER;
      const next = pool[Math.floor(Math.random() * pool.length)];
      setStance(next);
    }, 5000 + Math.random() * 7000);
    return () => {
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
    };
  }, [enabled, mode, stance, isEdge]);

  // 一段时间后散步：水平分段行走（走走停停，像走路而非瞬移）
  // 注意：依赖里【不能有 stance】—— idleCycle 每 5~12s 切一次待机，
  // 若依赖 stance 会让散步定时器被反复重置而永远不触发。睡眠检查用
  // stanceRef 读取当前姿态。
  useEffect(() => {
    if (!enabled || mode === "free" || isEdge || wanderingRef.current) return;
    if (stanceRef.current === "fall_asleep") {
      return; // 睡着：暂停散步（睡醒时 wakeUp 会 +1 tick 恢复调度）
    }
    wanderTimer.current = window.setTimeout(
      () => {
        const target = walkTarget(editorRef);
        const from = posRef.current;
        const dx = target.x - from.x;
        setWalkDir(dx < -4 ? -1 : 1); // 目标在左 → 朝左走（镜像）
        wanderingRef.current = true;
        setStance("walk_side_r");

        const finish = () => {
          wanderingRef.current = false;
          setMoveMs(1500);
          suppressDockSyncRef.current = true; // 保留散步终点，不被联动拉回
          setStance(target.stance);
          setWanderTick((t) => t + 1); // 调度下一次散步
        };

        if (Math.abs(dx) < 8) {
          // 几乎没水平位移 → 只做短促垂直微调
          setMoveMs(700);
          setPos({ x: target.x, y: target.y });
          moveTimer.current = window.setTimeout(finish, 900);
          return;
        }

        // 水平分 N 段走：每段 850ms 过渡 + 220ms 停顿 → 步伐感
        const seg = 170;
        const n = Math.max(1, Math.ceil(Math.abs(dx) / seg));
        const stepMs = 850;
        const pauseMs = 220;
        for (let i = 1; i <= n; i++) {
          const timer = window.setTimeout(() => {
            setMoveMs(stepMs);
            setPos({ x: from.x + (dx * i) / n, y: from.y });
          }, (i - 1) * (stepMs + pauseMs));
          segTimers.current.push(timer);
        }
        // 水平走完后，垂直短促微调到位
        const horizEnd = n * (stepMs + pauseMs) + 120;
        moveTimer.current = window.setTimeout(() => {
          setMoveMs(650);
          setPos({ x: target.x, y: target.y });
          moveTimer.current = window.setTimeout(finish, 850);
        }, horizEnd);
      },
      12000 + Math.random() * 16000
    );
    return () => {
      if (wanderTimer.current) window.clearTimeout(wanderTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, mode, isEdge, wanderTick]);

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

  // 打瞌睡：较长时间【不与桌宠交互】触发（≥3 分钟），睡着时长随机（45~120s）。
  // 页面活动（写稿/滚动）不算——只有点击/拖拽/双击/右键桌宠才刷新计时。
  const wakeUp = useCallback(
    (withLine: boolean) => {
      if (sleepTimer.current) window.clearTimeout(sleepTimer.current);
      sleepTimer.current = null;
      setStance("breath_idle");
      setWanderTick((t) => t + 1); // 睡醒恢复散步调度
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

  // 拖拽 / 点击 / 贴边
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    bumpPetActivity(); // 与桌宠的交互 → 刷新无交互计时
    // 打断进行中的散步
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
      // 2) 拖到文本框上沿/框后 → 触发姿态；水平位置跟随落点，不强制居中
      const el = editorRef?.current;
      const r = el ? el.getBoundingClientRect() : null;
      const inView = r && r.width > 40;
      if (inView) {
        const overlapX =
          finalPos.x > r.left - 40 && finalPos.x < r.right + 40 - showW;
        const onTop = Math.abs(finalPos.y - r.top) < 60; // 紧贴框顶
        const behind =
          finalPos.y >= r.top - 130 && finalPos.y <= r.top + 60; // 框上/框后
        const nearRight =
          Math.abs(finalPos.x - r.right) < 130 &&
          finalPos.y > r.top - 80 &&
          finalPos.y < r.bottom + 80;
        if (overlapX && onTop) {
          // 趴在框顶：x 保持落点（拖到哪趴哪）
          const s = PET_ANIMATIONS.perch_top;
          const c = PET_CANVAS[s.canvas];
          const h = (PET_W / c.w) * c.h;
          const ratio = (s.anchor?.sit_contact?.y ?? c.h / 2) / c.h;
          const p = { x: clampX(finalPos.x), y: clampY(r.top - h * ratio) };
          suppressDockSyncRef.current = true;
          setMode("dock");
          setStance("perch_top");
          setPos(p);
          setDeskPetPos(p);
          say("那我趴这儿陪你写。");
          return;
        }
        if (overlapX && behind) {
          // 躲在框后探头：x 保持落点
          const p = { x: clampX(finalPos.x, 96), y: clampY(r.top - 56, 96) };
          suppressDockSyncRef.current = true;
          setMode("dock");
          setStance("peek_over");
          setPos(p);
          setDeskPetPos(p);
          say("躲在这儿偷看你写……");
          return;
        }
        if (nearRight) {
          // 明确拖到右侧附近 → 站回编辑器旁
          const p = dockFromEditorRect(r);
          suppressDockSyncRef.current = true;
          setMode("dock");
          setStance("breath_idle");
          setPos(p);
          setDeskPetPos(p);
          return;
        }
      }
      // 3) 其他位置 → 自由停留（位置持久化，拖到哪停在哪）
      setPos(finalPos);
      setDeskPetPos(finalPos);
      setStance("drop_land");
      window.setTimeout(() => {
        setMode("free");
        setStance("breath_idle");
      }, 320);
      return;
    }
    // 单击
    if (clickTimer.current) window.clearTimeout(clickTimer.current);
    clickTimer.current = window.setTimeout(() => {
      if (stance === "fall_asleep") {
        // 点睡着的桌宠 → 直接唤醒
        wakeUp(true);
        return;
      }
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
