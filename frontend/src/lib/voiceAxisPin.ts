/**
 * 角色工坊「定口吻」的方向标签：**勾了标签 ≠ 这一轮要用标签**。
 *
 * 背景（用户反馈）：勾过一两次标签之后，三组方向永远是那三个。
 * 根因是两个按钮调的是同一个生成函数，而它无条件把勾选发出去；后端一收到 3 个
 * `pinned` 轴就直接命令模型「必须严格使用这三条轴（一一对应三组），勿改名」
 * （`app/core/character_voice/generate.py` 的 `_build_axes_brief`），于是方向被钉死，
 * 与模型无关。
 *
 * 所以"这一轮要不要用标签"必须是一个**显式**决定，由按下的是哪个按钮给出，
 * 不能由"勾没勾"隐含决定。这里把它抽成纯函数，好在 vitest 里钉住——
 * 那条按钮链（VoiceScenarioControls → VoiceShapeZone → CharacterWorkshop）
 * 本身没有组件测试可用。
 */
import type { VoiceAxisTag } from "../api/voice";

/** 会用到方向轴的形态；长场次与手写金句不用轴。 */
const PINNABLE_MODES = ["preference", "interview"] as const;

export type PinnableShapeMode = (typeof PINNABLE_MODES)[number];
export type VoiceShapeMode = PinnableShapeMode | "scene" | "manual";

/** 与界面勾选上限一致；后端 `axes_from_tag_ids` 也只取前 3 条。 */
export const MAX_PINNED_TAGS = 3;

/**
 * 这一轮该发哪些 `axis_tags`。
 *
 * 只有「按标签重开」传 `pinTags = true`。**主按钮必须传 false**——它叫「生成三组」，
 * 界面上写明"默认按角色卡出本轮三轴"，那就不能偷偷把上次勾的标签再钉一遍。
 *
 * 返回 `undefined`（JSON 里省略该字段）而不是 `[]`：两者后端等价（`axis_tags`
 * 默认空列表），但省略更能表达"这一轮不涉及标签"。
 */
export function axisTagsForGeneration(
  shapeMode: VoiceShapeMode,
  pinTags: boolean,
  selectedTagIds: string[]
): string[] | undefined {
  if (!(PINNABLE_MODES as readonly string[]).includes(shapeMode)) return undefined;
  if (!pinTags) return undefined;
  const picked = selectedTagIds.slice(0, MAX_PINNED_TAGS);
  return picked.length ? picked : undefined;
}

/** 后端回的 `pinnedTags` 是标签 id；翻成人看的名字。查不到的 id 原样保留。 */
export function pinnedTagLabels(
  pinnedIds: string[] | undefined,
  pool: VoiceAxisTag[]
): string[] {
  if (!pinnedIds?.length) return [];
  const byId = new Map(pool.map((t) => [t.id, t.label]));
  return pinnedIds.map((id) => byId.get(id) ?? id);
}

/**
 * 结果区那一行：点明"这三组的方向是被你自己钉的"，并给出怎么换。
 * 没有钉标签时返回空串（不显示任何东西）。
 */
export function pinnedTagsNote(
  pinnedIds: string[] | undefined,
  pool: VoiceAxisTag[]
): string {
  const labels = pinnedTagLabels(pinnedIds, pool);
  if (!labels.length) return "";
  return (
    `本次三组的方向由你勾的标签钉住：${labels.join("、")}。` +
    "想换方向就点「生成三组」（它会按角色卡重出三轴），或清空标签。"
  );
}

/**
 * 勾了标签但这一轮没用上时的说明。
 *
 * 分开成一条是因为修复之后会出现一个新的困惑状态："我明明勾了，怎么没按标签来？"
 * 不解释的话，作者会以为勾选坏了。已经钉过标签时返回空串（那时显示 `pinnedTagsNote`）。
 */
export function tagSelectionHint(
  selectedTagIds: string[],
  pinnedIds: string[] | undefined
): string {
  if (!selectedTagIds.length) return "";
  if (pinnedIds?.length) return "";
  return (
    `已勾 ${selectedTagIds.length} 个方向标签，但本次生成没用到它们——` +
    "点「按标签重开」才会按标签出三组。"
  );
}
