/**
 * 桌面视图 / 开机界面相关的纯逻辑：图标清单、时钟、开机是否显示。
 *
 * 抽出来是为了能测：这些判断写错的表现是"图标点了没反应""手机上看到桌面"
 * 这类不好复现的问题。
 */

export type ViewMode = "studio" | "desktop";

/** 窄于这个宽度不进桌面视图：触屏上没有双击/右键，桌面比喻只会让人更迷惑。 */
export const DESKTOP_MIN_WIDTH = 720;

export function isDesktopViewport(width: number): boolean {
  return width >= DESKTOP_MIN_WIDTH;
}

/** 只有用户选了桌面视图、且屏幕够宽、且不在编辑中的项目里才显示桌面。 */
export function shouldShowDesktop(opts: {
  view: ViewMode;
  width: number;
}): boolean {
  return opts.view === "desktop" && isDesktopViewport(opts.width);
}

export type DesktopIcon = {
  id: string;
  label: string;
  glyph: string;
  kind: "project" | "action";
  /** 提示条上的一句话说明 */
  hint: string;
};

/** 桌面只放"快捷方式"：项目、新建、以及应用自己声明要放桌面的那些。 */
export type DesktopAppLike = {
  id: string;
  label: string;
  glyph: string;
  onDesktop?: boolean;
};

/**
 * 桌面图标：最近项目在前，然后是新建（+ 剧本太多时的「更多剧本」），再是应用快捷方式。
 *
 * 「系统设置 / 帮助 / 更新公告 / 剧本库」这类**不进桌面**，只放开始菜单 —— 跟 Windows 一致：
 * 桌面放自己的东西（剧本、常用程序），"管理全部剧本"这种系统功能在开始里，
 * 剧本自己的重命名/复制/删除走图标右键菜单。
 *
 * 剧本超过 `maxProjects` 时补一个「更多剧本」，不然多出来的剧本在桌面上就没有入口了。
 */
export function buildDesktopIcons(opts: {
  projects: Array<{ id: string; title: string }>;
  apps?: DesktopAppLike[];
  maxProjects?: number;
}): DesktopIcon[] {
  const max = opts.maxProjects ?? 6;
  const recent = opts.projects.slice(0, max).map((p) => ({
    id: `project:${p.id}`,
    label: p.title || "未命名剧本",
    glyph: "📁",
    kind: "project" as const,
    hint: "双击打开这个剧本（写作页 / 设定 / 角色 / 地图 / 剧情状态都只属于它）；右键更多操作",
  }));
  const appIcons = (opts.apps ?? [])
    .filter((a) => a.onDesktop)
    .map((a) => ({
      id: `action:${a.id}`,
      label: a.label,
      glyph: a.glyph,
      kind: "action" as const,
      hint: `双击打开${a.label}`,
    }));
  const more: DesktopIcon[] =
    opts.projects.length > recent.length
      ? [
          {
            id: "action:more",
            label: `更多剧本（${opts.projects.length}）`,
            glyph: "🗄️",
            kind: "action",
            hint: "双击打开剧本库，查看 / 搜索 / 导入全部剧本",
          },
        ]
      : [];
  return [
    ...recent,
    {
      id: "action:new",
      label: "新建剧本",
      glyph: "📄",
      kind: "action",
      hint: "双击新建一个空白剧本",
    },
    ...more,
    ...appIcons,
  ];
}

/** 任务栏时钟：HH:MM（本地时间）。 */
export function formatClock(date: Date): string {
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function formatClockDate(date: Date): string {
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
}

const BOOT_SEEN_KEY = "vnss-boot-seen";

/**
 * 开机动画要不要放：同一会话只放一次（从登录页来回跳不该反复开机），
 * 且用户明确要求减少动效时直接跳过。
 */
export function shouldPlayBoot(opts: {
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  reducedMotion?: boolean;
}): boolean {
  if (opts.reducedMotion) return false;
  const store = opts.storage;
  if (!store) return true;
  try {
    if (store.getItem(BOOT_SEEN_KEY) === "1") return false;
    store.setItem(BOOT_SEEN_KEY, "1");
    return true;
  } catch {
    return true;
  }
}

/** 注销时重新武装开机画面：让"注销 → 重新开机"这件事成立。 */
export function rearmBoot(storage?: Pick<Storage, "removeItem"> | null): void {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.sessionStorage;
    } catch {
      store = null;
    }
  }
  try {
    store?.removeItem(BOOT_SEEN_KEY);
  } catch {
    /* 忽略 */
  }
}

const TIPS_SEEN_KEY = "vnss-desktop-tips-v1";

/** 首次进入桌面视角时的小抄内容（一次讲清四条，不再出现）。 */
export const DESKTOP_TIPS: ReadonlyArray<string> = [
  "双击剧本图标 → 打开这个剧本自己的工作台（写作 / 设定 / 角色工坊 / 地图 / 剧情状态）",
  "右键图标 → 重命名 / 复制 / 删除；右键空白处 → 新建剧本 / 整理图标",
  "「开始」里是全部应用与系统设置，也能直接跳到当前剧本的某一页",
  "图标拖到想放的位置就会自动对齐；开始菜单里「整理图标 / 重置桌面布局」能一键恢复",
];

/**
 * 桌面小抄要不要显示：只显示一次（localStorage 记住），
 * 且只有当桌面空着（没打开剧本窗口）时才出 —— 那时用户才需要认识这个界面，
 * 打开窗口后再弹只会挡住刚要在工作台里干的事。
 */
export function shouldShowDesktopTips(opts: {
  storage?: Pick<Storage, "getItem"> | null;
  scriptOpen?: boolean;
}): boolean {
  if (opts.scriptOpen) return false;
  let store = opts.storage ?? null;
  if (!opts.storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  if (!store) return false;
  try {
    return store.getItem(TIPS_SEEN_KEY) !== "1";
  } catch {
    return false;
  }
}

/** 关掉小抄就永久关掉（同一个浏览器不再出现）。 */
export function markDesktopTipsSeen(
  storage?: Pick<Storage, "setItem"> | null
): void {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  try {
    store?.setItem(TIPS_SEEN_KEY, "1");
  } catch {
    /* 隐私模式下写不进去也不该崩 */
  }
}

/** 开机动画时长：桌面比喻要像，但不能真的让人等开机。 */
export const BOOT_TOTAL_MS = 1500;
export const BOOT_REDUCED_MS = 0;
