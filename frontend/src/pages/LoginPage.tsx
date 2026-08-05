import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import {
  applySettingsToDom,
  DEFAULT_SETTINGS,
  loadAppearanceCache,
} from "../lib/settings";
import styles from "./LoginPage.module.css";

type Mode = "login" | "register";

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

  const redirectTo =
    (location.state as { from?: string } | null)?.from || "/";

  // Align login chrome with last-used studio appearance (local cache)
  useEffect(() => {
    const cached = loadAppearanceCache();
    const s = cached ? { ...DEFAULT_SETTINGS, ...cached } : DEFAULT_SETTINGS;
    applySettingsToDom(s);
    setHasWallpaper(Boolean(s.bgImage));
  }, []);

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
        <div className={styles.heroInner}>
          <span className={styles.mark} aria-hidden>
            VN
          </span>
          <h1 className={styles.brand}>Script Studio</h1>
          <p className={styles.sub}>
            面向 Ren&apos;Py 的视觉小说编剧工作台——设定、章节、地图与审稿 Agent，一处写完。
          </p>
        </div>
      </section>

      <section className={`${styles.panel} vnss-frost`}>
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>
            {mode === "login" ? "欢迎回来" : "创建账号"}
          </h2>
          <p className={styles.cardLead}>
            {mode === "login"
              ? "登录后同步云端剧本库与 Agent 会话。"
              : "注册后即可新建工程、导入稿件并导出 .rpy。"}
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

          <form className={styles.form} onSubmit={onSubmit}>
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
              {busy ? "处理中…" : mode === "login" ? "进入工作室" : "注册并进入"}
            </button>
          </form>

          <p className={styles.hint}>
            {mode === "login"
              ? "还没有账号？切换到「注册」。"
              : "已有账号？切换到「登录」。"}
          </p>
        </div>
      </section>
    </div>
  );
}
