/** Persist writing focus mode + timer prefs + daily stats. */

export type FocusTimerMode = "up" | "down";

export type FocusTimerPrefs = {
  mode: FocusTimerMode;
  /** Countdown length in minutes (ignored for count-up). */
  minutes: number;
  /** Suggested break length after countdown ends (minutes). */
  restMinutes: number;
};

const MODE_KEY = "vnss-focus-mode-v1";
const PREFS_KEY = "vnss-focus-timer-prefs-v1";
const DAY_KEY = "vnss-focus-day-v1";

type DayStats = { date: string; seconds: number };

export function loadFocusMode(): boolean {
  try {
    return localStorage.getItem(MODE_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveFocusMode(on: boolean) {
  try {
    localStorage.setItem(MODE_KEY, on ? "1" : "0");
  } catch {
    /* ignore quota */
  }
}

function clampMinutes(n: number, fallback: number): number {
  return Number.isFinite(n) && n >= 1 && n <= 180 ? Math.round(n) : fallback;
}

export function loadFocusTimerPrefs(): FocusTimerPrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return { mode: "up", minutes: 25, restMinutes: 5 };
    const parsed = JSON.parse(raw) as Partial<FocusTimerPrefs>;
    return {
      mode: parsed.mode === "down" ? "down" : "up",
      minutes: clampMinutes(Number(parsed.minutes), 25),
      restMinutes: clampMinutes(Number(parsed.restMinutes), 5),
    };
  } catch {
    return { mode: "up", minutes: 25, restMinutes: 5 };
  }
}

export function saveFocusTimerPrefs(prefs: FocusTimerPrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore quota */
  }
}

function todayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function readDayStats(): DayStats {
  try {
    const raw = localStorage.getItem(DAY_KEY);
    if (!raw) return { date: todayIso(), seconds: 0 };
    const parsed = JSON.parse(raw) as Partial<DayStats>;
    const date = typeof parsed.date === "string" ? parsed.date : todayIso();
    const seconds = Number(parsed.seconds);
    if (date !== todayIso()) return { date: todayIso(), seconds: 0 };
    return {
      date,
      seconds: Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0,
    };
  } catch {
    return { date: todayIso(), seconds: 0 };
  }
}

export function loadTodayFocusSeconds(): number {
  return readDayStats().seconds;
}

export function addTodayFocusSeconds(delta: number) {
  if (!Number.isFinite(delta) || delta <= 0) return loadTodayFocusSeconds();
  const cur = readDayStats();
  const next: DayStats = {
    date: todayIso(),
    seconds: cur.seconds + Math.floor(delta),
  };
  try {
    localStorage.setItem(DAY_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  return next.seconds;
}

/** Count script characters (exclude whitespace). */
export function countFocusChars(text: string): number {
  return (text || "").replace(/\s+/g, "").length;
}

export async function enterFullscreen(el?: Element | null) {
  const target = el ?? document.documentElement;
  if (document.fullscreenElement) return;
  const req =
    target.requestFullscreen?.bind(target) ||
    (
      target as HTMLElement & {
        webkitRequestFullscreen?: () => Promise<void> | void;
      }
    ).webkitRequestFullscreen?.bind(target);
  if (req) await Promise.resolve(req());
}

export async function exitFullscreen() {
  if (!document.fullscreenElement) return;
  const doc = document as Document & {
    webkitExitFullscreen?: () => Promise<void> | void;
  };
  const exit =
    document.exitFullscreen?.bind(document) ||
    doc.webkitExitFullscreen?.bind(document);
  if (exit) await Promise.resolve(exit());
}

export function formatFocusClock(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}
