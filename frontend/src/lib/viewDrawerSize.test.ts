import { describe, expect, it } from "vitest";

import {
  VIEW_DEFAULT_SIZE,
  nextViewSize,
  resolveViewSize,
  sanitizeViewSizeOverrides,
  type ViewPanelId,
} from "./viewDrawerSize";

describe("视图抽屉宽度策略", () => {
  it("吃宽度的面板默认给 wide，清单式的给 narrow", () => {
    // 这条是"不要再来一次一律 560px"的守卫：改默认值时必须是有意的。
    expect(VIEW_DEFAULT_SIZE.analysis).toBe("wide");
    expect(VIEW_DEFAULT_SIZE.voice).toBe("wide");
    expect(VIEW_DEFAULT_SIZE.world).toBe("wide");
    expect(VIEW_DEFAULT_SIZE.map).toBe("wide");
    expect(VIEW_DEFAULT_SIZE.system).toBe("narrow");
  });

  it("没选过时用默认档", () => {
    for (const panel of Object.keys(VIEW_DEFAULT_SIZE) as ViewPanelId[]) {
      expect(resolveViewSize(panel)).toBe(VIEW_DEFAULT_SIZE[panel]);
      expect(resolveViewSize(panel, {})).toBe(VIEW_DEFAULT_SIZE[panel]);
      expect(resolveViewSize(panel, null)).toBe(VIEW_DEFAULT_SIZE[panel]);
    }
  });

  it("选过时用选择（作者可以自己把某个面板钉成全宽）", () => {
    expect(resolveViewSize("system", { system: "full" })).toBe("full");
    expect(resolveViewSize("analysis", { analysis: "narrow" })).toBe("narrow");
  });

  it("localStorage 里的坏值当作没选过，不抛错", () => {
    const bad = { system: "huge", analysis: 3, nope: "wide" } as never;
    expect(resolveViewSize("system", bad)).toBe(VIEW_DEFAULT_SIZE.system);
    expect(resolveViewSize("analysis", bad)).toBe(VIEW_DEFAULT_SIZE.analysis);
    expect(sanitizeViewSizeOverrides(bad)).toEqual({});
    expect(sanitizeViewSizeOverrides(null)).toEqual({});
    expect(sanitizeViewSizeOverrides("x")).toEqual({});
  });

  it("铺满 ↔ 默认档 之间切换（收窄回到本该有的宽度，不是一律 560）", () => {
    expect(nextViewSize("analysis", "wide")).toBe("full");
    expect(nextViewSize("analysis", "full")).toBe("wide");
    expect(nextViewSize("system", "narrow")).toBe("full");
    expect(nextViewSize("system", "full")).toBe("narrow");
  });

  it("过滤只保留合法键与合法值", () => {
    expect(
      sanitizeViewSizeOverrides({ analysis: "full", map: "wide", bad: 1, system: "narrow" })
    ).toEqual({ analysis: "full", map: "wide", system: "narrow" });
  });
});
