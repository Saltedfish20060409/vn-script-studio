/**
 * 桌面视图的窗口与图标布局逻辑（纯函数，便于测试）。
 *
 * 桌面比喻里最容易出错的两件事都在这儿：
 * 1. **层级**：点了哪个窗口它就该在最上面（z 递增），不是靠 DOM 顺序碰运气；
 * 2. **位置**：图标/窗口拖到哪儿要记住，刷新后还在原地（不然用户摆好的布局白摆）。
 */

export type WinRect = { x: number; y: number; w: number; h: number };

export type WinState = WinRect & {
  id: string;
  z: number;
  minimized: boolean;
  /** 最大化：铺满工作区（剧本编辑器就用这一档） */
  maximized: boolean;
};

export type DesktopLayout = {
  windows: Record<string, WinState>;
  /** 图标 id → 自由位置（未记录则按默认网格排列） */
  icons: Record<string, { x: number; y: number }>;
  topZ: number;
};

export const EMPTY_LAYOUT: DesktopLayout = { windows: {}, icons: {}, topZ: 10 };

/** 图标网格：拖动后吸附到网格（Windows 也是这样，看起来才不凌乱） */
export const ICON_GRID = 8;

export function snapToGrid(value: number, grid: number = ICON_GRID): number {
  return Math.round(value / grid) * grid;
}

/** 把坐标夹在工作区内，避免拖出屏幕后找不回来。 */
export function clampToViewport(
  x: number,
  y: number,
  opts: { width: number; height: number; winWidth?: number; winHeight?: number; reserveBottom?: number }
): { x: number; y: number } {
  const maxX = Math.max(0, opts.width - (opts.winWidth ?? 0));
  const maxY = Math.max(0, opts.height - (opts.winHeight ?? 0) - (opts.reserveBottom ?? 0));
  return { x: Math.min(Math.max(0, x), maxX), y: Math.min(Math.max(0, y), maxY) };
}

/** 打开（或前置）一个窗口：已存在就置顶，不存在就按给的位置新建。 */
export function openWindow(
  layout: DesktopLayout,
  id: string,
  rect: WinRect
): DesktopLayout {
  const z = layout.topZ + 1;
  const prev = layout.windows[id];
  const next: WinState = prev
    ? { ...prev, z, minimized: false }
    : { id, ...rect, z, minimized: false, maximized: false };
  return { ...layout, topZ: z, windows: { ...layout.windows, [id]: next } };
}

export function focusWindow(layout: DesktopLayout, id: string): DesktopLayout {
  const win = layout.windows[id];
  if (!win) return layout;
  const z = layout.topZ + 1;
  return {
    ...layout,
    topZ: z,
    windows: { ...layout.windows, [id]: { ...win, z, minimized: false } },
  };
}

export function moveWindow(layout: DesktopLayout, id: string, x: number, y: number): DesktopLayout {
  const win = layout.windows[id];
  if (!win) return layout;
  return { ...layout, windows: { ...layout.windows, [id]: { ...win, x, y } } };
}

export function resizeWindow(layout: DesktopLayout, id: string, w: number, h: number): DesktopLayout {
  const win = layout.windows[id];
  if (!win) return layout;
  return { ...layout, windows: { ...layout.windows, [id]: { ...win, w, h } } };
}

export function minimizeWindow(layout: DesktopLayout, id: string): DesktopLayout {
  const win = layout.windows[id];
  if (!win) return layout;
  return { ...layout, windows: { ...layout.windows, [id]: { ...win, minimized: true } } };
}

/** 关闭 = 从布局里移除（下次打开回到默认位置，和 Windows 一样） */
export function closeWindow(layout: DesktopLayout, id: string): DesktopLayout {
  if (!layout.windows[id]) return layout;
  const rest = { ...layout.windows };
  delete rest[id];
  return { ...layout, windows: rest };
}

export function toggleMaximize(layout: DesktopLayout, id: string): DesktopLayout {
  const win = layout.windows[id];
  if (!win) return layout;
  return {
    ...layout,
    windows: { ...layout.windows, [id]: { ...win, maximized: !win.maximized, minimized: false } },
  };
}

export function setIconPosition(
  layout: DesktopLayout,
  iconId: string,
  x: number,
  y: number
): DesktopLayout {
  return {
    ...layout,
    icons: { ...layout.icons, [iconId]: { x: snapToGrid(x), y: snapToGrid(y) } },
  };
}

/** 任务栏上要显示的窗口按钮：按 z 从高到低（最近用的在最前）。 */
export function taskbarWindows(layout: DesktopLayout): WinState[] {
  return Object.values(layout.windows).sort((a, b) => b.z - a.z);
}

/** 当前应该显示在最上面的窗口（用于"点任务栏还原"）。 */
export function topWindow(layout: DesktopLayout): WinState | null {
  return taskbarWindows(layout).find((w) => !w.minimized) ?? null;
}

const LAYOUT_KEY = "vnss-desktop-layout-v1";

export function loadLayout(): DesktopLayout {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return EMPTY_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<DesktopLayout>;
    if (!parsed || typeof parsed !== "object") return EMPTY_LAYOUT;
    return {
      windows: parsed.windows && typeof parsed.windows === "object" ? parsed.windows : {},
      icons: parsed.icons && typeof parsed.icons === "object" ? parsed.icons : {},
      topZ: typeof parsed.topZ === "number" ? parsed.topZ : EMPTY_LAYOUT.topZ,
    };
  } catch {
    return EMPTY_LAYOUT;
  }
}

export function saveLayout(layout: DesktopLayout): void {
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    /* 隐私模式下写不进去也不该崩 */
  }
}

/** 删掉已经不存在的图标位置（项目被删掉后别留垃圾）。 */
export function pruneIconPositions(layout: DesktopLayout, liveIds: string[]): DesktopLayout {
  const live = new Set(liveIds);
  const icons: DesktopLayout["icons"] = {};
  for (const [id, pos] of Object.entries(layout.icons)) {
    if (live.has(id)) icons[id] = pos;
  }
  return { ...layout, icons };
}
