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
  /** 最大化：铺满工作区（剧本工作台窗口就用这一档） */
  maximized: boolean;
};

export type DesktopLayout = {
  windows: Record<string, WinState>;
  /** 图标 id → 座位号（不是自由坐标：桌面图标有固定座位，跟 Windows 一样） */
  icons: Record<string, number>;
  topZ: number;
};

export const EMPTY_LAYOUT: DesktopLayout = { windows: {}, icons: {}, topZ: 10 };

/* ── 图标座位 ────────────────────────────────────────────────────────────
 * 桌面图标不是"随便放"，而是占一个个**固定座位**：先竖着排满一列再排下一列
 * （跟 Windows 的自动排列一致）。拖动只是"换座位"，松手吸附到最近的空位，
 * 这样桌面永远不会乱，也不会出现两个图标叠在一起。
 */
export const ICON_W = 92;
export const ICON_H = 96;
export const ICON_GAP = 4;
export const ICON_ROWS = 6; // 每列几个座位
export const ICON_MARGIN_X = 16;
export const ICON_MARGIN_Y = 16;

/** 座位号 → 落点（列优先：先往下排满一列，再排右边一列）。 */
export function slotToPosition(
  slot: number,
  rows: number = ICON_ROWS
): { x: number; y: number } {
  const safe = Math.max(0, Math.floor(slot));
  const col = Math.floor(safe / Math.max(1, rows));
  const row = safe % Math.max(1, rows);
  return {
    x: ICON_MARGIN_X + col * (ICON_W + ICON_GAP),
    y: ICON_MARGIN_Y + row * (ICON_H + ICON_GAP),
  };
}

/** 落点 → 最近的座位号（拖动松手时用）。 */
export function nearestSlot(
  x: number,
  y: number,
  rows: number = ICON_ROWS
): number {
  const col = Math.max(0, Math.round((x - ICON_MARGIN_X) / (ICON_W + ICON_GAP)));
  const row = Math.max(0, Math.min(rows - 1, Math.round((y - ICON_MARGIN_Y) / (ICON_H + ICON_GAP))));
  return col * rows + row;
}

/**
 * 把一个图标放到指定座位。座位上原本有别的图标（不管是手工摆过的还是自动补位的）
 * 就**互相换座**：谁都不会被挤没，桌面也不会出现两个图标叠在一起。
 */
export function assignIconSlot(
  layout: DesktopLayout,
  iconId: string,
  slot: number,
  orderedIds: string[]
): DesktopLayout {
  const target = Math.max(0, Math.floor(slot));
  const resolved = resolveIconSlots(layout, orderedIds);
  const current = resolved[iconId];
  if (current === undefined || current === target) return layout;
  const occupant = orderedIds.find((id) => id !== iconId && resolved[id] === target);
  const icons: Record<string, number> = { ...layout.icons, [iconId]: target };
  if (occupant) icons[occupant] = current;
  return { ...layout, icons };
}

export function setIconSlot(layout: DesktopLayout, iconId: string, slot: number): DesktopLayout {
  return { ...layout, icons: { ...layout.icons, [iconId]: Math.max(0, Math.floor(slot)) } };
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

/** 任务栏上要显示的窗口按钮：按 z 从高到低（最近用的在最前）。 */
export function taskbarWindows(layout: DesktopLayout): WinState[] {
  return Object.values(layout.windows).sort((a, b) => b.z - a.z);
}

/** 当前应该显示在最上面的窗口（用于"点任务栏还原"）。 */
export function topWindow(layout: DesktopLayout): WinState | null {
  return taskbarWindows(layout).find((w) => !w.minimized) ?? null;
}

// v2：图标从"自由坐标"改成"固定座位"。旧键直接不用（这个桌面视图刚上线，
// 没有值得迁移的历史布局），换键名比写迁移代码更省事、也不会读出坏数据。
const LAYOUT_KEY = "vnss-desktop-layout-v2";

function sanitizeWindows(raw: unknown): Record<string, WinState> {
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, WinState> = {};
  for (const [id, value] of Object.entries(raw as Record<string, unknown>)) {
    const w = value as Partial<WinState>;
    if (!w || typeof w !== "object") continue;
    if (typeof w.x !== "number" || typeof w.y !== "number") continue;
    out[id] = {
      id,
      x: w.x,
      y: w.y,
      w: typeof w.w === "number" && w.w > 0 ? w.w : 520,
      h: typeof w.h === "number" && w.h > 0 ? w.h : 420,
      z: typeof w.z === "number" ? w.z : EMPTY_LAYOUT.topZ,
      minimized: Boolean(w.minimized),
      maximized: Boolean(w.maximized),
    };
  }
  return out;
}

function sanitizeIconSlots(raw: unknown): Record<string, number> {
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, number> = {};
  for (const [id, value] of Object.entries(raw as Record<string, unknown>)) {
    // 只认座位号（旧版的 {x,y} 会被丢掉，等价于"回到默认座位"）
    if (typeof value === "number" && Number.isFinite(value)) {
      out[id] = Math.max(0, Math.floor(value));
    }
  }
  return out;
}

export function loadLayout(): DesktopLayout {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return EMPTY_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<DesktopLayout>;
    if (!parsed || typeof parsed !== "object") return EMPTY_LAYOUT;
    return {
      windows: sanitizeWindows(parsed.windows),
      icons: sanitizeIconSlots(parsed.icons),
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

/** 删掉已经不存在的图标座位（项目被删掉后别留垃圾）。 */
export function pruneIconPositions(layout: DesktopLayout, liveIds: string[]): DesktopLayout {
  const live = new Set(liveIds);
  const icons: DesktopLayout["icons"] = {};
  for (const [id, slot] of Object.entries(layout.icons)) {
    if (live.has(id)) icons[id] = slot;
  }
  return { ...layout, icons };
}

/**
 * 把自动排列的图标与手工摆过的座位**合到一起**：没记录座位的按清单顺序找空位。
 * 这样"用户摆过的"不会被自动排列覆盖，新出现的图标也会自动补进空位。
 */
export function resolveIconSlots(
  layout: DesktopLayout,
  orderedIds: string[]
): Record<string, number> {
  const taken = new Set<number>();
  const out: Record<string, number> = {};
  for (const id of orderedIds) {
    const slot = layout.icons[id];
    if (typeof slot === "number" && !taken.has(slot)) {
      out[id] = slot;
      taken.add(slot);
    }
  }
  let cursor = 0;
  for (const id of orderedIds) {
    if (out[id] !== undefined) continue;
    while (taken.has(cursor)) cursor += 1;
    out[id] = cursor;
    taken.add(cursor);
    cursor += 1;
  }
  return out;
}
