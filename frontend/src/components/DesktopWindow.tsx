import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { clampToViewport, type WinState } from "../lib/desktopWindows";
import styles from "./DesktopWindow.module.css";

type Props = {
  win: WinState;
  title: string;
  glyph?: string;
  children: ReactNode;
  onFocus: () => void;
  onMove: (x: number, y: number) => void;
  onResize: (w: number, h: number) => void;
  onMinimize: () => void;
  onClose: () => void;
  /** 任务栏高度 + 音乐条预留：窗口不能拖到被它们盖住的地方 */
  reserveBottom?: number;
};

const MIN_W = 320;
const MIN_H = 220;

/**
 * 桌面窗口：标题栏可拖动、可最小化/关闭、点哪抬哪。
 *
 * 只负责"外壳与几何"——窗口里放什么由调用方决定（系统设置、Agent、音乐…）。
 * 拖动用 pointer 事件 + setPointerCapture，触屏和鼠标都能用；
 * 松手时把坐标夹回可视区，避免拖出屏幕找不回来。
 */
export function DesktopWindow({
  win,
  title,
  glyph,
  children,
  onFocus,
  onMove,
  onResize,
  onMinimize,
  onClose,
  reserveBottom = 0,
}: Props) {
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeRef = useRef<{ sx: number; sy: number; w: number; h: number } | null>(null);

  const clamp = useCallback(
    (x: number, y: number) =>
      clampToViewport(x, y, {
        width: window.innerWidth,
        height: window.innerHeight,
        winWidth: win.w,
        winHeight: win.h,
        reserveBottom,
      }),
    [win.w, win.h, reserveBottom]
  );

  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      if (dragRef.current) {
        const { x, y } = clamp(e.clientX - dragRef.current.dx, e.clientY - dragRef.current.dy);
        onMove(x, y);
        return;
      }
      if (resizeRef.current) {
        const next = {
          w: Math.max(MIN_W, resizeRef.current.w + (e.clientX - resizeRef.current.sx)),
          h: Math.max(MIN_H, resizeRef.current.h + (e.clientY - resizeRef.current.sy)),
        };
        onResize(next.w, next.h);
      }
    };
    const stop = () => {
      dragRef.current = null;
      resizeRef.current = null;
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, [clamp, onMove, onResize]);

  const rect = win.maximized
    ? { left: 0, top: 0, width: "100%", height: `calc(100% - ${reserveBottom}px)` }
    : { left: win.x, top: win.y, width: win.w, height: win.h };

  return (
    <section
      className={styles.win}
      style={{ ...rect, zIndex: win.z }}
      aria-label={title}
      onPointerDown={onFocus}
      data-testid={`desktop-window-${win.id}`}
    >
      <header
        className={styles.titleBar}
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest("button")) return;
          dragRef.current = { dx: e.clientX - win.x, dy: e.clientY - win.y };
        }}
        onDoubleClick={() => onMinimize()}
      >
        {glyph ? (
          <span className={styles.glyph} aria-hidden>
            {glyph}
          </span>
        ) : null}
        <span className={styles.title}>{title}</span>
        <div className={styles.buttons}>
          <button type="button" onClick={onMinimize} title="最小化" aria-label={`最小化 ${title}`}>
            —
          </button>
          <button type="button" onClick={onClose} title="关闭" aria-label={`关闭 ${title}`}>
            ✕
          </button>
        </div>
      </header>
      <div className={styles.body}>{children}</div>
      {!win.maximized ? (
        <span
          className={styles.resizer}
          aria-hidden
          onPointerDown={(e) => {
            resizeRef.current = { sx: e.clientX, sy: e.clientY, w: win.w, h: win.h };
          }}
        />
      ) : null}
    </section>
  );
}
