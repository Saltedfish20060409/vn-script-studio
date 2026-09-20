/**
 * 地图的"按需功能"开关。
 *
 * 为什么需要：地图里有些能力（手绘、距离、区域、图层…）是**特定题材才用得上**的，
 * 不该占默认界面的注意力。这里把"默认要"和"按需开"分开，并且：
 *
 * - **关掉只隐藏，不删数据**：关掉画笔不等于删掉已画的线，重新打开原样回来；
 * - 未知/新增的 id 一律落回默认值（将来加功能时老配置不会炸）；
 * - 存在本机（localStorage）：这是"我怎么用界面"的偏好，不是作品数据。
 */

export type MapFeatureId = "strokes" | "distance";

export type MapFeatureDef = {
  id: MapFeatureId;
  label: string;
  hint: string;
  /** 默认是否开启。已有的能力保持开着（不打扰老用户），新能力默认关。 */
  defaultOn: boolean;
};

export const MAP_FEATURES: MapFeatureDef[] = [
  {
    id: "strokes",
    label: "手绘与标记",
    hint: "画笔随手画路线/地形，以及橡皮和笔迹图层。关掉只是隐藏，笔迹仍保留。",
    defaultOn: true,
  },
  {
    id: "distance",
    label: "距离与行程时间",
    hint: "按比例尺算出两地距离，并按交通方式给「要走几天」，避免剧情里的路程自相矛盾。",
    defaultOn: false,
  },
];

/** 距离功能的比例尺与交通方式（和开关一起存在本机）。 */
export type MapMeasurePrefs = {
  /** 多少像素算一段距离（世界坐标的像素） */
  px: number;
  /** 这段像素等于多少公里 */
  km: number;
  /** 默认交通方式 id（见 mapDistance 的 TRANSPORT_MODES） */
  transport: string;
};

export type MapPrefs = {
  features: Record<MapFeatureId, boolean>;
  measure: MapMeasurePrefs;
};

const STORE_KEY = "vnss-map-features-v1";

export const DEFAULT_MEASURE: MapMeasurePrefs = { px: 100, km: 10, transport: "walk" };

export function defaultFeatures(): Record<MapFeatureId, boolean> {
  const out = {} as Record<MapFeatureId, boolean>;
  for (const f of MAP_FEATURES) out[f.id] = f.defaultOn;
  return out;
}

export function defaultPrefs(): MapPrefs {
  return { features: defaultFeatures(), measure: { ...DEFAULT_MEASURE } };
}

/** 把存下来的（可能是老版本/坏数据）配置收敛成完整配置。 */
export function resolvePrefs(raw: unknown): MapPrefs {
  const base = defaultPrefs();
  if (!raw || typeof raw !== "object") return base;
  const record = raw as {
    features?: Record<string, unknown>;
    measure?: Record<string, unknown>;
  };
  if (record.features && typeof record.features === "object") {
    for (const f of MAP_FEATURES) {
      const value = record.features[f.id];
      if (typeof value === "boolean") base.features[f.id] = value;
    }
  }
  const m = record.measure;
  if (m && typeof m === "object") {
    const px = Number(m.px);
    const km = Number(m.km);
    if (Number.isFinite(px) && px > 0) base.measure.px = px;
    if (Number.isFinite(km) && km > 0) base.measure.km = km;
    if (typeof m.transport === "string" && m.transport) base.measure.transport = m.transport;
  }
  return base;
}

const hasStorage = (s?: Pick<Storage, "getItem"> | null): boolean => {
  if (s) return true;
  try {
    return typeof window !== "undefined" && Boolean(window.localStorage);
  } catch {
    return false;
  }
};

export function loadMapPrefs(storage?: Pick<Storage, "getItem"> | null): MapPrefs {
  let store = storage ?? null;
  if (!storage && hasStorage()) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  if (!store) return defaultPrefs();
  try {
    const raw = store.getItem(STORE_KEY);
    if (!raw) return defaultPrefs();
    return resolvePrefs(JSON.parse(raw));
  } catch {
    return defaultPrefs();
  }
}

export function saveMapPrefs(
  prefs: MapPrefs,
  storage?: Pick<Storage, "setItem"> | null
): void {
  let store = storage ?? null;
  if (!storage && hasStorage()) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  try {
    store?.setItem(STORE_KEY, JSON.stringify(prefs));
  } catch {
    /* 隐私模式写不进去也不该崩 */
  }
}

export function toggleFeature(prefs: MapPrefs, id: MapFeatureId): MapPrefs {
  return {
    ...prefs,
    features: { ...prefs.features, [id]: !prefs.features[id] },
  };
}

export function setMeasurePrefs(prefs: MapPrefs, patch: Partial<MapMeasurePrefs>): MapPrefs {
  return { ...prefs, measure: { ...prefs.measure, ...patch } };
}
