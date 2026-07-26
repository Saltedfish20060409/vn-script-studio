export type ThemeMode = "day" | "night";

export type CraftModePreference = "auto" | "off" | "lite" | "full";

export interface AppSettings {
  theme: ThemeMode;
  /** UI font scale, 1 = 100% */
  fontScale: number;
  apiKey: string;
  apiBaseUrl: string;
  apiModel: string;
  /** Agent writing-craft injection preference */
  craftMode: CraftModePreference;
  /** Second-pass self-review for continue/scene etc. */
  selfReview: "auto" | "on" | "off";
  /** Critic model override — leave empty to reuse writer model */
  criticApiKey: string;
  criticApiBaseUrl: string;
  criticApiModel: string;
  /** data URL or empty */
  bgImage: string;
  bgScale: number;
  bgOpacity: number;
  /** Pan offset in px from center */
  bgPanX: number;
  bgPanY: number;
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: "day",
  fontScale: 1,
  apiKey: "",
  apiBaseUrl: "https://api.deepseek.com",
  apiModel: "deepseek-chat",
  craftMode: "auto",
  selfReview: "auto",
  criticApiKey: "",
  criticApiBaseUrl: "",
  criticApiModel: "",
  bgImage: "",
  bgScale: 1,
  bgOpacity: 0.35,
  bgPanX: 0,
  bgPanY: 0,
};

const KEY = "vnss-settings-v1";

export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(s: AppSettings) {
  localStorage.setItem(KEY, JSON.stringify(s));
}

export function applySettingsToDom(s: AppSettings) {
  const root = document.documentElement;
  root.dataset.theme = s.theme;
  root.style.setProperty(
    "--font-scale",
    String(s.fontScale > 0 ? s.fontScale : 1)
  );
  root.style.setProperty("--bg-custom-opacity", String(s.bgOpacity));
  root.style.setProperty("--bg-custom-scale", String(s.bgScale));
  root.style.setProperty("--bg-custom-pan-x", `${s.bgPanX}px`);
  root.style.setProperty("--bg-custom-pan-y", `${s.bgPanY}px`);
  if (s.bgImage) {
    root.style.setProperty("--bg-custom-image", `url(${JSON.stringify(s.bgImage)})`);
    root.dataset.customBg = "1";
  } else {
    root.style.removeProperty("--bg-custom-image");
    delete root.dataset.customBg;
  }
}
