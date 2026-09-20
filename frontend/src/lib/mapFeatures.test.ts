import { describe, expect, it } from "vitest";
import {
  DEFAULT_MEASURE,
  MAP_FEATURES,
  MAP_SCALE_PRESETS,
  applyScalePreset,
  defaultFeatures,
  defaultPrefs,
  loadMapPrefs,
  resolvePrefs,
  saveMapPrefs,
  scalePreset,
  setMeasurePrefs,
  toggleFeature,
} from "./mapFeatures";
import {
  TRANSPORT_MODES,
  distanceKm,
  formatDuration,
  formatKm,
  formatLegLabel,
  kmFromPixels,
  pixelDistance,
  recommendedModes,
  transportById,
  travelDays,
  travelMinutes,
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

describe("地图尺度预设", () => {
  it("三种尺度各自的比例尺与默认交通方式", () => {
    const urban = scalePreset("urban").measure;
    expect(urban.km).toBe(1);
    expect(urban.transport).toBe("walk");
    expect(scalePreset("continental").measure.km).toBe(100);
    expect(scalePreset("continental").measure.transport).toBe("horse");
    expect(MAP_SCALE_PRESETS.map((p) => p.id)).toEqual(["urban", "regional", "continental"]);
  });

  it("应用预设：比例尺与交通方式一起换，开关不受影响", () => {
    const before = toggleFeature(defaultPrefs(), "distance");
    const after = applyScalePreset(before, "urban");
    expect(after.measure).toEqual({ scale: "urban", px: 100, km: 1, transport: "walk" });
    expect(after.features.distance).toBe(true); // 开关不该被动到
  });

  it("推荐交通方式按尺度排序：城市先给步行/自行车/公交/开车", () => {
    expect(recommendedModes("urban").slice(0, 4).map((m) => m.id)).toEqual([
      "walk",
      "bike",
      "transit",
      "car",
    ]);
    // 长途方式仍在列表里（可选，不能被藏掉）
    expect(recommendedModes("urban").map((m) => m.id)).toContain("airship");
    expect(recommendedModes("continental").slice(0, 3).map((m) => m.id)).toEqual([
      "walk",
      "horse",
      "cart",
    ]);
  });

  it("未知尺度退化成地区预设", () => {
    expect(scalePreset("火星").id).toBe("regional");
  });
});

describe("测距与行程时间：单位要跟着题材尺度走", () => {
  it("像素距离", () => {
    expect(pixelDistance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });

  it("按比例尺换算公里（地区尺度 100px = 10km）", () => {
    expect(kmFromPixels(100, DEFAULT_MEASURE)).toBe(10);
    expect(kmFromPixels(250, DEFAULT_MEASURE)).toBe(25);
    expect(distanceKm({ x: 0, y: 0 }, { x: 300, y: 400 }, DEFAULT_MEASURE)).toBe(50);
  });

  it("比例尺非法时退化成默认值而不是 Infinity", () => {
    expect(Number.isFinite(kmFromPixels(100, { px: 0, km: 10 }))).toBe(true);
    expect(Number.isFinite(kmFromPixels(100, { px: 100, km: 0 }))).toBe(true);
  });

  it("城市尺度：几百米也要给出分钟级的读数（这是修掉的老问题）", () => {
    // 城市预设：100 像素 = 1 公里；800 像素 ≈ 8 公里
    const measure = { px: 100, km: 1 };
    expect(formatKm(kmFromPixels(800, measure))).toBe("8.0 公里");
    const km = kmFromPixels(800, measure);
    expect(formatDuration(travelMinutes(km, "walk"), "walk")).toBe("约 1.6 小时");
    // 家→学校这种：300 像素 ≈ 3 公里 → 步行 36 分钟（而不是"不到半天"）
    expect(formatLegLabel(kmFromPixels(300, measure), "walk")).toBe("约 3.0 公里 · 步行约 36 分钟");
    // 更近的一段：600 米 → 米 + 分钟
    expect(formatLegLabel(kmFromPixels(60, measure), "walk")).toBe("约 600 米 · 步行约 7 分钟");
  });

  it("城市尺度的短途交通：公交含等车开销，比步行更快", () => {
    const km = kmFromPixels(800, { px: 100, km: 1 }); // 8 公里
    const walkMin = travelMinutes(km, "walk");
    const transitMin = travelMinutes(km, "transit");
    expect(transitMin).toBeLessThan(walkMin);
    expect(travelMinutes(0.2, "transit")).toBeGreaterThan(0); // 等车 8 分钟仍在
    expect(formatDuration(transitMin, "transit")).toBe("约 27 分钟"); // 8/25*60+8
  });

  it("大陆尺度：长距离按天，且按「一天走几小时」折算", () => {
    const measure = { px: 100, km: 100 }; // 异世界预设
    const km = kmFromPixels(400, measure); // 400 公里
    expect(formatKm(km)).toBe("400 公里");
    // 骑马 12 km/h、每天 7 小时、含 5 分钟备马：400 km → 33.4 小时 → 4.8 天
    expect(formatLegLabel(km, "horse")).toBe("约 400 公里 · 骑马约 4.8 天");
    expect(travelDays(km, "horse")).toBeCloseTo(((400 / 12) * 60 + 5) / 60 / 7, 5);
  });

  it("时长单位自适应：分钟 → 小时 → 天", () => {
    expect(formatDuration(0.2, "walk")).toBe("不到 1 分钟");
    expect(formatDuration(8, "walk")).toBe("约 8 分钟");
    expect(formatDuration(59.4, "walk")).toBe("约 59 分钟");
    expect(formatDuration(90, "walk")).toBe("约 1.5 小时");
    // 半天以内仍然用小时（开车 10 小时 = 约 10.0 小时，而不是 0.8 天）
    expect(formatDuration(600, "car")).toBe("约 10.0 小时");
    // 超过 12 小时才折算成天，且按该方式每天的行程小时数
    expect(formatDuration(60 * 13, "car")).toBe("约 1.1 天"); // 13h / 12h 每天
    // 10 天以上取整（与 10 天以下保留一位小数一致）
    expect(formatDuration(60 * 80, "walk")).toBe("约 10 天"); // 80h / 8h 每天
  });

  it("未知方式退化成第一个（步行），不能抛", () => {
    expect(transportById("不存在").id).toBe(TRANSPORT_MODES[0].id);
    expect(Number.isFinite(travelMinutes(10, "不存在"))).toBe(true);
  });

  it("一行读法", () => {
    expect(formatLegLabel(8, "walk")).toBe("约 8.0 公里 · 步行约 1.6 小时");
    expect(formatLegLabel(8, "walk", { includeKm: false })).toBe("步行约 1.6 小时");
  });
});
