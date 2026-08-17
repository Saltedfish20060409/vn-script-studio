/**
 * 轻量 i18n — 文案字典 + 语言切换。
 *
 * 迁移路径：新文案先写进 messages.zh 与 messages.en，UI 用 t("key") 取词；
 * 未迁移的硬编码中文保持不变（默认 zh）。en 缺失的 key 自动回退 zh，
 * 保证任何语言下都不会出现空文案。
 */

import { useSyncExternalStore } from "react";

export type Locale = "zh" | "en";

const LOCALE_KEY = "vnss-lang";

const zh = {
  "settings.title": "设置",
  "settings.theme": "外观",
  "settings.wallpaper": "壁纸",
  "settings.usage": "用量",
  "settings.llm": "模型",
  "settings.lang": "语言",
  "settings.lang.zh": "中文",
  "settings.lang.en": "English",
  "settings.close": "关闭",
  "settings.save": "保存凭据",
  "settings.saveBusy": "保存中…",
  "settings.clearMainKey": "清除主 Key",
  "settings.refresh": "刷新",
  "settings.testConn": "测试连接",
  "settings.testing": "测试中…",
  "settings.activeModel": "当前生效：{model}",
  "settings.activeUser": "使用你的 Key",
  "settings.activeServer": "使用服务端配置",
  "settings.preset": "模型预设",
  "settings.presetPick": "选择预设快速填入…",
  "settings.apiKey": "主模型 API Key",
  "settings.baseUrl": "Base URL",
  "settings.model": "模型名",
  "settings.criticKey": "评审模型 API Key",
  "settings.criticBaseUrl": "评审 Base URL",
  "settings.criticModel": "评审模型名",
  "settings.criticHint": "可选：独立的评审模型（critic，改稿对照时使用）。",
  "settings.llmNote":
    "配置你自己的模型 Key 后，AI 请求将优先使用该 Key（按账号隔离，服务端加密存储）。留空则回退服务端环境变量配置。",
  "common.cancel": "取消",
  "common.save": "保存",
  "common.ok": "好的",
  "common.error": "出错了",
  "nav.write": "写作",
  "nav.map": "地图",
  "nav.project": "项目",
  "nav.help": "帮助",
  "nav.system": "系统",
};

const en: Record<keyof typeof zh, string> = {
  "settings.title": "Settings",
  "settings.theme": "Appearance",
  "settings.wallpaper": "Wallpaper",
  "settings.usage": "Usage",
  "settings.llm": "Models",
  "settings.lang": "Language",
  "settings.lang.zh": "中文",
  "settings.lang.en": "English",
  "settings.close": "Close",
  "settings.save": "Save credentials",
  "settings.saveBusy": "Saving…",
  "settings.clearMainKey": "Clear main key",
  "settings.refresh": "Refresh",
  "settings.testConn": "Test connection",
  "settings.testing": "Testing…",
  "settings.activeModel": "Active: {model}",
  "settings.activeUser": "Using your key",
  "settings.activeServer": "Using server config",
  "settings.preset": "Model preset",
  "settings.presetPick": "Pick a preset to fill…",
  "settings.apiKey": "Main model API key",
  "settings.baseUrl": "Base URL",
  "settings.model": "Model name",
  "settings.criticKey": "Critic model API key",
  "settings.criticBaseUrl": "Critic base URL",
  "settings.criticModel": "Critic model name",
  "settings.criticHint":
    "Optional separate review model (used when comparing revisions).",
  "settings.llmNote":
    "Your own model key is preferred when set (per-account, encrypted at rest). Empty falls back to the server environment.",
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.ok": "OK",
  "common.error": "Something went wrong",
  "nav.write": "Write",
  "nav.map": "Map",
  "nav.project": "Project",
  "nav.help": "Help",
  "nav.system": "System",
};

type Messages = typeof zh;

const DICTS: Record<Locale, Messages> = { zh, en };

/** Exported for tests: every zh key must exist in en. */
export function enCoversZh(): boolean {
  const zhKeys = Object.keys(zh);
  return zhKeys.every((k) => Object.prototype.hasOwnProperty.call(en, k));
}

export function detectLocale(): Locale {
  try {
    const saved = localStorage.getItem(LOCALE_KEY);
    if (saved === "zh" || saved === "en") return saved;
  } catch {
    /* storage unavailable */
  }
  try {
    const nav = navigator.language?.toLowerCase() ?? "";
    return nav.startsWith("zh") ? "zh" : "en";
  } catch {
    return "zh";
  }
}

export function setLocale(locale: Locale): void {
  try {
    localStorage.setItem(LOCALE_KEY, locale);
  } catch {
    /* ignore */
  }
}

let currentLocale: Locale = detectLocale();
const listeners = new Set<() => void>();

export function getLocale(): Locale {
  return currentLocale;
}

/** Subscribe to locale changes; returns an unsubscribe function. */
export function subscribeLocale(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function changeLocale(locale: Locale): void {
  if (locale === currentLocale) return;
  currentLocale = locale;
  setLocale(locale);
  listeners.forEach((fn) => fn());
}

/** Reactive locale for React components (re-renders on change). */
export function useLocale(): Locale {
  return useSyncExternalStore(subscribeLocale, getLocale, getLocale);
}

/** Translate a key with {param} substitution; falls back to zh on missing key. */
export function t(key: string, params?: Record<string, string | number>): string {
  const dict = DICTS[currentLocale];
  let text: string | undefined = (dict as Record<string, string>)[key];
  if (text === undefined) text = (zh as Record<string, string>)[key];
  if (text === undefined) return key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replaceAll(`{${k}}`, String(v));
    }
  }
  return text;
}
