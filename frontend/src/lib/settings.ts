export type ThemeMode = "day" | "night";

/** Appearance + tool background only. LLM credentials live on the server. */
export interface AppSettings {
  theme: ThemeMode;
  /** UI font scale, 1 = 100% */
  fontScale: number;
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
  bgImage: "",
  bgScale: 1,
  bgOpacity: 0.35,
  bgPanX: 0,
  bgPanY: 0,
};

const APPEARANCE_CACHE_KEY = "vnss-appearance-cache-v1";

export type AppearanceCache = AppSettings;

export function loadAppearanceCache(): AppearanceCache | null {
  try {
    const raw = localStorage.getItem(APPEARANCE_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AppSettings>;
    return {
      theme: parsed.theme === "night" ? "night" : "day",
      fontScale: parsed.fontScale || 1,
      bgImage: parsed.bgImage || "",
      bgScale: parsed.bgScale || 1,
      bgOpacity: parsed.bgOpacity ?? 0.35,
      bgPanX: parsed.bgPanX || 0,
      bgPanY: parsed.bgPanY || 0,
    };
  } catch {
    return null;
  }
}

export function saveAppearanceCache(s: AppSettings) {
  try {
    localStorage.setItem(APPEARANCE_CACHE_KEY, JSON.stringify(s));
  } catch {
    /* ignore quota */
  }
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

export interface ServerSettingsOut {
  theme: string;
  font_scale: number;
  bg_image: string;
  bg_scale: number;
  bg_opacity: number;
  bg_pan_x: number;
  bg_pan_y: number;
}

export function fromServerSettings(out: ServerSettingsOut): AppSettings {
  return {
    theme: out.theme === "night" ? "night" : "day",
    fontScale: out.font_scale || 1,
    bgImage: out.bg_image || "",
    bgScale: out.bg_scale || 1,
    bgOpacity: out.bg_opacity ?? 0.35,
    bgPanX: out.bg_pan_x || 0,
    bgPanY: out.bg_pan_y || 0,
  };
}

export function toServerSettingsPatch(s: AppSettings) {
  return {
    theme: s.theme,
    font_scale: s.fontScale,
    bg_image: s.bgImage,
    bg_scale: s.bgScale,
    bg_opacity: s.bgOpacity,
    bg_pan_x: s.bgPanX,
    bg_pan_y: s.bgPanY,
  };
}
