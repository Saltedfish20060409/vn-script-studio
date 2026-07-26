"use client";

import { useEffect, useRef, useState } from "react";
import type { VnProject } from "@vnss/core";
import { AgentChat } from "./AgentChat";
import styles from "./AgentFloat.module.css";

type SizeMode = "mini" | "normal" | "large";

type Props = {
  project: VnProject;
  chapterId: string;
  selection: string;
  prepareProject: () => VnProject;
  onProjectChange: (p: VnProject) => void;
  onChapterFocus?: (id: string) => void;
  apiConfig?: {
    apiKey?: string;
    apiBaseUrl?: string;
    apiModel?: string;
    craftMode?: "auto" | "off" | "lite" | "full";
    selfReview?: "auto" | "on" | "off";
    criticApiKey?: string;
    criticApiBaseUrl?: string;
    criticApiModel?: string;
  };
};

/** v4：修正布局/拖拽；旧坐标可能把窗拖没，换 key 重置 */
const POS_KEY = "vnss-agent-float-v4";

type PosState =
  | { mode: "corner" }
  | { mode: "free"; x: number; y: number };

function clampPos(
  x: number,
  y: number,
  w: number,
  h: number
): { x: number; y: number } {
  const maxX = Math.max(8, window.innerWidth - Math.min(w, 120));
  const maxY = Math.max(8, window.innerHeight - 56);
  return {
    x: Math.min(Math.max(8, x), maxX),
    y: Math.min(Math.max(8, y), maxY),
  };
}

export function AgentFloat(props: Props) {
  const [size, setSize] = useState<SizeMode>("normal");
  const [pos, setPos] = useState<PosState | null>(null);
  const [dragging, setDragging] = useState(false);
  const drag = useRef({ ox: 0, oy: 0, w: 400 });
  const panelRef = useRef<HTMLDivElement>(null);
  const inited = useRef(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(POS_KEY);
      if (raw) {
        const p = JSON.parse(raw) as {
          mode?: "corner" | "free";
          x?: number;
          y?: number;
          size?: SizeMode;
        };
        if (p.size === "mini" || p.size === "normal" || p.size === "large") {
          setSize(p.size);
        }
        if (
          p.mode === "free" &&
          typeof p.x === "number" &&
          typeof p.y === "number"
        ) {
          const c = clampPos(p.x, p.y, 400, 480);
          setPos({ mode: "free", x: c.x, y: c.y });
          inited.current = true;
          return;
        }
      }
    } catch {
      /* ignore */
    }
    setPos({ mode: "corner" });
    inited.current = true;
  }, []);

  useEffect(() => {
    if (!inited.current || !pos) return;
    localStorage.setItem(POS_KEY, JSON.stringify({ ...pos, size }));
  }, [pos, size]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const next = clampPos(
        e.clientX - drag.current.ox,
        e.clientY - drag.current.oy,
        drag.current.w,
        480
      );
      setPos({ mode: "free", x: next.x, y: next.y });
    };
    const onUp = () => setDragging(false);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragging]);

  if (!pos) return null;

  const large = size === "large";
  const corner = pos.mode === "corner";
  const minimized = size === "mini";

  return (
    <>
      {minimized && (
        <button
          type="button"
          className={styles.tab}
          onClick={() => setSize("normal")}
          title="打开审稿 Agent"
        >
          审稿 Agent
        </button>
      )}
      <div
        ref={panelRef}
        className={
          large
            ? styles.panelLarge
            : corner
              ? styles.panelCorner
              : styles.panel
        }
        style={{
          ...(large || corner
            ? {}
            : {
                left: pos.x,
                top: pos.y,
                width: "min(400px, calc(100vw - 24px))",
                height: "min(520px, calc(100vh - 24px))",
              }),
          ...(minimized ? { display: "none" } : {}),
        }}
        aria-hidden={minimized || undefined}
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
            const w = rect?.width ?? 400;
            drag.current = {
              ox: e.clientX - x,
              oy: e.clientY - y,
              w,
            };
            try {
              (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            } catch {
              /* ignore */
            }
            setPos({ mode: "free", ...clampPos(x, y, w, 480) });
            setDragging(true);
          }}
        >
          <strong>审稿 Agent</strong>
          <span className={styles.sub}>轻小说式编剧顾问</span>
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
              onClick={() => setSize("mini")}
              title="收起为标签（对话保留）"
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
            <AgentChat
              project={props.project}
              chapterId={props.chapterId}
              selection={props.selection}
              prepareProject={props.prepareProject}
              onProjectChange={props.onProjectChange}
              onChapterFocus={props.onChapterFocus}
              compact
              hidden={minimized}
              apiConfig={props.apiConfig}
            />
          </div>
        </div>
      </div>
    </>
  );
}
