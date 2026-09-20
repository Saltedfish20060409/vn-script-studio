/**
 * 交给 AI 的资料块「按需带上」开关。
 *
 * 为什么需要：工具比"网页端裸聊"差的常见原因不是模型，而是**塞了太多无关资料**——
 * 聊天里用户只贴相关的那一段，工具却把 bible、台账、立绘、变量一起灌进去。这里让作者
 * 一眼看到有哪些块、并且能当场摘掉（只影响这一次会话，不改工程数据）。
 *
 * key 与后端 `core/agent_context.EXCLUDABLE_SECTIONS` 一一对应；后端会忽略未知 key，
 * 所以这里多一个少一个也不会报错（只是那个勾没用）。
 */

export type AgentSection = { key: string; label: string };

export const AGENT_SECTIONS: AgentSection[] = [
  { key: "bible", label: "设定 bible（世界观 / 大纲 / 背景）" },
  { key: "lore", label: "设定条目" },
  { key: "longMemory", label: "长程章节记忆" },
  { key: "craft", label: "ACG 工艺卡" },
  { key: "referenceDocs", label: "上传的参考资料" },
  { key: "chatMemory", label: "对话滚动记忆" },
  { key: "index", label: "章节目录与本地摘要" },
  { key: "characters", label: "角色卡" },
  { key: "relations", label: "角色关系" },
  { key: "locations", label: "地点与通路" },
  { key: "variables", label: "变量 / 状态机" },
  { key: "sprites", label: "立绘" },
  { key: "otherChapters", label: "其他章节摘录" },
  { key: "style", label: "文风记忆" },
];

const STORE_KEY = "vnss-agent-exclude-v1";

export function loadExcludedSections(
  storage?: Pick<Storage, "getItem"> | null
): string[] {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  if (!store) return [];
  try {
    const raw = store.getItem(STORE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((k): k is string => typeof k === "string");
  } catch {
    return [];
  }
}

export function saveExcludedSections(
  keys: string[],
  storage?: Pick<Storage, "setItem"> | null
): void {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  try {
    store?.setItem(STORE_KEY, JSON.stringify(keys));
  } catch {
    /* 隐私模式写不进去也不该崩 */
  }
}

export function toggleSection(keys: string[], key: string): string[] {
  return keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key];
}

/** 给界面用的一句话：这次省掉了哪些资料（空数组 → 空字符串） */
export function excludedSummary(keys: string[]): string {
  if (keys.length === 0) return "";
  return `本次不带：${keys.length} 项`;
}
