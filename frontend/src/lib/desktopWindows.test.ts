import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  EMPTY_LAYOUT,
  clampToViewport,
  closeWindow,
  focusWindow,
  loadLayout,
  minimizeWindow,
  moveWindow,
  openWindow,
  pruneIconPositions,
  saveLayout,
  setIconPosition,
  snapToGrid,
  taskbarWindows,
  toggleMaximize,
  topWindow,
  type DesktopLayout,
} from "./desktopWindows";

const RECT = { x: 40, y: 60, w: 420, h: 320 };

function withWin(ids: string[]): DesktopLayout {
  return ids.reduce((acc, id) => openWindow(acc, id, RECT), EMPTY_LAYOUT);
}

describe("窗口层级", () => {
  it("新开的窗口在最上面，后开的更高", () => {
    const a = openWindow(EMPTY_LAYOUT, "settings", RECT);
    const b = openWindow(a, "help", RECT);
    expect(b.windows.help.z).toBeGreaterThan(b.windows.settings.z);
    expect(topWindow(b)?.id).toBe("help");
  });

  it("点某个窗口会把它抬到最上面（不是靠 DOM 顺序）", () => {
    const layout = withWin(["settings", "help"]);
    const focused = focusWindow(layout, "settings");
    expect(topWindow(focused)?.id).toBe("settings");
    expect(focused.windows.help.z).toBeLessThan(focused.windows.settings.z);
  });

  it("聚焦已最小化的窗口会顺便还原它", () => {
    let layout = withWin(["music"]);
    layout = minimizeWindow(layout, "music");
    expect(topWindow(layout)).toBeNull();
    layout = focusWindow(layout, "music");
    expect(topWindow(layout)?.id).toBe("music");
  });

  it("再次打开已存在的窗口 = 置顶 + 还原，不会重置它的位置", () => {
    let layout = openWindow(EMPTY_LAYOUT, "agent", RECT);
    layout = moveWindow(layout, "agent", 200, 120);
    layout = minimizeWindow(layout, "agent");
    layout = openWindow(layout, "agent", { x: 0, y: 0, w: 900, h: 600 });
    expect(layout.windows.agent.x).toBe(200);
    expect(layout.windows.agent.minimized).toBe(false);
  });
});

describe("任务栏", () => {
  it("按 z 从高到低列出，最近用的在最前", () => {
    let layout = withWin(["a", "b"]);
    layout = focusWindow(layout, "a");
    expect(taskbarWindows(layout).map((w) => w.id)).toEqual(["a", "b"]);
  });

  it("最小化的窗口不参与「最上面」判断，但仍然在任务栏里", () => {
    let layout = withWin(["a", "b"]);
    layout = minimizeWindow(layout, "b");
    expect(topWindow(layout)?.id).toBe("a");
    expect(taskbarWindows(layout).map((w) => w.id)).toContain("b");
  });

  it("关掉的窗口从任务栏消失", () => {
    let layout = withWin(["a"]);
    layout = closeWindow(layout, "a");
    expect(taskbarWindows(layout)).toEqual([]);
  });
});

describe("最大化", () => {
  it("来回切换都保留原位置（还原后不跳到别处）", () => {
    let layout = openWindow(EMPTY_LAYOUT, "editor", { x: 88, y: 64, w: 900, h: 600 });
    layout = toggleMaximize(layout, "editor");
    expect(layout.windows.editor.maximized).toBe(true);
    expect(layout.windows.editor.x).toBe(88);
    layout = toggleMaximize(layout, "editor");
    expect(layout.windows.editor.maximized).toBe(false);
    expect(layout.windows.editor.x).toBe(88);
  });
});

describe("坐标", () => {
  it("吸附到网格（拖完不凌乱）", () => {
    expect(snapToGrid(37, 8)).toBe(40);
    expect(snapToGrid(35, 8)).toBe(32);
    expect(setIconPosition(EMPTY_LAYOUT, "project:p1", 37, 101).icons["project:p1"]).toEqual({
      x: 40,
      y: 104,
    });
  });

  it("拖出屏幕会被拉回来（含底部任务栏预留）", () => {
    expect(clampToViewport(9999, 9999, { width: 1000, height: 800, winWidth: 300, winHeight: 200, reserveBottom: 64 }))
      .toEqual({ x: 700, y: 536 });
    expect(clampToViewport(-50, -50, { width: 1000, height: 800 })).toEqual({ x: 0, y: 0 });
  });
});

describe("持久化", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, String(v)),
      removeItem: (k: string) => void store.delete(k),
    });
  });

  it("布局能存能读（窗口位置 + 图标位置 + 层级）", () => {
    let layout = openWindow(EMPTY_LAYOUT, "music", RECT);
    layout = moveWindow(layout, "music", 120, 200);
    layout = setIconPosition(layout, "project:p1", 24, 48);
    saveLayout(layout);
    const back = loadLayout();
    expect(back.windows.music.x).toBe(120);
    expect(back.icons["project:p1"]).toEqual({ x: 24, y: 48 });
    expect(back.topZ).toBe(layout.topZ);
  });

  it("坏数据不炸，退回空布局", () => {
    localStorage.setItem("vnss-desktop-layout-v1", "{不是 JSON");
    expect(loadLayout()).toEqual(EMPTY_LAYOUT);
  });

  it("项目删掉后不留下孤立的图标位置", () => {
    let layout = setIconPosition(EMPTY_LAYOUT, "project:gone", 8, 8);
    layout = setIconPosition(layout, "project:live", 16, 16);
    const pruned = pruneIconPositions(layout, ["project:live"]);
    expect(Object.keys(pruned.icons)).toEqual(["project:live"]);
  });
});
