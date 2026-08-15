import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import {
  applySettingsToDom,
  DEFAULT_SETTINGS,
  loadAppearanceCache,
} from "../lib/settings";
import { MascotFigure } from "../components/MascotFigure";
import { MASCOT_MOODS, type MascotMood } from "../lib/mascotArt";
import { mascotLine } from "../lib/mascotCopy";
import styles from "./LoginPage.module.css";

type Mode = "login" | "register";

const LOGIN_MOOD_CYCLE: MascotMood[] = MASCOT_MOODS.filter((m) => m !== "focus");

const MOOD_LINE: Partial<Record<MascotMood, string>> = {
  idle: "点我换表情，先模拟看板娘站桩。",
  think: "在想你的下一章怎么写…",
  cheer: "写得不错的话，我会这样笑。",
  angel: "小天使模式——夸你两句也可以。",
  wince: "这句有点尬，要不改改？",
  angry: "说明书腔太多，我有点火。",
  fluster: "等等，设定是不是对不上？",
  worry: "这一章节奏我有点担心。",
  puzzled: "这里的分支……我没太看懂。",
};

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hasWallpaper, setHasWallpaper] = useState(false);
  const [mascotMood, setMascotMood] = useState<MascotMood>("idle");
  const [mascotSpeech, setMascotSpeech] = useState(
    () => MOOD_LINE.idle || mascotLine("idle")
  );

  const redirectTo =
    (location.state as { from?: string } | null)?.from || "/";

  // Align login chrome with last-used studio appearance (local cache)
  useEffect(() => {
    const cached = loadAppearanceCache();
    const s = cached ? { ...DEFAULT_SETTINGS, ...cached } : DEFAULT_SETTINGS;
    applySettingsToDom(s);
    setHasWallpaper(Boolean(s.bgImage));
  }, []);

  function cycleMascotLine() {
    setMascotMood((prev) => {
      const i = LOGIN_MOOD_CYCLE.indexOf(prev);
      const next = LOGIN_MOOD_CYCLE[(i + 1) % LOGIN_MOOD_CYCLE.length] || "idle";
      setMascotSpeech(MOOD_LINE[next] || mascotLine("idle"));
      return next;
    });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!username.trim() || !password) {
      setError("请填写用户名和密码");
      return;
    }
    if (mode === "register") {
      if (password.length < 6) {
        setError("密码至少 6 位");
        return;
      }
      if (password !== confirm) {
        setError("两次输入的密码不一致");
        return;
      }
    }
    setBusy(true);
    try {
      if (mode === "login") {
        await login(username.trim(), password);
      } else {
        await register(username.trim(), password);
      }
      navigate(redirectTo, { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`vnss-app ${styles.wrap}`}>
      {hasWallpaper ? (
        <>
          <div className="vnss-wallpaper" aria-hidden />
          <div className="vnss-wallpaper-scrim" aria-hidden />
          <div className="vnss-grain" aria-hidden />
        </>
      ) : null}

      <section className={styles.hero} aria-label="品牌介绍">
        <div className={styles.slash} aria-hidden />
        <div className={styles.arc} aria-hidden>
          <span>STUDIO</span>
        </div>
        <span className={`${styles.shard} ${styles.shardA}`} aria-hidden />
        <span className={`${styles.shard} ${styles.shardB}`} aria-hidden />
        <span className={`${styles.shard} ${styles.shardC}`} aria-hidden />
        <button
          type="button"
          className={styles.portraitSlot}
          onClick={cycleMascotLine}
          title="点我切换表情"
          aria-label="点击切换看板娘表情与旁白"
        >
          <MascotFigure size="fill" mood={mascotMood} line={mascotSpeech} />
        </button>
        <div className={styles.heroInner}>
          <p className={styles.kicker}>VISUAL NOVEL</p>
          <h1 className={styles.brand}>
            Script
            <br />
            Studio
          </h1>
          <p className={styles.sub}>
            非线性叙事工作台——角色、章节、地图与审稿，写完再导出 .rpy。
          </p>
        </div>
      </section>

      <section className={`${styles.panel} vnss-frost`}>
        <div className={styles.card}>
          <div className={styles.cardSlash} aria-hidden />
          <h2 className={styles.cardTitle}>
            {mode === "login" ? "进入工作室" : "注册账号"}
          </h2>
          <p className={styles.cardLead}>
            {mode === "login"
              ? "同步云端剧本库与 Agent 会话。"
              : "新建工程、导入稿件、导出 Ren'Py。"}
          </p>

          <div className={styles.tabs} role="tablist" aria-label="登录或注册">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              className={mode === "login" ? styles.tabActive : styles.tab}
              onClick={() => {
                setMode("login");
                setError("");
              }}
            >
              登录
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "register"}
              className={mode === "register" ? styles.tabActive : styles.tab}
              onClick={() => {
                setMode("register");
                setError("");
              }}
            >
              注册
            </button>
          </div>

          <form
            id="vnss-login-form"
            className={styles.form}
            onSubmit={onSubmit}
          >
            <label htmlFor="vnss-username">
              用户名
              <input
                id="vnss-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="至少 2 个字符"
              />
            </label>
            <label htmlFor="vnss-password">
              密码
              <input
                id="vnss-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                placeholder={mode === "register" ? "至少 6 位" : "密码"}
              />
            </label>
            {mode === "register" && (
              <label htmlFor="vnss-confirm">
                确认密码
                <input
                  id="vnss-confirm"
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                />
              </label>
            )}
            {error && (
              <p className={styles.error} role="alert">
                {error}
              </p>
            )}
            <button type="submit" className={styles.submit} disabled={busy}>
              {busy ? "处理中…" : mode === "login" ? "开始创作" : "注册并进入"}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
