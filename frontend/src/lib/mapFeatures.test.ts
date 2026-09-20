import { describe, expect, it } from "vitest";
import {
  DEFAULT_MEASURE,
  MAP_FEATURES,
  defaultFeatures,
  defaultPrefs,
  loadMapPrefs,
  resolvePrefs,
  saveMapPrefs,
  setMeasurePrefs,
  toggleFeature,
} from "./mapFeatures";
import {
  TRANSPORT_MODES,
  distanceKm,
  formatDays,
  formatKm,
  formatLegLabel,
  kmFromPixels,
  pixelDistance,
  transportById,
  travelDays,
} from "./mapDistance";

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

describe("地图功能开关", () => {
  it("默认值：已有的画笔开着，新加的测距关着", () => {
    const features = defaultFeatures();
    expect(features.strokes).toBe(true);
    expect(features.distance).toBe(false);
    // 每个声明过的功能都必须有默认值
    for (const f of MAP_FEATURES) expect(typeof features[f.id]).toBe("boolean");
  });

  it("切换只影响这一项", () => {
    const next = toggleFeature(defaultPrefs(), "distance");
    expect(next.features.distance).toBe(true);
    expect(next.features.strokes).toBe(true);
  });

  it("存在本机并读回来", () => {
    const store = fakeStorage();
    const prefs = toggleFeature(defaultPrefs(), "distance");
    saveMapPrefs(setMeasurePrefs(prefs, { km: 25, transport: "horse" }), store);
    const loaded = loadMapPrefs(store);
    expect(loaded.features.distance).toBe(true);
    expect(loaded.measure.km).toBe(25);
    expect(loaded.measure.transport).toBe("horse");
  });

  it("坏数据 / 缺字段 → 落回默认（老配置不会炸）", () => {
    expect(loadMapPrefs(fakeStorage({ "vnss-map-features-v1": "{不是 JSON" }))).toEqual(
      defaultPrefs()
    );
    const partial = loadMapPrefs(
      fakeStorage({ "vnss-map-features-v1": JSON.stringify({ features: { strokes: false } }) })
    );
    expect(partial.features.strokes).toBe(false);
    expect(partial.features.distance).toBe(false); // 没存过的用默认
    expect(partial.measure).toEqual(DEFAULT_MEASURE);
  });

  it("未知功能 id 不会污染配置", () => {
    const resolved = resolvePrefs({ features: { strokes: true, 未来功能: true } });
    expect(Object.keys(resolved.features).sort()).toEqual(["distance", "strokes"]);
  });

  it("非法比例尺被忽略（0 或负数会算出无穷大）", () => {
    const resolved = resolvePrefs({ measure: { px: 0, km: -5, transport: 42 } });
    expect(resolved.measure.px).toBe(DEFAULT_MEASURE.px);
    expect(resolved.measure.km).toBe(DEFAULT_MEASURE.km);
    expect(resolved.measure.transport).toBe(DEFAULT_MEASURE.transport);
  });

  it("storage 不可用时不抛", () => {
    expect(loadMapPrefs(null)).toEqual(defaultPrefs());
    expect(() => saveMapPrefs(defaultPrefs(), null)).not.toThrow();
  });
});

describe("测距与行程时间", () => {
  it("像素距离", () => {
    expect(pixelDistance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });

  it("按比例尺换算公里（默认 100px = 10km）", () => {
    expect(kmFromPixels(100, DEFAULT_MEASURE)).toBe(10);
    expect(kmFromPixels(250, DEFAULT_MEASURE)).toBe(25);
    expect(distanceKm({ x: 0, y: 0 }, { x: 300, y: 400 }, DEFAULT_MEASURE)).toBe(50);
  });

  it("比例尺非法时退化成默认值而不是 Infinity", () => {
    expect(Number.isFinite(kmFromPixels(100, { px: 0, km: 10 }))).toBe(true);
    expect(Number.isFinite(kmFromPixels(100, { px: 100, km: 0 }))).toBe(true);
  });

  it("行程天数按交通方式", () => {
    const walk = transportById("walk");
    expect(walk.kmPerDay).toBe(30);
    expect(travelDays(120, walk)).toBeCloseTo(4, 5);
    expect(travelDays(120, "horse")).toBeCloseTo(1.5, 5);
    // 未知方式退化成第一个（步行），不能抛
    expect(transportById("不存在").id).toBe(TRANSPORT_MODES[0].id);
  });

  it("公里与天数的显示", () => {
    expect(formatKm(8.25)).toBe("8.3 公里");
    expect(formatKm(120.4)).toBe("120 公里");
    expect(formatKm(0)).toBe("0 公里");
    expect(formatDays(0.2)).toBe("不到半天");
    expect(formatDays(0.8)).toBe("半天");
    expect(formatDays(4)).toBe("4.0 天");
    expect(formatDays(12.6)).toBe("13 天");
  });

  it("一行读法：距离 + 行程", () => {
    expect(formatLegLabel(120, "walk")).toBe("约 120 公里 · 步行约 4.0 天");
    expect(formatLegLabel(120, "walk", { includeKm: false })).toBe("步行约 4.0 天");
  });
});
