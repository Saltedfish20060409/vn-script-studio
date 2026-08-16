export type ThemeMode = "day" | "night";
/** Wallpaper chrome: auto follows day→mist / night→ink. */
export type PanelGlass = "auto" | "mist" | "ink";

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
  /** Panel glass over custom wallpaper */
  panelGlass: PanelGlass;
  /** Readability scrim strength over wallpaper (0–0.85) */
  bgScrim: number;
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: "day",
  fontScale: 1,
  bgImage: "",
  bgScale: 1,
  bgOpacity: 0.35,
  bgPanX: 0,
  bgPanY: 0,
  panelGlass: "auto",
  bgScrim: 0.42,
};

const APPEARANCE_CACHE_KEY = "vnss-appearance-cache-v1";

export type AppearanceCache = AppSettings;

export function normalizePanelGlass(v: unknown): PanelGlass {
  if (v === "mist" || v === "ink" || v === "auto") return v;
  return "auto";
}

export function clampScrim(n: number): number {
  if (!Number.isFinite(n)) return 0.42;
  return Math.min(0.85, Math.max(0, n));
}

export function resolvePanelGlass(s: AppSettings): "mist" | "ink" {
  if (s.panelGlass === "mist") return "mist";
  if (s.panelGlass === "ink") return "ink";
  // auto: follow day/night so theme switch keeps meaning with wallpaper
  return s.theme === "night" ? "ink" : "mist";
}

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
      panelGlass: normalizePanelGlass(parsed.panelGlass),
      bgScrim: clampScrim(parsed.bgScrim !== undefined ? Number(parsed.bgScrim) : 0.42),
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
  const glass = resolvePanelGlass(s);
  // Glass override only with wallpaper; otherwise day/night tokens alone drive UI.
  if (s.bgImage) {
    root.dataset.panelGlass = glass;
  } else {
    delete root.dataset.panelGlass;
  }
  root.style.setProperty("--font-scale", String(s.fontScale > 0 ? s.fontScale : 1));
  root.style.setProperty("--bg-custom-opacity", String(s.bgOpacity));
  root.style.setProperty("--bg-custom-scale", String(s.bgScale));
  root.style.setProperty("--bg-custom-pan-x", `${s.bgPanX}px`);
  root.style.setProperty("--bg-custom-pan-y", `${s.bgPanY}px`);
  root.style.setProperty("--bg-scrim", String(clampScrim(s.bgScrim)));
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
  panel_glass?: string;
  bg_scrim?: number;
  /** User-level LLM credentials (masked — server never returns the raw key). */
  has_api_key?: boolean;
  api_key_masked?: string;
  api_base_url?: string;
  api_model?: string;
  has_critic_api_key?: boolean;
  critic_api_key_masked?: string;
  critic_api_base_url?: string;
  critic_api_model?: string;
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
    panelGlass: normalizePanelGlass(out.panel_glass),
    bgScrim: clampScrim(
      out.bg_scrim !== undefined && out.bg_scrim !== null ? Number(out.bg_scrim) : 0.42
    ),
  };
}

/** Merge server response with the local payload we just tried to save. */
export function mergeSettingsAfterSave(
  local: AppSettings,
  out: ServerSettingsOut
): AppSettings {
  const merged = fromServerSettings(out);
  return {
    ...merged,
    // Keep local wallpaper if server dropped a large data URL
    bgImage: local.bgImage && !merged.bgImage ? local.bgImage : merged.bgImage,
    // Always keep glass/scrim the user just chose (JSONB nested keys were getting lost)
    panelGlass: local.panelGlass,
    bgScrim: local.bgScrim,
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
    panel_glass: s.panelGlass,
    bg_scrim: s.bgScrim,
  };
}
