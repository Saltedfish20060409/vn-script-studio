/** Short companion lines for the studio mascot (审稿搭档). */

const IDLE = ["稿子还在，我不急。", "慢慢写，我在这边。", "需要第二双眼睛时叫我。"];

const CONFIRM_DANGER = [
  "这一步不好撤销，再看一眼？",
  "删了就回不来了，确认吗？",
  "危险操作——想清楚再点。",
];

const CONFIRM_SOFT = ["可以的话，点确认继续。", "改完还能再调，别紧张。"];

const SETTINGS = ["外观随便调，写作习惯最重要。", "主题换好了就专心写吧。"];

const SETTINGS_PAN = [
  "按住挪取景区，找到最舒服的构图。",
  "慢慢拖——背景会对齐你的视线。",
  "松手前我都陪着，别急着松手。",
];

const FOCUS = ["我先靠边站，专心写。", "计时开始，加油。"];

const EMPTY_MAP = [
  "这里是世界观参考台——钉地点、连通路，写的时候翻回来看。",
  "先钉几个关键场景，后面通路和气氛再补。",
];

const EMPTY_EXPORT = [
  "还没有预览。生成一次 .rpy，我帮你盯语法。",
  "点「生成 .rpy」看看编译结果。",
];

const EMPTY_ANALYSIS = [
  "这一章还没什么可分析的结构。",
  "写几个 menu / jump，分支树就会亮起来。",
];

const EMPTY_LIBRARY = [
  "先建一个工程，我等你开写。",
  "空白剧本或示例都可以，选一个开场。",
];

function pick(pool: string[]): string {
  return pool[Math.floor(Math.random() * pool.length)] || pool[0] || "";
}

export function mascotLine(
  kind:
    | "idle"
    | "confirmDanger"
    | "confirmSoft"
    | "settings"
    | "settingsPan"
    | "focus"
    | "emptyMap"
    | "emptyExport"
    | "emptyAnalysis"
    | "emptyLibrary"
): string {
  switch (kind) {
    case "confirmDanger":
      return pick(CONFIRM_DANGER);
    case "confirmSoft":
      return pick(CONFIRM_SOFT);
    case "settings":
      return pick(SETTINGS);
    case "settingsPan":
      return pick(SETTINGS_PAN);
    case "focus":
      return pick(FOCUS);
    case "emptyMap":
      return pick(EMPTY_MAP);
    case "emptyExport":
      return pick(EMPTY_EXPORT);
    case "emptyAnalysis":
      return pick(EMPTY_ANALYSIS);
    case "emptyLibrary":
      return pick(EMPTY_LIBRARY);
    default:
      return pick(IDLE);
  }
}
