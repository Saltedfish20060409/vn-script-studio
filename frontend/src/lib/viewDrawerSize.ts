/**
 * 视图抽屉的宽度策略。
 *
 * 背景（用户反馈）：Word 壳重构把设定 / 角色工坊 / 地图 / 剧情状态 / 结构分析
 * 一律塞进 `min(52vw, 560px)` 的右侧抽屉，只有地图被特批成宽抽屉。结果是
 * **本来就吃宽度的面板被挤成一列**——角色卡的 `minmax(270px,1fr)` 网格在 560px 下
 * 只剩一两列，结构分析的表和角色工坊的几条 rail 更挤。用户的原话是
 * "不如前版看着详细易懂"。
 *
 * 所以这里把"哪个面板默认多宽"变成**一处可读的规则**（而不是散在 JSX 里的三元表达式），
 * 并允许作者用抽屉标题栏的「铺满 / 收窄」开关覆盖它。
 *
 * 为什么不是一律 wide：写作时多数时候只是"瞥一眼设定"，
 * 一上来就占 92vw 会把稿纸整个挤走——那是另一个方向的退步。
 */

export type ViewSize = "narrow" | "wide" | "full";

export type ViewPanelId = "world" | "voice" | "map" | "system" | "analysis";

/**
 * 各面板的默认宽度档。判断依据是"这个面板里的东西按列排会不会塌"：
 *
 * - `analysis`（结构分析）：表格 + 卡片 + 弧线视图，整页时是多列并排 → wide
 * - `voice`（角色工坊）：自带 rail + 编辑区，560px 会挤成一列 → wide
 * - `world`（设定）：角色卡网格 `minmax(270px,1fr)`，窄抽屉只剩 1 列 → wide
 * - `map`（地图）：画布，最吃宽度 → wide（重构前也是唯一特批的）
 * - `system`（剧情状态）：变量/状态机是清单式，窄栏够用 → narrow
 */
export const VIEW_DEFAULT_SIZE: Readonly<Record<ViewPanelId, ViewSize>> = {
  analysis: "wide",
  voice: "wide",
  world: "wide",
  map: "wide",
  system: "narrow",
};

/** 用户显式点过「铺满 / 收窄」时记住的选择：panel → 档位。 */
export type ViewSizeOverrides = Partial<Record<ViewPanelId, ViewSize>>;

export function isViewSize(value: unknown): value is ViewSize {
  return value === "narrow" || value === "wide" || value === "full";
}

export function isViewPanelId(value: unknown): value is ViewPanelId {
  return (
    value === "world" ||
    value === "voice" ||
    value === "map" ||
    value === "system" ||
    value === "analysis"
  );
}

/**
 * 生效档位：有显式选择就用它，否则用该面板的默认档。
 *
 * 非法值一律当作"没选过"（放宽），不要抛错——localStorage 里的东西是用户可改的，
 * 一个坏值不该让抽屉打不开。
 */
export function resolveViewSize(
  panel: ViewPanelId,
  overrides?: ViewSizeOverrides | null
): ViewSize {
  const picked = overrides?.[panel];
  return isViewSize(picked) ? picked : VIEW_DEFAULT_SIZE[panel];
}

/**
 * 点「铺满 / 收窄」后的下一档。
 *
 * 语义就是二值切换：**当前是铺满 → 回到该面板默认档；否则 → 铺满**。
 * 这样"收窄"永远回到这个面板本来该有的宽度，而不是一律 560px
 * （否则从铺满回来会把"结构分析"也压成窄栏，等于把默认值丢掉）。
 */
export function nextViewSize(panel: ViewPanelId, current: ViewSize): ViewSize {
  return current === "full" ? VIEW_DEFAULT_SIZE[panel] : "full";
}

/** 把 localStorage 里读到的原始对象过滤成合法的 overrides（坏值丢弃）。 */
export function sanitizeViewSizeOverrides(raw: unknown): ViewSizeOverrides {
  if (!raw || typeof raw !== "object") return {};
  const out: ViewSizeOverrides = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (isViewPanelId(key) && isViewSize(value)) out[key] = value;
  }
  return out;
}

/** localStorage 键：与本设备其它偏好（章节大纲折叠、写作辅助条折叠）同一类。 */
export const VIEW_SIZE_KEY = "vnss-view-drawer-size";

/** 读本机记住的宽度选择；隐私模式/坏 JSON 都退回"没选过"。 */
export function loadViewSizeOverrides(): ViewSizeOverrides {
  try {
    const raw = localStorage.getItem(VIEW_SIZE_KEY);
    if (!raw) return {};
    return sanitizeViewSizeOverrides(JSON.parse(raw));
  } catch {
    return {};
  }
}

export function saveViewSizeOverrides(overrides: ViewSizeOverrides): void {
  try {
    localStorage.setItem(VIEW_SIZE_KEY, JSON.stringify(sanitizeViewSizeOverrides(overrides)));
  } catch {
    /* 隐私模式下写不了：这次会话内仍然生效，不弹错 */
  }
}
