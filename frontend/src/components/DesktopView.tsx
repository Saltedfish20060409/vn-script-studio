import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
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
  /**
   * 打开某个剧本：**在桌面上打开这个剧本自己的窗口**（B 方案）。
   * 窗口标题栏上另有「全屏写作」，那才是离开桌面、进整套 Word 壳。
   */
  onOpenProject: (id: string) => void;
  onNewProject: () => void;
  apps: DesktopApp[];
  activeProjectTitle?: string;
  /** 右键剧本图标：重命名 / 复制 / 删除（跟 Windows 的桌面右键一致） */
  onRenameProject?: (id: string) => void;
  onDuplicateProject?: (id: string) => void;
  onDeleteProject?: (id: string) => void;
  /**
   * 开始菜单里的"跳到这个剧本的某一页"（写作/设定/角色工坊/地图/剧情状态/项目）。
   * 会进入稿纸工作台并打开对应 overlay。
   */
  scriptTabs?: Array<{ id: string; label: string }>;
  onOpenScriptTab?: (id: string) => void;
  /**
   * 外部请求开某个应用窗口（例如工作台顶栏的「审稿」按钮在桌面视角下不该弹浮窗，
   * 而应该打开桌面上的「AI 责编」窗口）。改 nonce 即触发一次。
   */
  openAppRequest?: { id: string; nonce: number };
  /** 作品窗口是否正开在桌面上（开着时图标/小抄收起，桌面让位给窗口） */
  scriptOpen?: boolean;
  /** 作品窗口最小化到任务栏：窗口还在（任务栏能点回来），只是不占屏幕 */
  scriptMinimized?: boolean;
  /** 标题栏「全屏写作」：离开桌面，用整套 Word 壳铺满屏幕（顶栏「返回桌面」回来） */
  onScriptFullscreen?: () => void;
  /** 标题栏「—」：最小化到任务栏 */
  onScriptMinimize?: () => void;
  /** 任务栏上的作品窗口按钮：从最小化还原 */
  onScriptRestore?: () => void;
  /** 标题栏「✕」与开始菜单「关掉所有窗口」：关掉作品窗口（回到桌面图标） */
  onCloseScript?: () => void;
  /**
   * 「继续写作」：桌面空着时给一条零学习成本的回头路 ——
   * 直接进入稿纸工作台、回到上次那一章。
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
 * 桌面：图标有固定座位、应用开成窗口、任务栏管窗口。
 *
 * 双击剧本 = **在桌面上打开这个剧本自己的窗口**（标题栏 + 底下的稿纸工作台），
 * 桌面并不退场 —— 这就是"打开项目 = 打开该项目的窗口"。
 * 想只留稿子，点窗口标题栏的「全屏写作」；从全屏回来走顶栏「文件 → 返回桌面」。
 *
 * 一扇窗，一套稿纸：工作台本体由 StudioApp 渲染在标题栏与任务栏之间那一条
 * （见 `.shellUnderDesktop`），桌面这一层只画自己该画的（标题栏 / 任务栏 / 应用窗口），
 * 其余空白处的鼠标事件让给下面的工作台（`.desktopPassThrough`）——
 * 否则 fixed + inset:0 的桌面层会把整屏点击吃掉，"只能滚不能点"。
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
  activeProjectTitle,
  onRenameProject,
  onDuplicateProject,
  onDeleteProject,
  scriptTabs,
  onOpenScriptTab,
  openAppRequest,
  scriptOpen = false,
  scriptMinimized = false,
  onScriptFullscreen,
  onScriptMinimize,
  onScriptRestore,
  onCloseScript,
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
    shouldShowDesktopTips({ scriptOpen })
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

  // 作品窗口开着时，一次性小抄让路（它讲的是"桌面怎么用"，而用户已经在用桌面了）
  useEffect(() => {
    if (scriptOpen && tipsOpen) setTipsOpen(false);
  }, [scriptOpen, tipsOpen]);

  /**
   * 关掉开始菜单/右键菜单：点任务栏外面、按 ESC、或者点了别处都算。
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

  const closeTips = useCallback(() => {
    markDesktopTipsSeen();
    setTipsOpen(false);
  }, []);

  function openApp(id: string) {
    const app = apps.find((a) => a.id === id);
    if (!app) return;
    app.run?.();
    if (!app.render) return;
    setLayout((cur) =>
      openWindow(cur, id, app.defaultRect ?? { x: 90, y: 70, w: 520, h: 420 })
    );
  }

  function openIcon(icon: DesktopIcon) {
    setSelected(icon.id);
    if (icon.id.startsWith("project:")) {
      onOpenProject(icon.id.slice("project:".length));
      return;
    }
    /* 图标 id 带命名空间（`project:` / `action:`），而 `openApp` 要的是**应用 id**。
       上一版重构给图标加命名空间时漏了这里：以前 icon.id 直接就是应用 id，
       加前缀之后 `apps.find(a => a.id === id)` 永远找不到，
       于是"双击应用图标 / 双击「更多剧本」都没有任何反应"。
       回归用例：desktop.harness.spec.ts 的两条窗口用例（剧本库 / AI 责编）。
       三种 action 各有归宿：`new` 走新建、`more` 打开剧本库、
       其余是应用快捷方式（`action:agent` → 应用 `agent`）。 */
    const action = icon.id.startsWith("action:")
      ? icon.id.slice("action:".length)
      : icon.id;
    if (action === "new") {
      onNewProject();
      return;
    }
    openApp(action === "more" ? "library" : action);
  }

  /** 单击选中；短间隔二次点击当双击（触控板/触屏不完全可靠） */
  function handleIconClick(icon: DesktopIcon) {
    const nowMs = Date.now();
    const same = lastClick.current.id === icon.id && nowMs - lastClick.current.at < 450;
    lastClick.current = { id: icon.id, at: nowMs };
    if (same) {
      openIcon(icon);
      return;
    }
    setSelected(icon.id);
  }

  function handleIconKey(e: ReactKeyboardEvent, icon: DesktopIcon) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openIcon(icon);
      return;
    }
    /* F2 / Delete：桌面图标的通用键盘操作（与右键菜单「重命名 / 删除」同一对动作）。
       上一版重构把这两个键丢了——只剩方向键与 Enter——而右键菜单还在，
       于是"能点鼠标、不能按键盘"。回归用例：desktop.harness.spec.ts
       「键盘：方向键移动、Enter 打开、F2 重命名、Delete 删除」。
       回调约定是**裸项目 id**（与右键一致）；icon.id 带 `project:` 前缀，这里剥掉。 */
    if (icon.id.startsWith("project:")) {
      const projectId = icon.id.slice("project:".length);
      if (e.key === "F2" && onRenameProject) {
        e.preventDefault();
        onRenameProject(projectId);
        return;
      }
      if (e.key === "Delete" && onDeleteProject) {
        e.preventDefault();
        onDeleteProject(projectId);
        return;
      }
    }
    if (
      e.key === "ArrowLeft" ||
      e.key === "ArrowRight" ||
      e.key === "ArrowUp" ||
      e.key === "ArrowDown"
    ) {
      e.preventDefault();
      const dir =
        e.key === "ArrowLeft"
          ? "left"
          : e.key === "ArrowRight"
            ? "right"
            : e.key === "ArrowUp"
              ? "up"
              : "down";
      const next = nextIconInDirection(slots, icon.id, dir);
      if (!next) return;
      setSelected(next);
      iconRefs.current[next]?.focus();
    }
  }

  function tileIcons() {
    setLayout((cur) => {
      const next: DesktopLayout = { ...cur, icons: {} };
      icons.forEach((icon, i) => {
        next.icons[icon.id] = i;
      });
      return next;
    });
  }

  function menuItemsFor(icon: DesktopIcon): Array<{ label: string; run: () => void }> {
    if (icon.id.startsWith("project:")) {
      const id = icon.id.slice("project:".length);
      return [
        { label: "📖 打开（进入写作）", run: () => onOpenProject(id) },
        ...(onRenameProject
          ? [{ label: "✎ 重命名", run: () => onRenameProject(id) }]
          : []),
        ...(onDuplicateProject
          ? [{ label: "⧉ 复制", run: () => onDuplicateProject(id) }]
          : []),
        ...(onDeleteProject
          ? [{ label: "🗑 删除", run: () => onDeleteProject(id) }]
          : []),
      ];
    }
    return [{ label: "打开", run: () => openIcon(icon) }];
  }

  const ctxIcon = ctxMenu?.id ? icons.find((i) => i.id === ctxMenu.id) : null;
  const selectedHint = selected
    ? icons.find((i) => i.id === selected)?.hint ?? ""
    : "双击剧本 → 在桌面上打开这个剧本的窗口 · 右键可重命名/复制/删除";

  return (
    <div
      /* 作品窗口开着时：桌面这一层只剩"自己的东西"（标题栏 / 任务栏 / 应用窗口），
         空白处必须把鼠标事件让给下面的工作台（见 .desktopPassThrough 的注释）。 */
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
      {/* 图标与暗角只在"没有开作品窗口"时出现 —— 否则会浮在工作台上面 */}
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

      {/* 作品窗口：**只画标题栏**，稿纸工作台本体由 StudioApp 渲染在它下面那一条
          （见 .shellUnderDesktop）——一扇窗一套稿纸，不复制第二个编辑器。
          「全屏写作」= 收起桌面、让这套壳自己铺满屏幕；「—」最小化到任务栏；
          「✕」关掉窗口（剧本还在桌面上，双击图标就能再开）。 */}
      {scriptOpen ? (
        <div className={styles.editorFrame} data-testid="desktop-script-window">
          <header className={styles.editorBar}>
            <span aria-hidden>📖</span>
            <span className={styles.editorTitle}>
              {activeProjectTitle || "未命名剧本"}
            </span>
            <span className={styles.editorSub}>仅此剧本</span>
            <div className={styles.editorButtons}>
              <button
                type="button"
                className={styles.editorFullscreen}
                data-testid="script-window-fullscreen"
                onClick={onScriptFullscreen}
                title="全屏写作：收起桌面，只留稿纸（顶栏「文件 → 返回桌面」回来）"
              >
                ⛶ 全屏写作
              </button>
              <button
                type="button"
                data-testid="script-window-minimize"
                onClick={onScriptMinimize}
                title="最小化到任务栏"
              >
                —
              </button>
              <button
                type="button"
                data-testid="script-window-close"
                onClick={onCloseScript}
                title="关闭窗口（剧本还在桌面上，双击图标就能再打开）"
              >
                ✕
              </button>
            </div>
          </header>
        </div>
      ) : null}

      {/* 应用窗口（剧本库 / AI 责编 / 设置等）—— 不是稿纸工作台本身 */}
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
            {/* 当前剧本：一键进入稿纸并打开对应面板 */}
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
                // 关掉所有应用窗口：窗口被拖到看不见的地方时，这样就能找回来
                // （作品窗口也一起关：它的位置记录随窗口清掉，重开会回到默认位置）
                setLayout((cur) => ({ ...cur, windows: {} }));
                onCloseScript?.();
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
          {/* 作品窗口也是一个窗口：开着时高亮，点它最小化；最小化后点它还原。 */}
          {scriptOpen || scriptMinimized ? (
            <button
              type="button"
              data-testid="desktop-task-script"
              className={scriptOpen ? `${styles.task} ${styles.taskOn}` : styles.task}
              onClick={() => (scriptOpen ? onScriptMinimize?.() : onScriptRestore?.())}
              title={`《${activeProjectTitle || "未命名剧本"}》${
                scriptOpen ? "：点一下最小化" : "：点一下还原"
              }`}
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
          title="切换为工作台视图：收起桌面，稿纸铺满整屏（设置里可以切回来）"
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
