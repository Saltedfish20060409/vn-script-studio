import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  addTodayFocusSeconds,
  countFocusChars,
  formatFocusClock,
  loadTodayFocusSeconds,
  type FocusTimerMode,
  type FocusTimerPrefs,
} from "../lib/focusMode";
import styles from "./FocusChrome.module.css";

type Props = {
  setupOpen: boolean;
  initialPrefs: FocusTimerPrefs;
  onSetupCancel: () => void;
  onSetupConfirm: (prefs: FocusTimerPrefs) => void;
  active: boolean;
  prefs: FocusTimerPrefs | null;
  /** Live editor text for session char delta */
  draft: string;
  onExit: () => void;
};

export function FocusChrome({
  setupOpen,
  initialPrefs,
  onSetupCancel,
  onSetupConfirm,
  active,
  prefs,
  draft,
  onExit,
}: Props) {
  const titleId = useId();
  const [mode, setMode] = useState<FocusTimerMode>(initialPrefs.mode);
  const [minutes, setMinutes] = useState(initialPrefs.minutes);
  const [restMinutes, setRestMinutes] = useState(initialPrefs.restMinutes);
  const [custom, setCustom] = useState(String(initialPrefs.minutes));
  const [elapsed, setElapsed] = useState(0);
  const [ended, setEnded] = useState(false);
  const [flash, setFlash] = useState(false);
  const [todaySec, setTodaySec] = useState(() => loadTodayFocusSeconds());
  const [baselineChars, setBaselineChars] = useState(0);
  const [resting, setResting] = useState(false);
  const [restLeft, setRestLeft] = useState(0);
  const [restDismissed, setRestDismissed] = useState(false);
  const creditedRef = useRef(0);

  useEffect(() => {
    if (!setupOpen) return;
    setMode(initialPrefs.mode);
    setMinutes(initialPrefs.minutes);
    setRestMinutes(initialPrefs.restMinutes);
    setCustom(String(initialPrefs.minutes));
  }, [setupOpen, initialPrefs]);

  useEffect(() => {
    if (!active || !prefs) {
      setElapsed(0);
      setEnded(false);
      setFlash(false);
      setResting(false);
      setRestLeft(0);
      setRestDismissed(false);
      creditedRef.current = 0;
      return;
    }
    setBaselineChars(countFocusChars(draft));
    setElapsed(0);
    setEnded(false);
    setFlash(false);
    setResting(false);
    setRestDismissed(false);
    creditedRef.current = 0;
    setTodaySec(loadTodayFocusSeconds());
    const started = Date.now();
    const id = window.setInterval(() => {
      const sec = Math.floor((Date.now() - started) / 1000);
      setElapsed(sec);
      const gain = sec - creditedRef.current;
      if (gain > 0) {
        creditedRef.current = sec;
        setTodaySec(addTodayFocusSeconds(gain));
      }
      if (prefs.mode === "down") {
        const total = prefs.minutes * 60;
        if (sec >= total) {
          setEnded(true);
          setFlash(true);
          window.clearInterval(id);
        }
      }
    }, 250);
    return () => window.clearInterval(id);
    // draft baseline only at session start
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, prefs]);

  useEffect(() => {
    if (!flash) return;
    const t = window.setTimeout(() => setFlash(false), 1200);
    return () => window.clearTimeout(t);
  }, [flash]);

  useEffect(() => {
    if (!resting) return;
    const id = window.setInterval(() => {
      setRestLeft((v) => {
        if (v <= 1) {
          window.clearInterval(id);
          setResting(false);
          return 0;
        }
        return v - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [resting]);

  const remain =
    prefs?.mode === "down" ? Math.max(0, prefs.minutes * 60 - elapsed) : elapsed;
  const clock = formatFocusClock(remain);
  // draft 是全量编辑器文本：countFocusChars 每次都要整段 regex 扫描。
  // 只在 draft/baselineChars 变化时重算，避免专注会话 250ms 定时器
  // 触发的渲染（及父组件无关重渲染）反复做全量扫描。
  const sessionChars = useMemo(
    () => Math.max(0, countFocusChars(draft) - baselineChars),
    [draft, baselineChars]
  );

  return (
    <>
      {setupOpen ? (
        <div
          className={styles.setupBackdrop}
          role="presentation"
          onClick={onSetupCancel}
        >
          <div
            className={styles.setup}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.setupMain}>
              <p className={styles.setupIdx} aria-hidden>
                FO
              </p>
              <h2 id={titleId} className={styles.setupTitle}>
                专注会话
              </h2>
              <p className={styles.setupLead}>
                将进入系统全屏，并隐藏写作界面干扰项。今日已累计{" "}
                {formatFocusClock(loadTodayFocusSeconds())}。
              </p>

              <fieldset className={styles.fieldset}>
                <legend>计时方式</legend>
                <label className={styles.radio}>
                  <input
                    type="radio"
                    name="focus-timer-mode"
                    checked={mode === "up"}
                    onChange={() => setMode("up")}
                  />
                  正计时
                </label>
                <label className={styles.radio}>
                  <input
                    type="radio"
                    name="focus-timer-mode"
                    checked={mode === "down"}
                    onChange={() => setMode("down")}
                  />
                  倒计时
                </label>
              </fieldset>

              {mode === "down" ? (
                <div className={styles.presets}>
                  <span className={styles.presetsLabel}>时长（分钟）</span>
                  <div className={styles.presetRow}>
                    {[15, 25, 45].map((n) => (
                      <button
                        key={n}
                        type="button"
                        className={minutes === n ? styles.presetOn : styles.preset}
                        onClick={() => {
                          setMinutes(n);
                          setCustom(String(n));
                        }}
                      >
                        {n}
                      </button>
                    ))}
                    <label className={styles.custom}>
                      自定义
                      <input
                        type="number"
                        min={1}
                        max={180}
                        value={custom}
                        aria-label="自定义倒计时分钟"
                        onChange={(e) => {
                          setCustom(e.target.value);
                          const n = Number(e.target.value);
                          if (Number.isFinite(n) && n >= 1 && n <= 180) {
                            setMinutes(Math.round(n));
                          }
                        }}
                      />
                    </label>
                  </div>
                </div>
              ) : (
                <p className={styles.setupHint}>正计时从 00:00 起算本场写作时长。</p>
              )}

              <div className={styles.presets}>
                <span className={styles.presetsLabel}>结束后休息（分钟）</span>
                <div className={styles.presetRow}>
                  {[3, 5, 10].map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={restMinutes === n ? styles.presetOn : styles.preset}
                      onClick={() => setRestMinutes(n)}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>

              <div className={styles.setupActions}>
                <button type="button" className={styles.ghost} onClick={onSetupCancel}>
                  取消
                </button>
                <button
                  type="button"
                  className={styles.primary}
                  onClick={() =>
                    onSetupConfirm({
                      mode,
                      minutes: mode === "down" ? minutes : 25,
                      restMinutes,
                    })
                  }
                >
                  开始全屏专注
                </button>
              </div>
              <p className={styles.setupHint}>快捷键 Ctrl+\ 也可开关专注。</p>
            </div>
          </div>
        </div>
      ) : null}

      {active && prefs ? (
        <div
          className={`${styles.bar} ${ended ? styles.barEnded : ""} ${
            flash ? styles.barFlash : ""
          }`}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          <span className={styles.barIdx} aria-hidden>
            {prefs.mode === "down" ? "DN" : "UP"}
          </span>
          <span className={styles.barClock}>{clock}</span>
          <span className={styles.barMeta}>
            <span className={styles.barLabel}>
              {ended ? "本场结束" : prefs.mode === "down" ? "倒计时" : "正计时"}
            </span>
            <span className={styles.barStat}>+{sessionChars} 字</span>
            <span className={styles.barStat}>今日 {formatFocusClock(todaySec)}</span>
          </span>
          <button
            type="button"
            className={styles.barExit}
            onClick={onExit}
            aria-label="退出专注模式"
          >
            退出
          </button>
        </div>
      ) : null}

      {active && ended && !restDismissed && !resting && prefs ? (
        <div className={styles.restBanner} role="dialog" aria-label="休息提醒">
          <span className={styles.restIdx} aria-hidden>
            BR
          </span>
          <div className={styles.restBody}>
            <strong>本场结束</strong>
            <span>建议休息 {prefs.restMinutes} 分钟，也可忽略继续写。</span>
          </div>
          <button
            type="button"
            className={styles.primary}
            onClick={() => {
              setResting(true);
              setRestLeft(prefs.restMinutes * 60);
            }}
          >
            开始休息
          </button>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => setRestDismissed(true)}
          >
            忽略
          </button>
        </div>
      ) : null}

      {active && resting ? (
        <div className={styles.restBanner} role="status" aria-live="polite">
          <span className={styles.restIdx} aria-hidden>
            BR
          </span>
          <div className={styles.restBody}>
            <strong>休息中</strong>
            <span className={styles.barClock}>{formatFocusClock(restLeft)}</span>
          </div>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => {
              setResting(false);
              setRestDismissed(true);
            }}
          >
            结束休息
          </button>
        </div>
      ) : null}
    </>
  );
}
