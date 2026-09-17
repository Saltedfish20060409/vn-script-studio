import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  DESKTOP_TIPS,
  buildDesktopIcons,
  formatClock,
  formatClockDate,
  markDesktopTipsSeen,
  shouldShowDesktopTips,
  type DesktopIcon,
} from "../lib/desktopView";
import {
  assignIconSlot,
  closeWindow,
  focusWindow,
  loadLayout,
  minimizeWindow,
  moveWindow,
  nearestSlot,
  nextIconInDirection,
  openWindow,
  pruneIconPositions,
  resizeWindow,
  resolveIconSlots,
  saveLayout,
  slotToPosition,
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
  /** 剧本（桌面上的"文件夹"）：带章数与最后修改时间，图标上直接显示进度 */
  projects: Array<{ id: string; title: string; chapters?: number; updatedAt?: string }>;
  activeProjectId?: string;
  /** 打开某个剧本：在桌面上打开**这个剧本自己的工作台窗口**（最大化），不是跳走 */
  onOpenProject: (id: string) => void;
  onNewProject: () => void;
  apps: DesktopApp[];
  /** 当前剧本的工作台窗口是否打开（打开时工作台以"最大化窗口"形式出现在桌面上） */
  scriptOpen: boolean;
  activeProjectTitle?: string;
  onCloseScript: () => void;
  onScriptMinimize?: () => void;
  /** 右键剧本图标：重命名 / 复制 / 删除（跟 Windows 的桌面右键一致） */
  onRenameProject?: (id: string) => void;
  onDuplicateProject?: (id: string) => void;
  onDeleteProject?: (id: string) => void;
  /**
   * 开始菜单里的"跳到这个剧本的某一页"（写作/设定/角色工坊/地图/剧情状态/项目）。
   * 跟 Windows 任务栏的跳转列表一个意思：桌面视角下这些页在剧本窗口里，
   * 但入口不该只有"双击图标再找标签"一条路。
   */
  scriptTabs?: Array<{ id: string; label: string }>;
  onOpenScriptTab?: (id: string) => void;
  /**
   * 外部请求开某个应用窗口（例如工作台顶栏的「审稿」按钮在桌面视角下不该弹浮窗，
   * 而应该打开桌面上的「AI 责编」窗口）。改 nonce 即触发一次。
   */
  openAppRequest?: { id: string; nonce: number };
  /**
   * 「继续写作」：桌面空着时给一条零学习成本的回头路 ——
   * 直接打开上次那个剧本、回到上次那一章（而不是"自己找哪个图标是刚才写的"）。
   */
  resume?: { projectTitle: string; chapterLabel: string };
  onResume?: () => void;
  /** 切换回工作台视图（非桌面形态） */
  onSwitchToStudioView: () => void;
  /** 注销：回到登录页（会重新走过开机画面） */
  onLogout: () => void;
};

const RESERVE_BOTTOM = 46; // 任务栏高度（桌面视图里底部音乐条由「音乐播放器」窗口提供）
const DRAG_THRESHOLD = 4; // 位移超过这么多像素才算"拖动"，避免单击时图标抖一下

/** 拖动中的图标：跟手位置 + 按下时的偏移（保证图标不会"跳"到指针中心） */
type DragInfo = { id: string; x: number; y: number; dx: number; dy: number };
/** 按下时就记下起点，用来区分"单击"和"拖动" */
type PendingDrag = DragInfo & { startX: number; startY: number };

/**
 * 点到的是"桌面空白"吗？
 *
 * 注意别用"target 就是桌面根节点"来判断：图标区是 inset:0 的一整层，
 * 空白处的 target 永远是它，那样判断的话"点空白取消选中/弹桌面菜单"永远不会触发。
 * 所以反过来问：这个 target 是不是图标/窗口/任务栏的一部分。
 */
function isBlankSpot(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return true;
  return !el.closest(
    "button, [data-desktop-menu], [data-testid^='desktop-window-'], [data-testid='desktop-script-window']"
  );
}

/**
 * 桌面视图：图标有固定座位（拖动=换座，松手自动对齐）、应用开成窗口、任务栏管窗口。
 *
 * 桌面上**没有"剧本编辑器"这个软件**：剧本自己就是入口 —— 双击某个剧本图标，
 * 打开的是这个剧本自己的工作台窗口（写作页 / 设定 / 角色工坊 / 地图 / 剧情状态，
 * 以及只读这个剧本的 AI 责编）。剧本的常用操作（重命名/复制/删除）在图标右键菜单里，
 * 跟 Windows 桌面一致；导入/模板这类"管理全部剧本"的事在开始菜单的「剧本库」窗口里。
 *
 * 窗口是**自己的形态**而不是跳回原界面；桌面只放"快捷方式"，系统设置/帮助/公告进开始菜单；
 * 图标座位与窗口位置会被记住（跨刷新）。
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
  scriptOpen,
  activeProjectTitle,
  onCloseScript,
  onScriptMinimize,
  onRenameProject,
  onDuplicateProject,
  onDeleteProject,
  scriptTabs,
  onOpenScriptTab,
  openAppRequest,
  resume,
  onResume,
  onSwitchToStudioView,
  onLogout,
}: Props) {
  const [layout, setLayout] = useState<DesktopLayout>(() => loadLayout());
  const [selected, setSelected] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  /** 首次进入桌面视角的一次性小抄（讲清四条操作，关掉就永久不再出现） */
  const [tipsOpen, setTipsOpen] = useState(() =>
    shouldShowDesktopTips({ scriptOpen: false })
  );
  /** 右键菜单：图标菜单带 id，空白处菜单只有位置 */
  const [ctxMenu, setCtxMenu] = useState<{ id: string | null; x: number; y: number } | null>(
    null
  );
  const lastClick = useRef<{ id: string; at: number }>({ id: "", at: 0 });
  /** 按下时记下的拖动信息（含偏移与起点，用来判定"到底算不算拖动"） */
  const pendingDrag = useRef<PendingDrag | null>(null);
  /** 已经越过阈值、真的开始拖了（单击不该触发"浮起来"的样式） */
  const dragActive = useRef(false);
  const iconIdsRef = useRef<string[]>([]);
  /** 图标按钮 ref：键盘方向键在它们之间移动焦点 */
  const iconRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const icons = useMemo(() => buildDesktopIcons({ projects, apps }), [projects, apps]);
  const openWins = taskbarWindows(layout);
  /** 每个图标当前的座位（手工摆过的优先，其余按清单顺序补空位） */
  const slots = useMemo(
    () => resolveIconSlots(layout, icons.map((i) => i.id)),
    [layout, icons]
  );
  /** 正在拖的图标：跟手位置，松手才真的换座位 */
  const [dragging, setDragging] = useState<DragInfo | null>(null);

  // 最新图标清单：松手落座时要按它算"换座"（用 ref 避免读到事件绑定那一刻的旧值）
  useEffect(() => {
    iconIdsRef.current = icons.map((i) => i.id);
  }, [icons]);

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

  // 小抄只在"桌面空着"时出现；一旦打开剧本窗口就自动收掉（别挡着要干的活）
  useEffect(() => {
    if (scriptOpen && tipsOpen) setTipsOpen(false);
  }, [scriptOpen, tipsOpen]);

  // 外部请求开窗口（例如工作台顶栏的「审稿」→ 桌面上的「AI 责编」窗口）
  const lastOpenRequest = useRef(openAppRequest?.nonce ?? 0);
  useEffect(() => {
    if (!openAppRequest) return;
    if (openAppRequest.nonce === lastOpenRequest.current) return;
    lastOpenRequest.current = openAppRequest.nonce;
    const app = apps.find((a) => a.id === openAppRequest.id);
    if (!app?.render) return;
    setLayout((cur) =>
      openWindow(cur, app.id, app.defaultRect ?? { x: 90, y: 70, w: 520, h: 420 })
    );
  }, [openAppRequest, apps]);

  /**
   * 关掉开始菜单/右键菜单：点任务栏外面、按 ESC、或者点了别处都算。
   * 必须挂在 document 上：剧本窗口打开时桌面层是"事件穿透"的，点在面板上收不到桌面的事件。
   */
  useEffect(() => {
    if (!menuOpen && !ctxMenu && !tipsOpen) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.closest("[data-desktop-menu]")) return;
      setMenuOpen(false);
      setCtxMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setCtxMenu(null);
        setTipsOpen((open) => {
          if (open) markDesktopTipsSeen();
          return false;
        });
      }
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen, ctxMenu, tipsOpen]);

  // 图标拖动：跟手移动，松手才"落座"到最近的座位（桌面有固定座位表，不是随便放）。
  // 越过 DRAG_THRESHOLD 那一小段位移才算拖动 —— 否则单纯点一下图标也会"浮起来"闪一下。
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const p = pendingDrag.current;
      if (!p) return;
      if (!dragActive.current) {
        if (Math.hypot(e.clientX - p.startX, e.clientY - p.startY) < DRAG_THRESHOLD) return;
        dragActive.current = true;
      }
      setDragging({ id: p.id, dx: p.dx, dy: p.dy, x: e.clientX - p.dx, y: e.clientY - p.dy });
    };
    const stop = (e: PointerEvent) => {
      const p = pendingDrag.current;
      pendingDrag.current = null;
      if (p && dragActive.current) {
        // 松手位置 → 最近的座位号；座位上原来有图标就换座
        const target = nearestSlot(e.clientX - p.dx, e.clientY - p.dy);
        setLayout((cur) => assignIconSlot(cur, p.id, target, iconIdsRef.current));
      }
      dragActive.current = false;
      setDragging(null);
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
    if (appId === "more") {
      // 「更多剧本」= 打开剧本库窗口（全部剧本的管理入口）
      openApp("library");
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

  /** 关掉一次性小抄（记住，以后不再出现） */
  function closeTips() {
    setTipsOpen(false);
    markDesktopTipsSeen();
  }

  /**
   * 排列图标：忘掉手工摆过的座位，回到默认顺序（跟 Windows 的自动排列一致）。
   * 只动图标、不动窗口 —— "窗口找不回来"是另一件事，见开始菜单里的「关掉所有窗口」。
   */
  function tileIcons() {
    setLayout((cur) => ({ ...cur, icons: {} }));
  }

  /**
   * 键盘操作（桌面比喻该有的那几件）：方向键在座位间移动、Enter 打开、
   * F2 重命名、Delete 删除。焦点跟着走，选中态同步，底部提示条会显示这个图标能干什么。
   */
  function handleIconKey(e: React.KeyboardEvent<HTMLButtonElement>, icon: DesktopIcon) {
    const dir =
      e.key === "ArrowUp"
        ? "up"
        : e.key === "ArrowDown"
          ? "down"
          : e.key === "ArrowLeft"
            ? "left"
            : e.key === "ArrowRight"
              ? "right"
              : null;
    if (dir) {
      e.preventDefault();
      const next = nextIconInDirection(slots, icon.id, dir);
      if (next) {
        setSelected(next);
        iconRefs.current[next]?.focus();
      }
      return;
    }
    const projectId = icon.id.startsWith("project:") ? icon.id.slice("project:".length) : null;
    if (e.key === "F2" && projectId && onRenameProject) {
      e.preventDefault();
      onRenameProject(projectId);
      return;
    }
    if (e.key === "Delete" && projectId && onDeleteProject) {
      e.preventDefault();
      onDeleteProject(projectId);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      openIcon(icon);
    }
  }

  const selectedHint =
    icons.find((i) => i.id === selected)?.hint ??
    "双击打开；右键有菜单；拖动可以换座位（松手自动对齐）";

  /** 右键菜单的项目（按图标类型给不同的项） */
  function menuItemsFor(icon: DesktopIcon): Array<{ label: string; run: () => void }> {
    const id = icon.id.startsWith("project:") ? icon.id.slice("project:".length) : null;
    const items: Array<{ label: string; run: () => void }> = [
      { label: "打开", run: () => openIcon(icon) },
    ];
    if (id) {
      if (onRenameProject) items.push({ label: "重命名…", run: () => onRenameProject(id) });
      if (onDuplicateProject) items.push({ label: "复制一份", run: () => onDuplicateProject(id) });
      if (onDeleteProject) items.push({ label: "删除…", run: () => onDeleteProject(id) });
    }
    return items;
  }

  const ctxIcon = ctxMenu?.id
    ? icons.find((i) => i.id === ctxMenu.id) ?? null
    : null;

  return (
    <div
      className={`${styles.desktop} ${scriptOpen ? styles.desktopPassThrough : ""}`}
      data-testid="desktop-view"
      onPointerDown={(e) => {
        // 任何一次点击都算"看懂了"，小抄让路
        if (tipsOpen) closeTips();
        if (isBlankSpot(e.target)) {
          setMenuOpen(false);
          setCtxMenu(null);
          setSelected(null);
        }
      }}
      onContextMenu={(e) => {
        // 右键空白处 = 桌面自己的菜单（新建剧本 / 排列图标 / 打开剧本库），跟 Windows 一致
        if (!isBlankSpot(e.target)) return;
        e.preventDefault();
        setMenuOpen(false);
        setSelected(null);
        setCtxMenu({ id: null, x: e.clientX, y: e.clientY });
      }}
    >
      {/* 图标与暗角只在"没有打开剧本窗口"时出现 —— 否则会浮在工作台上面 */}
      {!scriptOpen ? <div className={styles.dim} aria-hidden data-blank="1" /> : null}

      {/* 首次进入桌面视角的一次性小抄：放在右侧空白区，不挡图标；点任意处或「知道了」即关闭 */}
      {!scriptOpen && tipsOpen ? (
        <aside
          className={styles.tips}
          data-testid="desktop-tips"
          aria-label="桌面视角怎么用"
        >
          <p className={styles.tipsTitle}>桌面视角怎么用</p>
          <ul className={styles.tipsList}>
            {DESKTOP_TIPS.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <div className={styles.tipsFoot}>
            <span>按 Esc 或点任意处也能关掉</span>
            <button type="button" data-testid="desktop-tips-close" onClick={closeTips}>
              知道了
            </button>
          </div>
        </aside>
      ) : null}

      {/* 桌面图标：剧本（文件夹）+ 放上桌面的应用快捷方式。位置=座位号，吸附对齐 */}
      {!scriptOpen ? (
        <div
          className={styles.iconArea}
          role="list"
          aria-label="桌面图标"
          style={{ paddingBottom: RESERVE_BOTTOM + 3.4 * 16 }}
        >
          {icons.map((icon) => {
            const pos = slotToPosition(slots[icon.id] ?? 0);
            const isDragging = dragging?.id === icon.id;
            return (
              <button
                key={icon.id}
                type="button"
                role="listitem"
                aria-label={icon.label}
                className={`${styles.icon} ${selected === icon.id ? styles.iconOn : ""} ${
                  icon.id === `project:${activeProjectId}` ? styles.iconActive : ""
                } ${isDragging ? styles.iconDragging : ""}`}
                style={
                  isDragging
                    ? { left: dragging.x, top: dragging.y, zIndex: 20 }
                    : { left: pos.x, top: pos.y }
                }
                onClick={() => handleIconClick(icon)}
                onDoubleClick={() => openIcon(icon)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setMenuOpen(false);
                  setSelected(icon.id);
                  setCtxMenu({ id: icon.id, x: e.clientX, y: e.clientY });
                }}
                onPointerDown={(e) => {
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  pendingDrag.current = {
                    id: icon.id,
                    x: r.left,
                    y: r.top,
                    dx: e.clientX - r.left,
                    dy: e.clientY - r.top,
                    startX: e.clientX,
                    startY: e.clientY,
                  };
                }}
                ref={(el) => {
                  iconRefs.current[icon.id] = el;
                }}
                onFocus={() => setSelected(icon.id)}
                onKeyDown={(e) => handleIconKey(e, icon)}
                title={icon.hint}
              >
                <span className={styles.glyph} aria-hidden>
                  {icon.glyph}
                </span>
                {icon.badge ? (
                  <span className={styles.badge} data-testid={`icon-badge-${icon.id}`}>
                    {icon.badge}
                  </span>
                ) : null}
                <span className={styles.label}>{icon.label}</span>
              </button>
            );
          })}
        </div>
      ) : null}

      {/* 剧本窗口：标题就是剧本名。一个剧本一套工作台（写作页/设定/角色/地图/剧情状态 +
          只读这个剧本的 AI 责编），所以它不是"某个编辑器"，而是这个剧本自己的工作区。
          工作台本体由 StudioApp 渲染在下面这一层（见 .shellUnderDesktop），
          它的高度/边距正好让开这条标题栏与任务栏。 */}
      {scriptOpen ? (
        <div className={styles.editorFrame} data-testid="desktop-script-window">
          <header className={styles.editorBar}>
            <span aria-hidden>📖</span>
            <span className={styles.editorTitle}>{activeProjectTitle || "未命名剧本"}</span>
            <span className={styles.editorSub}>仅此剧本</span>
            <div className={styles.editorButtons}>
              <button type="button" onClick={onScriptMinimize} title="最小化到任务栏">
                —
              </button>
              <button type="button" onClick={onCloseScript} title="关闭">
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

      {/* 右键菜单：图标上（打开/重命名/复制/删除）或空白处（新建/排列图标） */}
      {ctxMenu ? (
        <div
          className={styles.ctx}
          role="menu"
          data-desktop-menu="1"
          data-testid="desktop-context-menu"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
        >
          {ctxIcon
            ? menuItemsFor(ctxIcon).map((item) => (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    const run = item.run;
                    setCtxMenu(null);
                    run();
                  }}
                >
                  {item.label}
                </button>
              ))
            : [
                { label: "📄 新建剧本", run: onNewProject },
                { label: "🧹 排列图标", run: tileIcons },
                { label: "🗄️ 打开剧本库", run: () => openApp("library") },
              ].map((item) => (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    const run = item.run;
                    setCtxMenu(null);
                    run();
                  }}
                >
                  {item.label}
                </button>
              ))}
        </div>
      ) : null}

      {/* 任务栏 */}
      <div className={styles.taskbar}>
        <button
          type="button"
          data-desktop-menu="1"
          className={menuOpen ? `${styles.start} ${styles.startOn}` : styles.start}
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
        >
          <MascotFigure size="xs" />
          <span>开始</span>
        </button>

        {menuOpen ? (
          <div className={styles.menu} role="menu" data-desktop-menu="1">
            {/* 当前剧本的各个篇章：一键打开剧本窗口并跳到那一页（不用先进去再找标签） */}
            {scriptTabs && scriptTabs.length > 0 && activeProjectTitle ? (
              <>
                <p className={styles.menuGroup}>
                  当前剧本《{activeProjectTitle}》
                </p>
                {scriptTabs.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      onOpenScriptTab?.(t.id);
                    }}
                  >
                    {t.label}
                  </button>
                ))}
              </>
            ) : null}

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
                tileIcons();
              }}
            >
              🧹 排列图标
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                // 关掉所有窗口：窗口被拖到看不见的地方时，这样就能找回来
                // （重新打开会回到默认位置，因为位置记录随窗口一起清掉了）
                setLayout((cur) => ({ ...cur, windows: {} }));
                onCloseScript();
              }}
            >
              🪟 关掉所有窗口
            </button>
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
          {scriptOpen ? (
            <button
              type="button"
              className={styles.task}
              onClick={() => onScriptMinimize?.()}
              title={activeProjectTitle || "未命名剧本"}
            >
              📖 {activeProjectTitle || "未命名剧本"}
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

        {/* 「继续写作」：桌面空着时最常做的动作，放在最显眼、零学习成本的位置 */}
        {!scriptOpen && resume && onResume ? (
          <button
            type="button"
            className={styles.resume}
            data-testid="desktop-resume"
            onClick={onResume}
            title={`继续写《${resume.projectTitle}》· ${resume.chapterLabel}`}
          >
            <span className={styles.resumeMain}>▶ 继续写作</span>
            <span className={styles.resumeSub}>
              {resume.chapterLabel} · {resume.projectTitle}
            </span>
          </button>
        ) : null}

        {/* 迷路时的出口：任务栏常驻一个"回工作台视图"（开始菜单里也有，但那里要两步） */}
        <button
          type="button"
          className={styles.task}
          data-testid="desktop-to-studio"
          onClick={onSwitchToStudioView}
          title="切换为工作台视图（三栏布局，设置里可以切回来）"
        >
          🖥️ 工作台
        </button>

        <span className={styles.clock}>
          <strong>{formatClock(now)}</strong>
          <small>{formatClockDate(now)}</small>
        </span>
        <span className={styles.user} title={username ? `已登录：${username}` : undefined}>
          {username ?? ""}
        </span>
      </div>

      <span className={styles.hintBar} style={{ opacity: scriptOpen ? 0 : 1 }}>
        {selectedHint}
      </span>
    </div>
  );
}
