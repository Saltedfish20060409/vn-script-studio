import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { buildDesktopIcons, formatClock, formatClockDate, type DesktopIcon } from "../lib/desktopView";
import {
  clampToViewport,
  closeWindow,
  focusWindow,
  loadLayout,
  minimizeWindow,
  moveWindow,
  openWindow,
  pruneIconPositions,
  resizeWindow,
  saveLayout,
  setIconPosition,
  taskbarWindows,
  type DesktopLayout,
  type WinRect,
} from "../lib/desktopWindows";
import { DesktopWindow } from "./DesktopWindow";
import { MascotFigure } from "./MascotFigure";
import styles from "./DesktopView.module.css";

/** 一个"应用"：桌面图标（可选）+ 开始菜单项（必有）+ 窗口内容 */
export type DesktopApp = {
  id: string;
  label: string;
  glyph: string;
  /** 是否在桌面放快捷方式（系统设置/帮助这类只在开始菜单里，跟 Windows 一致） */
  onDesktop?: boolean;
  /** 窗口内容；不返回就不开窗（例如只做动作的项） */
  render?: () => ReactNode;
  defaultRect?: WinRect;
  /** 打开时先执行的动作（例如公告走弹窗、注销走登出） */
  run?: () => void;
};

type Props = {
  username?: string;
  /** 剧本（桌面上的"文件夹"） */
  projects: Array<{ id: string; title: string }>;
  activeProjectId?: string;
  /** 打开某个剧本：切到"剧本编辑器"窗口（最大化），不是跳走 */
  onOpenProject: (id: string) => void;
  onNewProject: () => void;
  apps: DesktopApp[];
  /** 剧本编辑器窗口是否打开（工作台以"最大化窗口"形式出现） */
  editorOpen: boolean;
  activeProjectTitle?: string;
  onCloseEditor: () => void;
  onEditorMinimize?: () => void;
  /** 切回工作台视图（非桌面形态） */
  onSwitchToStudioView: () => void;
  /** 注销：回到登录页（会重新走过开机画面） */
  onLogout: () => void;
};

const RESERVE_BOTTOM = 46; // 任务栏高度（桌面视图里底部音乐条由「音乐播放器」窗口提供）

/**
 * 桌面视图：图标可拖动、应用开成窗口、任务栏管窗口，剧本编辑器是"最大化窗口"。
 *
 * 与上一版的区别（都是按反馈改的）：窗口是**自己的形态**而不是跳回原界面；
 * 桌面只放"快捷方式"，系统设置/帮助/公告这些进开始菜单；图标与窗口位置会被记住。
 *
 * 边界仍然没变：窄屏自动回工作台（见 shouldShowDesktop），数据模型/编辑器逻辑一行没动。
 */
export function DesktopView({
  username,
  projects,
  activeProjectId,
  onOpenProject,
  onNewProject,
  apps,
  editorOpen,
  activeProjectTitle,
  onCloseEditor,
  onEditorMinimize,
  onSwitchToStudioView,
  onLogout,
}: Props) {
  const [layout, setLayout] = useState<DesktopLayout>(() => loadLayout());
  const [selected, setSelected] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  const dragIcon = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const lastClick = useRef<{ id: string; at: number }>({ id: "", at: 0 });

  const icons = useMemo(() => buildDesktopIcons({ projects, apps }), [projects, apps]);
  const openWins = taskbarWindows(layout);

  // 布局变了就落盘（图标/窗口位置跨刷新保留）
  useEffect(() => {
    saveLayout(layout);
  }, [layout]);

  // 项目被删掉后清掉它的图标位置
  useEffect(() => {
    const live = icons.map((i) => i.id);
    setLayout((cur) => {
      const pruned = pruneIconPositions(cur, live);
      return Object.keys(pruned.icons).length === Object.keys(cur.icons).length ? cur : pruned;
    });
  }, [icons]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  // 图标拖动：跟窗口一样用 pointer 事件，松手吸附到网格
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = dragIcon.current;
      if (!d) return;
      const pos = clampToViewport(e.clientX - d.dx, e.clientY - d.dy, {
        width: window.innerWidth,
        height: window.innerHeight,
        winWidth: 92,
        winHeight: 92,
        reserveBottom: RESERVE_BOTTOM,
      });
      setLayout((cur) => setIconPosition(cur, d.id, pos.x, pos.y));
    };
    const stop = () => {
      dragIcon.current = null;
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, []);

  const openApp = useCallback(
    (id: string) => {
      const app = apps.find((a) => a.id === id);
      if (!app) return;
      app.run?.();
      if (app.render) {
        setLayout((cur) =>
          openWindow(cur, app.id, app.defaultRect ?? { x: 90, y: 70, w: 520, h: 420 })
        );
      }
    },
    [apps]
  );

  function openIcon(icon: DesktopIcon) {
    if (icon.kind === "project") {
      onOpenProject(icon.id.slice("project:".length));
      return;
    }
    const appId = icon.id.slice("action:".length);
    if (appId === "new") {
      onNewProject();
      return;
    }
    openApp(appId);
  }

  function handleIconClick(icon: DesktopIcon) {
    const t = Date.now();
    const isDouble = lastClick.current.id === icon.id && t - lastClick.current.at < 400;
    lastClick.current = { id: icon.id, at: t };
    setSelected(icon.id);
    if (isDouble) openIcon(icon);
  }

  const selectedHint = icons.find((i) => i.id === selected)?.hint ?? "双击图标打开；拖动可以摆放位置";

  return (
    <div
      className={styles.desktop}
      data-testid="desktop-view"
      onPointerDown={(e) => {
        if (e.target === e.currentTarget || (e.target as HTMLElement).dataset.blank === "1") {
          setMenuOpen(false);
          setSelected(null);
        }
      }}
    >
      {/* 图标与暗角只在"没有最大化窗口"时出现 —— 否则会浮在工作台上面 */}
      {!editorOpen ? <div className={styles.dim} aria-hidden data-blank="1" /> : null}

      {/* 桌面图标：项目（文件夹）+ 用户放上来的应用快捷方式 */}
      {!editorOpen ? (
        <div
          className={styles.iconArea}
          role="list"
          aria-label="桌面图标"
          style={{ paddingBottom: RESERVE_BOTTOM + 3.4 * 16 }}
        >
          {icons.map((icon, index) => {
            const saved = layout.icons[icon.id];
            // 没记录位置的按默认网格排：一行几个，向下增长
            const fallback = { x: 16 + Math.floor(index / 6) * 100, y: 16 + (index % 6) * 96 };
            const pos = saved ?? fallback;
            return (
              <button
                key={icon.id}
                type="button"
                role="listitem"
                className={`${styles.icon} ${selected === icon.id ? styles.iconOn : ""} ${
                  icon.id === `project:${activeProjectId}` ? styles.iconActive : ""
                }`}
                style={{ left: pos.x, top: pos.y }}
                onClick={() => handleIconClick(icon)}
                onDoubleClick={() => openIcon(icon)}
                onPointerDown={(e) => {
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  dragIcon.current = { id: icon.id, dx: e.clientX - r.left, dy: e.clientY - r.top };
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    openIcon(icon);
                  }
                }}
                title={icon.hint}
              >
                <span className={styles.glyph} aria-hidden>
                  {icon.glyph}
                </span>
                <span className={styles.label}>{icon.label}</span>
              </button>
            );
          })}
        </div>
      ) : null}

      {/* 剧本编辑器：以"最大化窗口"的形式出现（自己的标题栏 + 最小化/关闭），不跳走。
          工作台本体由 StudioApp 渲染在下面这一层（见 .shellUnderDesktop），
          它的高度/边距正好让开这条标题栏与任务栏。 */}
      {editorOpen ? (
        <div className={styles.editorFrame} data-testid="desktop-editor">
          <header className={styles.editorBar}>
            <span aria-hidden>✍️</span>
            <span className={styles.editorTitle}>
              剧本编辑器{activeProjectTitle ? ` — ${activeProjectTitle}` : ""}
            </span>
            <div className={styles.editorButtons}>
              <button type="button" onClick={onEditorMinimize} title="最小化到任务栏">
                —
              </button>
              <button type="button" onClick={onCloseEditor} title="关闭">
                ✕
              </button>
            </div>
          </header>
        </div>
      ) : null}

      {/* 应用窗口 */}
      {openWins.map((win) => {
        const app = apps.find((a) => a.id === win.id);
        if (!app?.render || win.minimized) return null;
        return (
          <DesktopWindow
            key={win.id}
            win={win}
            title={app.label}
            glyph={app.glyph}
            reserveBottom={RESERVE_BOTTOM}
            onFocus={() => setLayout((cur) => focusWindow(cur, win.id))}
            onMove={(x, y) => setLayout((cur) => moveWindow(cur, win.id, x, y))}
            onResize={(w, h) => setLayout((cur) => resizeWindow(cur, win.id, w, h))}
            onMinimize={() => setLayout((cur) => minimizeWindow(cur, win.id))}
            onClose={() => setLayout((cur) => closeWindow(cur, win.id))}
          >
            {app.render()}
          </DesktopWindow>
        );
      })}

      {/* 任务栏 */}
      <div className={styles.taskbar}>        <button
          type="button"
          className={menuOpen ? `${styles.start} ${styles.startOn}` : styles.start}
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
        >
          <MascotFigure size="xs" />
          <span>开始</span>
        </button>

        {menuOpen ? (
          <div className={styles.menu} role="menu">
            <p className={styles.menuGroup}>应用</p>
            {apps.map((app) => (
              <button
                key={app.id}
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  if (app.render) openApp(app.id);
                  else app.run?.();
                }}
              >
                {app.glyph} {app.label}
              </button>
            ))}
            <p className={styles.menuGroup}>系统</p>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onSwitchToStudioView();
              }}
            >
              🖥️ 切换为工作台视图
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onLogout();
              }}
            >
              ⏏️ 注销（回到开机界面）
            </button>
          </div>
        ) : null}

        {/* 已打开窗口 = 任务栏按钮（点一下切换/还原） */}
        <div className={styles.tasks}>
          {editorOpen ? (
            <button
              type="button"
              className={styles.task}
              onClick={() => (editorOpen ? onEditorMinimize?.() : undefined)}
              title="剧本编辑器"
            >
              ✍️ 剧本编辑器
            </button>
          ) : null}
          {openWins.map((win) => {
            const app = apps.find((a) => a.id === win.id);
            if (!app?.render) return null;
            return (
              <button
                key={win.id}
                type="button"
                className={win.minimized ? styles.task : `${styles.task} ${styles.taskOn}`}
                onClick={() =>
                  setLayout((cur) =>
                    win.minimized ? focusWindow(cur, win.id) : minimizeWindow(cur, win.id)
                  )
                }
              >
                {app.glyph} {app.label}
              </button>
            );
          })}
        </div>

        <span className={styles.clock}>
          <strong>{formatClock(now)}</strong>
          <small>{formatClockDate(now)}</small>
        </span>
        <span className={styles.user} title={username ? `已登录：${username}` : undefined}>
          {username ?? ""}
        </span>
      </div>

      <span className={styles.hintBar} style={{ opacity: editorOpen ? 0 : 1 }}>
        {selectedHint}
      </span>
    </div>
  );
}
