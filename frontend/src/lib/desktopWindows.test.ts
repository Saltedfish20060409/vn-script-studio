import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  EMPTY_LAYOUT,
  ICON_GAP,
  ICON_H,
  ICON_MARGIN_X,
  ICON_MARGIN_Y,
  ICON_ROWS,
  ICON_W,
  assignIconSlot,
  clampToViewport,
  closeWindow,
  focusWindow,
  loadLayout,
  minimizeWindow,
  moveWindow,
  nearestSlot,
  nextIconInDirection,
  openWindow,
  pruneIconPositions,
  resetLayout,
  resolveIconSlots,
  saveLayout,
  setIconSlot,
  slotToPosition,
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
    let layout = openWindow(EMPTY_LAYOUT, "script", { x: 88, y: 64, w: 900, h: 600 });
    layout = toggleMaximize(layout, "script");
    expect(layout.windows.script.maximized).toBe(true);
    expect(layout.windows.script.x).toBe(88);
    layout = toggleMaximize(layout, "script");
    expect(layout.windows.script.maximized).toBe(false);
    expect(layout.windows.script.x).toBe(88);
  });
});

describe("图标座位", () => {
  it("座位是固定网格：先往下排满一列，再排下一列", () => {
    expect(slotToPosition(0)).toEqual({ x: ICON_MARGIN_X, y: ICON_MARGIN_Y });
    expect(slotToPosition(1)).toEqual({ x: ICON_MARGIN_X, y: ICON_MARGIN_Y + ICON_H + ICON_GAP });
    expect(slotToPosition(ICON_ROWS)).toEqual({
      x: ICON_MARGIN_X + ICON_W + ICON_GAP,
      y: ICON_MARGIN_Y,
    });
  });

  it("落点吸回最近的座位，并且行号被夹在座位表内（不会排到任务栏下面）", () => {
    expect(nearestSlot(ICON_MARGIN_X + 3, ICON_MARGIN_Y + 3)).toBe(0);
    // 行 2 偏下一点 → 仍然是行 2
    expect(nearestSlot(ICON_MARGIN_X, ICON_MARGIN_Y + 2 * (ICON_H + ICON_GAP) + 10)).toBe(2);
    // 拖到很下面也不会得到第 99 行，而是最后一行的某个座位
    const far = nearestSlot(ICON_MARGIN_X, 99_999);
    expect(far % ICON_ROWS).toBe(ICON_ROWS - 1);
  });

  it("手工摆过的座位优先，其余按清单顺序补空位（不会两个图标叠在一起）", () => {
    const layout = setIconSlot(EMPTY_LAYOUT, "b", 2);
    const slots = resolveIconSlots(layout, ["a", "b", "c"]);
    expect(slots.b).toBe(2);
    expect(slots.a).toBe(0);
    expect(slots.c).toBe(1); // 跳过被 b 占掉的 2
    expect(new Set(Object.values(slots)).size).toBe(3);
  });

  it("拖到别人的座位上 = 换座（占位方不会被挤没）", () => {
    const layout = setIconSlot(EMPTY_LAYOUT, "a", 0);
    const swapped = assignIconSlot(layout, "a", 2, ["a", "b", "c"]);
    const slots = resolveIconSlots(swapped, ["a", "b", "c"]);
    expect(slots.a).toBe(2);
    expect(slots.c).toBe(0); // 原来在 2 的 c 挪到 a 腾出来的 0
    expect(new Set(Object.values(slots)).size).toBe(3);
  });

  it("拖回自己的座位不算移动（布局对象不变）", () => {
    const layout = setIconSlot(EMPTY_LAYOUT, "a", 3);
    expect(assignIconSlot(layout, "a", 3, ["a", "b"])).toBe(layout);
  });

  it("座位号是排过序的，坏值（负数/小数）被规整", () => {
    const layout = setIconSlot(EMPTY_LAYOUT, "a", -4.7);
    expect(layout.icons.a).toBe(0);
  });
});

describe("键盘在图标间移动", () => {
  // 一列 6 个座位（ICON_ROWS=6）：a0..a5 在第一列，b0 在第二列第一个
  const slots: Record<string, number> = {
    a0: 0,
    a1: 1,
    a2: 2,
    a3: 3,
    a4: 4,
    a5: 5,
    b0: 6,
    b1: 7,
  };

  it("上下在同一列内走，不会跨列", () => {
    expect(nextIconInDirection(slots, "a0", "down")).toBe("a1");
    expect(nextIconInDirection(slots, "a1", "up")).toBe("a0");
    // 该列最后一个再往下 → 没有下一个（不该跳到下一列第一行）
    expect(nextIconInDirection(slots, "a5", "down")).toBeNull();
  });

  it("左右换列", () => {
    expect(nextIconInDirection(slots, "a0", "right")).toBe("b0");
    expect(nextIconInDirection(slots, "b0", "left")).toBe("a0");
    // 最左列再往左 → 没有
    expect(nextIconInDirection(slots, "a0", "left")).toBeNull();
  });

  it("目标座位空着时，继续往那个方向找最近的图标（用户摆乱了也不卡住）", () => {
    const sparse: Record<string, number> = { x: 0, y: 3 }; // 0 和 3 都在第一列
    expect(nextIconInDirection(sparse, "x", "down")).toBe("y");
    expect(nextIconInDirection(sparse, "y", "up")).toBe("x");
  });

  it("当前图标没有座位记录 → 不动（返回 null）", () => {
    expect(nextIconInDirection(slots, "nope", "down")).toBeNull();
  });
});

describe("重置桌面布局", () => {
  it("图标座位与窗口位置一起清掉，层级计数器保留", () => {
    let layout = openWindow(EMPTY_LAYOUT, "music", RECT);
    layout = setIconSlot(layout, "project:p1", 3);
    const reset = resetLayout(layout);
    expect(reset.icons).toEqual({});
    expect(reset.windows).toEqual({});
    expect(reset.topZ).toBeGreaterThanOrEqual(EMPTY_LAYOUT.topZ);
  });
});

describe("窗口贴边", () => {
  it("拖出屏幕会被拉回来（含底部任务栏预留）", () => {
    expect(
      clampToViewport(9999, 9999, {
        width: 1000,
        height: 800,
        winWidth: 300,
        winHeight: 200,
        reserveBottom: 64,
      })
    ).toEqual({ x: 700, y: 536 });
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

  it("布局能存能读（窗口位置 + 图标座位 + 层级）", () => {
    let layout = openWindow(EMPTY_LAYOUT, "music", RECT);
    layout = moveWindow(layout, "music", 120, 200);
    layout = setIconSlot(layout, "project:p1", 4);
    saveLayout(layout);
    const back = loadLayout();
    expect(back.windows.music.x).toBe(120);
    expect(back.icons["project:p1"]).toBe(4);
    expect(back.topZ).toBe(layout.topZ);
  });

  it("旧版的坐标式图标位置读不进来（v2 只认座位号），等价于回到默认排列", () => {
    localStorage.setItem(
      "vnss-desktop-layout-v2",
      JSON.stringify({ windows: {}, topZ: 10, icons: { "project:p1": { x: 24, y: 48 } } })
    );
    expect(loadLayout().icons).toEqual({});
  });

  it("坏数据不炸，退回空布局", () => {
    localStorage.setItem("vnss-desktop-layout-v2", "{不是 JSON");
    expect(loadLayout()).toEqual(EMPTY_LAYOUT);
  });

  it("项目删掉后不留下孤立的图标座位", () => {
    let layout = setIconSlot(EMPTY_LAYOUT, "project:gone", 1);
    layout = setIconSlot(layout, "project:live", 2);
    const pruned = pruneIconPositions(layout, ["project:live"]);
    expect(Object.keys(pruned.icons)).toEqual(["project:live"]);
  });
});
