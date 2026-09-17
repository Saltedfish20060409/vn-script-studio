import { useEffect, useMemo, useRef, useState } from "react";
import { buildDesktopIcons, formatClock, formatClockDate, type DesktopIcon } from "../lib/desktopView";
import { MascotFigure } from "./MascotFigure";
import styles from "./DesktopView.module.css";

type Props = {
  username?: string;
  projects: Array<{ id: string; title: string }>;
  onOpenProject: (id: string) => void;
  onNewProject: () => void;
  onOpenLibrary: () => void;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
  onOpenNotice: () => void;
  /** 切回三栏写作工作台 */
  onExitDesktop: () => void;
};

/**
 * 桌面视图：一屏"像操作系统"的入口，双击图标进各自的去处。
 *
 * 边界很清楚：**它只是外壳**。点剧本 → 打开的仍是原来的三栏工作台，
 * 数据模型、编辑器、协作都没动；窄屏会自动回到工作台（见 shouldShowDesktop）。
 * 图标交互按桌面习惯来：单击选中、双击打开，同时支持键盘 Enter 打开
 * （纯靠双击会让键盘用户用不了）。
 *
 * 壁纸、桌宠、点击特效、音乐条都由 StudioApp 根上全局渲染，这里不再重复一份
 * （重复渲染会出现两个桌宠、两条音乐条）。
 */
export function DesktopView({
  username,
  projects,
  onOpenProject,
  onNewProject,
  onOpenLibrary,
  onOpenSettings,
  onOpenHelp,
  onOpenNotice,
  onExitDesktop,
}: Props) {
  const [selected, setSelected] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  const lastClick = useRef<{ id: string; at: number }>({ id: "", at: 0 });

  const icons = useMemo(() => buildDesktopIcons({ projects }), [projects]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  function open(icon: DesktopIcon) {
    if (icon.kind === "project") {
      onOpenProject(icon.id.slice("project:".length));
      return;
    }
    switch (icon.id) {
      case "action:new":
        onNewProject();
        break;
      case "action:library":
        onOpenLibrary();
        break;
      case "action:settings":
        onOpenSettings();
        break;
      case "action:help":
        onOpenHelp();
        break;
      case "action:notice":
        onOpenNotice();
        break;
      case "action:studio":
        onExitDesktop();
        break;
      default:
        break;
    }
  }

  /** 桌面式交互：单击选中；同一个图标在 400ms 内再点一次 = 双击打开。 */
  function handleClick(icon: DesktopIcon) {
    const t = Date.now();
    const isDouble = lastClick.current.id === icon.id && t - lastClick.current.at < 400;
    lastClick.current = { id: icon.id, at: t };
    setSelected(icon.id);
    if (isDouble) open(icon);
  }

  const selectedHint = icons.find((i) => i.id === selected)?.hint ?? "双击图标打开；也可以选中后按回车";

  return (
    <div
      className={styles.desktop}
      data-testid="desktop-view"
      /* 点空白处：收起开始菜单、取消选中（桌面的基本手感） */
      onPointerDown={(e) => {
        if (e.target === e.currentTarget || (e.target as HTMLElement).dataset.blank === "1") {
          setMenuOpen(false);
          setSelected(null);
        }
      }}
    >
      {/* 暗角：白字图标在任何壁纸上都要读得清（不动全局壁纸设置） */}
      <div className={styles.dim} aria-hidden data-blank="1" />

      {/* 桌面图标区 */}
      <div className={styles.iconArea} role="list" aria-label="桌面图标">
        {icons.map((icon) => (
          <button
            key={icon.id}
            type="button"
            role="listitem"
            className={selected === icon.id ? `${styles.icon} ${styles.iconOn}` : styles.icon}
            onClick={() => handleClick(icon)}
            onDoubleClick={() => open(icon)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                open(icon);
              }
            }}
            title={icon.hint}
          >
            <span className={styles.glyph} aria-hidden>
              {icon.glyph}
            </span>
            <span className={styles.label}>{icon.label}</span>
          </button>
        ))}
      </div>

      {/* 任务栏 */}
      <div className={styles.taskbar}>
        <button
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
            <button type="button" role="menuitem" onClick={onExitDesktop}>
              ✍️ 写作工作台
            </button>
            <button type="button" role="menuitem" onClick={onOpenLibrary}>
              🗂️ 剧本库
            </button>
            <button type="button" role="menuitem" onClick={onNewProject}>
              📄 新建剧本
            </button>
            <button type="button" role="menuitem" onClick={onOpenSettings}>
              ⚙️ 系统设置
            </button>
            <button type="button" role="menuitem" onClick={onOpenNotice}>
              📢 更新公告
            </button>
            <button type="button" role="menuitem" onClick={onOpenHelp}>
              ❓ 帮助 / FAQ
            </button>
          </div>
        ) : null}

        <span className={styles.hint}>{selectedHint}</span>

        <span className={styles.clock}>
          <strong>{formatClock(now)}</strong>
          <small>{formatClockDate(now)}</small>
        </span>
        <span className={styles.user} title={username ? `已登录：${username}` : undefined}>
          {username ? `${username}` : ""}
        </span>
      </div>
    </div>
  );
}
