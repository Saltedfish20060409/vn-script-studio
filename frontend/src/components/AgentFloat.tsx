import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { VnProject } from "../types/vn";
import styles from "./AgentFloat.module.css";

// AgentChat（约 64KB 源码 + 其依赖）静态挂载会拖慢首屏：
// 改为 dynamic import，等用户展开审稿面板时才加载。
// AgentChat 只有具名导出，这里在 import 处适配成 default。
const AgentChat = lazy(() =>
  import("./AgentChat").then((m) => ({ default: m.AgentChat }))
);

type SizeMode = "normal" | "large";
type Edge = "left" | "right" | "top" | "bottom";

type Props = {
  project: VnProject;
  chapterId: string;
  selection: string;
  draft?: string;
  prepareProject: () => VnProject;
  onProjectChange: (p: VnProject) => void;
  onChapterFocus?: (id: string) => void;
  /** 外部"打开"请求：值变化时把面板从任何状态（含贴边收起）拉出来 */
  openRequest?: number;
};

/** v6：可拉伸面板 + 对话侧栏 */
const POS_KEY = "vnss-agent-float-v6";
const EDGE_SNAP = 56;
const PANEL_W = 560;
const PANEL_H = 560;
const MIN_W = 420;
const MIN_H = 360;

type PosState =
  | { mode: "corner" }
  | { mode: "free"; x: number; y: number }
  | { mode: "docked"; edge: Edge; along: number };

function clamp(n: number, min: number, max: number) {
  return Math.min(Math.max(min, n), max);
}

function clampFree(x: number, y: number, w: number, _h: number) {
  return {
    x: clamp(x, 8, Math.max(8, window.innerWidth - Math.min(w, 120))),
    y: clamp(y, 8, Math.max(8, window.innerHeight - 56)),
  };
}

/** During drag allow hugging the edge so snap can trigger */
function clampDrag(x: number, y: number, w: number, h: number) {
  return {
    x: clamp(x, -w + 40, window.innerWidth - 40),
    y: clamp(y, -h + 40, window.innerHeight - 40),
  };
}

function detectEdge(x: number, y: number, w: number, h: number): Edge | null {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const distR = vw - (x + w);
  const distL = x;
  const distT = y;
  const distB = vh - (y + h);
  const nearest = Math.min(distR, distL, distT, distB);
  if (nearest > EDGE_SNAP) return null;
  if (nearest === distR) return "right";
  if (nearest === distL) return "left";
  if (nearest === distT) return "top";
  return "bottom";
}

function alongForEdge(edge: Edge, x: number, y: number, _w: number, _h: number) {
  if (edge === "left" || edge === "right") {
    return clamp(y, 8, Math.max(8, window.innerHeight - 140));
  }
  return clamp(x, 8, Math.max(8, window.innerWidth - 140));
}

export function AgentFloat(props: Props) {
  const { openRequest = 0 } = props;
  const [size, setSize] = useState<SizeMode>("normal");
  const [pos, setPos] = useState<PosState | null>(null);
  const [panelSize, setPanelSize] = useState({ w: PANEL_W, h: PANEL_H });
  const [dragging, setDragging] = useState(false);
  const drag = useRef({ ox: 0, oy: 0, w: PANEL_W, h: PANEL_H });
  const resizeDrag = useRef<{
    startX: number;
    startY: number;
    startW: number;
    startH: number;
  } | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const inited = useRef(false);
  const lastFree = useRef<{ x: number; y: number } | null>(null);
  // 贴边标签交互：点一下=展开；长按 300ms 或按下即拖=进入桌宠式拖动
  // （拖动复用面板的 window 级拖拽，pos 切 free 后按钮卸载也不中断）
  const tabDragStart = useRef<{
    x: number;
    y: number;
    moved: number;
    mode: "pending" | "dragging";
  } | null>(null);
  const tabHoldTimer = useRef<number | null>(null);
  const suppressTabClick = useRef(false);

  useEffect(
    () => () => {
      if (tabHoldTimer.current !== null) window.clearTimeout(tabHoldTimer.current);
    },
    []
  );

  /** 进入拖拽：面板从贴边位置出现，交给 window 级拖拽跟随指针 */
  function beginTabDrag(clientX: number, clientY: number) {
    if (!pos || pos.mode !== "docked") return;
    if (tabHoldTimer.current !== null) {
      window.clearTimeout(tabHoldTimer.current);
      tabHoldTimer.current = null;
    }
    const along = pos.along;
    let px: number;
    let py: number;
    if (pos.edge === "right") {
      px = window.innerWidth - PANEL_W - 16;
      py = clamp(along, 8, Math.max(8, window.innerHeight - PANEL_H - 8));
    } else if (pos.edge === "left") {
      px = 16;
      py = clamp(along, 8, Math.max(8, window.innerHeight - PANEL_H - 8));
    } else if (pos.edge === "top") {
      px = clamp(along, 8, Math.max(8, window.innerWidth - PANEL_W - 8));
      py = 16;
    } else {
      px = clamp(along, 8, Math.max(8, window.innerWidth - PANEL_W - 8));
      py = window.innerHeight - PANEL_H - 16;
    }
    drag.current = { ox: clientX - px, oy: clientY - py, w: PANEL_W, h: PANEL_H };
    lastFree.current = { x: px, y: py };
    setPos({ mode: "free", x: px, y: py });
    if (tabDragStart.current) tabDragStart.current.mode = "dragging";
    setDragging(true);
  }

  function onTabPointerDown(e: React.PointerEvent<HTMLButtonElement>) {
    // 只响应主键按下；悬停/其他键不启动
    if (e.button !== 0 || !pos || pos.mode !== "docked") return;
    e.preventDefault();
    e.stopPropagation();
    tabDragStart.current = { x: e.clientX, y: e.clientY, moved: 0, mode: "pending" };
    suppressTabClick.current = true;
    // 长按 300ms 进入拖拽（点一下不会立即打开）
    tabHoldTimer.current = window.setTimeout(
      () => beginTabDrag(e.clientX, e.clientY),
      300
    );
  }

  function onTabPointerMove(e: React.PointerEvent<HTMLButtonElement>) {
    const d = tabDragStart.current;
    if (!d || e.buttons === 0) return;
    const dist = Math.hypot(e.clientX - d.x, e.clientY - d.y);
    if (dist > d.moved) d.moved = dist;
    // 按下即移动 >4px → 不等长按，立即进入拖拽
    if (d.mode === "pending" && d.moved > 4) {
      beginTabDrag(e.clientX, e.clientY);
    }
  }

  function onTabPointerUp() {
    const d = tabDragStart.current;
    tabDragStart.current = null;
    if (tabHoldTimer.current !== null) {
      window.clearTimeout(tabHoldTimer.current);
      tabHoldTimer.current = null;
    }
    if (!d) return;
    if (d.mode === "pending") {
      // 快速点击（未进入拖拽）：展开
      expandFromDock();
    }
    // mode === "dragging"：由 window 级 onUp 处理贴边判定（长按不展开）
  }

  function onTabClick() {
    if (suppressTabClick.current) {
      suppressTabClick.current = false;
      return;
    }
    expandFromDock();
  }

  useEffect(() => {
    try {
      const narrow = window.innerWidth < 900;
      const raw =
        localStorage.getItem(POS_KEY) || localStorage.getItem("vnss-agent-float-v5");
      if (raw) {
        const p = JSON.parse(raw) as {
          mode?: string;
          x?: number;
          y?: number;
          edge?: Edge;
          along?: number;
          size?: SizeMode | "mini";
          w?: number;
          h?: number;
        };
        if (typeof p.w === "number" && typeof p.h === "number") {
          setPanelSize({
            w: clamp(p.w, MIN_W, Math.max(MIN_W, window.innerWidth - 24)),
            h: clamp(p.h, MIN_H, Math.max(MIN_H, window.innerHeight - 24)),
          });
        }
        // Narrow viewports: keep writing surface visible (agent as edge tab)
        if (narrow && p.mode !== "docked") {
          setSize("normal");
          setPos({ mode: "docked", edge: "right", along: 96 });
          inited.current = true;
          return;
        }
        if (p.size === "large" || p.size === "normal") setSize(p.size);
        if (
          p.mode === "docked" &&
          (p.edge === "left" ||
            p.edge === "right" ||
            p.edge === "top" ||
            p.edge === "bottom")
        ) {
          setPos({
            mode: "docked",
            edge: p.edge,
            along: typeof p.along === "number" ? p.along : 96,
          });
          inited.current = true;
          return;
        }
        if (p.mode === "free" && typeof p.x === "number" && typeof p.y === "number") {
          const c = clampFree(p.x, p.y, PANEL_W, PANEL_H);
          lastFree.current = c;
          setPos({ mode: "free", ...c });
          inited.current = true;
          return;
        }
        if (p.size === "mini") {
          setPos({ mode: "docked", edge: "right", along: 96 });
          inited.current = true;
          return;
        }
      }
      if (narrow) {
        setPos({ mode: "docked", edge: "right", along: 96 });
        inited.current = true;
        return;
      }
    } catch {
      /* ignore */
    }
    setPos({ mode: "corner" });
    inited.current = true;
  }, []);

  useEffect(() => {
    if (!inited.current || !pos) return;
    localStorage.setItem(
      POS_KEY,
      JSON.stringify({ ...pos, size, w: panelSize.w, h: panelSize.h })
    );
  }, [pos, size, panelSize]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const ts = tabDragStart.current;
      if (ts) {
        const dist = Math.hypot(e.clientX - ts.x, e.clientY - ts.y);
        if (dist > ts.moved) ts.moved = dist;
      }
      if (resizeDrag.current) {
        const rd = resizeDrag.current;
        const nextW = clamp(
          rd.startW + (e.clientX - rd.startX),
          MIN_W,
          Math.max(MIN_W, window.innerWidth - 16)
        );
        const nextH = clamp(
          rd.startH + (e.clientY - rd.startY),
          MIN_H,
          Math.max(MIN_H, window.innerHeight - 16)
        );
        setPanelSize({ w: nextW, h: nextH });
        drag.current.w = nextW;
        drag.current.h = nextH;
        return;
      }
      const next = clampDrag(
        e.clientX - drag.current.ox,
        e.clientY - drag.current.oy,
        drag.current.w,
        drag.current.h
      );
      setPos({ mode: "free", ...next });
    };
    const onUp = () => {
      const wasResize = !!resizeDrag.current;
      resizeDrag.current = null;
      setDragging(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      if (wasResize) return;
      // 清理标签拖拽标记（面板自身拖拽时它为空，无影响）
      tabDragStart.current = null;
      const snap = (prev: PosState | null): PosState | null => {
        if (!prev || prev.mode !== "free") return prev;
        const w = drag.current.w;
        const h = drag.current.h;
        const edge = detectEdge(prev.x, prev.y, w, h);
        if (edge) {
          return {
            mode: "docked" as const,
            edge,
            along: alongForEdge(edge, prev.x, prev.y, w, h),
          };
        }
        const c = clampFree(prev.x, prev.y, w, h);
        lastFree.current = c;
        return { mode: "free" as const, ...c };
      };
      // 标签拖拽（长按/按下即拖进入）：仅贴边判定，不展开（长按不打开页面）
      setPos(snap);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragging]);

  function expandFromDock() {
    setSize("normal");
    if (lastFree.current) {
      setPos({ mode: "free", ...lastFree.current });
    } else {
      setPos({ mode: "corner" });
    }
  }

  // 顶栏"审稿"按钮：把面板从任何状态拉出来（防入口丢失/贴边收起后找不到）
  const prevOpenRequest = useRef(0);
  useEffect(() => {
    if (!inited.current) return;
    if (openRequest !== prevOpenRequest.current && openRequest > 0) {
      prevOpenRequest.current = openRequest;
      expandFromDock();
    }
  }, [openRequest]);

  function dockTo(edge: Edge = "right") {
    setPos((prev) => {
      if (prev?.mode === "free") {
        lastFree.current = { x: prev.x, y: prev.y };
        return {
          mode: "docked",
          edge,
          along: alongForEdge(edge, prev.x, prev.y, PANEL_W, PANEL_H),
        };
      }
      return {
        mode: "docked",
        edge,
        along:
          edge === "right" || edge === "left"
            ? Math.max(96, window.innerHeight / 2 - 70)
            : 96,
      };
    });
  }

  if (!pos) return null;

  const large = size === "large";
  const corner = pos.mode === "corner";
  const docked = pos.mode === "docked";
  const nearEdgeHint =
    pos.mode === "free" &&
    detectEdge(
      pos.x,
      pos.y,
      drag.current.w || panelSize.w,
      drag.current.h || panelSize.h
    );

  const sizeStyle =
    large || docked
      ? {}
      : {
          width: `min(${panelSize.w}px, calc(100vw - 24px))`,
          height: `min(${panelSize.h}px, calc(100dvh - 24px))`,
        };

  return (
    <>
      {docked && (
        <button
          type="button"
          className={`${styles.tab} ${styles[`tab_${pos.edge}`]}`}
          style={
            pos.edge === "left" || pos.edge === "right"
              ? { top: pos.along }
              : { left: pos.along }
          }
          onPointerDown={onTabPointerDown}
          onPointerMove={onTabPointerMove}
          onPointerUp={onTabPointerUp}
          onClick={onTabClick}
          title="点击展开 · 可沿边拖动"
        >
          审稿 Agent
        </button>
      )}
      <div
        ref={panelRef}
        className={[
          large ? styles.panelLarge : corner ? styles.panelCorner : styles.panel,
          nearEdgeHint ? styles.panelSnapHint : "",
          dragging ? styles.panelDragging : "",
        ]
          .filter(Boolean)
          .join(" ")}
        style={{
          ...sizeStyle,
          ...(large || corner || docked
            ? {}
            : {
                left: pos.x,
                top: pos.y,
              }),
          ...(docked ? { display: "none" } : {}),
        }}
        aria-hidden={docked || undefined}
        onWheel={(e) => e.stopPropagation()}
      >
        <div
          className={styles.titlebar}
          onPointerDown={(e) => {
            if (large) return;
            const t = e.target as HTMLElement;
            if (t.closest("button")) return;
            e.preventDefault();
            const rect = panelRef.current?.getBoundingClientRect();
            const x = rect?.left ?? e.clientX - 40;
            const y = rect?.top ?? e.clientY - 20;
            const w = rect?.width ?? panelSize.w;
            const h = rect?.height ?? panelSize.h;
            drag.current = {
              ox: e.clientX - x,
              oy: e.clientY - y,
              w,
              h,
            };
            try {
              (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            } catch {
              /* ignore */
            }
            const start = clampDrag(x, y, w, h);
            lastFree.current = clampFree(x, y, w, h);
            setPos({ mode: "free", ...start });
            setDragging(true);
          }}
        >
          <span className={styles.titleIdx} aria-hidden>
            AG
          </span>
          <strong>审稿 Agent</strong>
          <span className={styles.sub}>
            {nearEdgeHint ? "松手贴边收起" : "卷宗 · ⇄ 参谋"}
          </span>
          <div className={styles.winBtns}>
            <button
              type="button"
              onClick={() => {
                setPos({ mode: "corner" });
                setSize("normal");
              }}
              title="回到右下角"
            >
              ↘
            </button>
            <button
              type="button"
              onClick={() => dockTo("right")}
              title="收起到右侧标签"
            >
              —
            </button>
            <button
              type="button"
              onClick={() => {
                if (large) {
                  setSize("normal");
                  setPos({ mode: "corner" });
                } else {
                  setSize("large");
                }
              }}
              title={large ? "还原窗口" : "放大居中"}
            >
              {large ? "❐" : "□"}
            </button>
          </div>
        </div>
        <div className={styles.body}>
          <div className={styles.chatFill}>
            {/* 面板有固定宽高（sizeStyle），fallback 用 null 不会引起布局跳动 */}
            <Suspense fallback={null}>
              <AgentChat
                project={props.project}
                chapterId={props.chapterId}
                selection={props.selection}
                draft={props.draft}
                prepareProject={props.prepareProject}
                onProjectChange={props.onProjectChange}
                onChapterFocus={props.onChapterFocus}
                compact
                hidden={docked}
              />
            </Suspense>
          </div>
        </div>
        {!large && !docked ? (
          <div
            className={styles.resizeHandle}
            title="拖动调整窗口大小"
            onPointerDown={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const rect = panelRef.current?.getBoundingClientRect();
              resizeDrag.current = {
                startX: e.clientX,
                startY: e.clientY,
                startW: rect?.width ?? panelSize.w,
                startH: rect?.height ?? panelSize.h,
              };
              document.body.style.cursor = "nwse-resize";
              document.body.style.userSelect = "none";
              try {
                (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
              } catch {
                /* ignore */
              }
              if (pos.mode === "corner") {
                const r = panelRef.current?.getBoundingClientRect();
                if (r) {
                  setPos({ mode: "free", x: r.left, y: r.top });
                }
              }
              setDragging(true);
            }}
          />
        ) : null}
      </div>
    </>
  );
}
