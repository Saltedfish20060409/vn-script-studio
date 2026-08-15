/** Local harness / pipeline preferences for Agent chat. */

export type HarnessPrefs = {
  /** Promote voice_break high → hard error on pipeline / finalize */
  voiceHard?: boolean;
  /** Run character voice check on final check / finalize (default true) */
  voiceCheck?: boolean;
  /** Max revise rounds for pipeline (0–5, default 2) */
  maxReviseRounds?: number;
  updatedAt?: number;
};

const KEY = "vnss-harness-prefs-v1";

const DEFAULTS: Required<
  Pick<HarnessPrefs, "voiceHard" | "voiceCheck" | "maxReviseRounds">
> = {
  voiceHard: false,
  voiceCheck: true,
  maxReviseRounds: 2,
};

export function getHarnessPrefs(): HarnessPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    const data = JSON.parse(raw) as HarnessPrefs;
    return {
      voiceHard: Boolean(data.voiceHard),
      voiceCheck: data.voiceCheck !== false,
      maxReviseRounds: clampRounds(data.maxReviseRounds),
      updatedAt: data.updatedAt,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function setHarnessPrefs(patch: Partial<HarnessPrefs>): HarnessPrefs {
  const prev = getHarnessPrefs();
  const next: HarnessPrefs = {
    ...prev,
    ...patch,
    maxReviseRounds: clampRounds(
      patch.maxReviseRounds ?? prev.maxReviseRounds ?? DEFAULTS.maxReviseRounds
    ),
    updatedAt: Date.now(),
  };
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  return next;
}

function clampRounds(n: unknown): number {
  const v = typeof n === "number" ? n : Number(n);
  if (!Number.isFinite(v)) return DEFAULTS.maxReviseRounds;
  return Math.max(0, Math.min(5, Math.round(v)));
}
