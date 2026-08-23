import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/authContext";
import {
  ApiError,
  forgotPassword,
  resendVerification,
} from "../api/client";
import {
  applySettingsToDom,
  DEFAULT_SETTINGS,
  loadAppearanceCache,
} from "../lib/settings";
import { MascotFigure } from "../components/MascotFigure";
import { MASCOT_MOODS, type MascotMood } from "../lib/mascotArt";
import { mascotLine } from "../lib/mascotCopy";
import { NoticeBanner } from "../components/NoticeBanner";
import styles from "./LoginPage.module.css";

type Mode = "login" | "register" | "forgot" | "checkEmail";

const LOGIN_MOOD_CYCLE: MascotMood[] = MASCOT_MOODS.filter((m) => m !== "focus");

const MOOD_LINE: Partial<Record<MascotMood, string>> = {
  idle: "准备好你的第一行了吗？",
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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");
  const [showNotice, setShowNotice] = useState(false);
  const [hasWallpaper, setHasWallpaper] = useState(false);
  const [mascotMood, setMascotMood] = useState<MascotMood>("idle");
  const [mascotSpeech, setMascotSpeech] = useState(
    () => MOOD_LINE.idle || mascotLine("idle")
  );

  const redirectTo =
    (location.state as { from?: string } | null)?.from ||
    new URLSearchParams(location.search).get("return") ||
    "/";

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
    setInfo("");
    setBusy(true);
    try {
      if (mode === "forgot") {
        if (!email.trim()) {
          setError("请填写注册邮箱");
          return;
        }
        const r = await forgotPassword(email.trim());
        setInfo(r.message || "若该邮箱已注册，我们已发送重置链接");
        return;
      }
      if (mode === "register") {
        if (!username.trim() || !password || !email.trim()) {
          setError("请填写用户名、邮箱和密码");
          return;
        }
        if (password.length < 6) {
          setError("密码至少 6 位");
          return;
        }
        if (password !== confirm) {
          setError("两次输入的密码不一致");
          return;
        }
        const r = await register(username.trim(), password, email.trim());
        setPendingEmail(r.email);
        setEmail(r.email);
        setMode("checkEmail");
        setInfo(r.message);
        return;
      }
      if (!username.trim() || !password) {
        setError("请填写用户名/邮箱和密码");
        return;
      }
      await login(username.trim(), password);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function onResendVerify() {
    if (!pendingEmail && !email.trim()) {
      setError("请填写邮箱");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await resendVerification(pendingEmail || email.trim());
      setInfo(r.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }

  const title =
    mode === "login"
      ? "进入工作室"
      : mode === "register"
        ? "注册账号"
        : mode === "forgot"
          ? "找回密码"
          : "验证邮箱";

  return (
    <div className={`vnss-app ${styles.wrap}`}>
      {/* 公告复看：右上角按钮 → 强制打开公告弹窗（已读也能看） */}
      <button
        type="button"
        className={styles.reviewBtn}
        onClick={() => setShowNotice(true)}
        title="查看公告与起步指导"
      >
        📢 公告
      </button>
      {showNotice && <NoticeBanner forceOpen onClose={() => setShowNotice(false)} />}
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
            非线性叙事工作台——角色、章节、地图与审稿。先写剧本，再导出 Word 或 .rpy。
          </p>
        </div>
      </section>

      <section className={`${styles.panel} vnss-frost`}>
        <div className={styles.card}>
          <div className={styles.cardSlash} aria-hidden />
          <h2 className={styles.cardTitle}>{title}</h2>
          <p className={styles.cardLead}>
            {mode === "login"
              ? "同步云端剧本库与 Agent 会话。"
              : mode === "register"
                ? "注册后请验证邮箱，再登录进入。"
                : mode === "forgot"
                  ? "我们会向注册邮箱发送重置链接。"
                  : `已向 ${pendingEmail} 发送验证邮件，请点击链接后再登录。`}
          </p>

          {(mode === "login" || mode === "register") && (
            <div className={styles.tabs} role="tablist" aria-label="登录或注册">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "login"}
                className={mode === "login" ? styles.tabActive : styles.tab}
                onClick={() => {
                  setMode("login");
                  setError("");
                  setInfo("");
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
                  setInfo("");
                }}
              >
                注册
              </button>
            </div>
          )}

          {mode === "checkEmail" ? (
            <form
              className={styles.form}
              onSubmit={(e) => {
                e.preventDefault();
                if (email.trim()) setPendingEmail(email.trim());
                void onResendVerify();
              }}
            >
              {info && <p className={styles.okNote}>{info}</p>}
              {error && (
                <p className={styles.error} role="alert">
                  {error}
                </p>
              )}
              <label htmlFor="vnss-resend-email">
                邮箱
                <input
                  id="vnss-resend-email"
                  type="email"
                  value={email || pendingEmail}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    setPendingEmail(e.target.value);
                  }}
                  autoComplete="email"
                  placeholder="注册时使用的邮箱"
                />
              </label>
              <button type="submit" className={styles.submit} disabled={busy}>
                {busy ? "发送中…" : "重新发送验证邮件"}
              </button>
              <button
                type="button"
                className={styles.ghostLink}
                onClick={() => {
                  setMode("login");
                  setError("");
                  setInfo("");
                }}
              >
                返回登录
              </button>
            </form>
          ) : (
            <form id="vnss-login-form" className={styles.form} onSubmit={onSubmit}>
              {mode !== "forgot" && (
                <label htmlFor="vnss-username">
                  {mode === "login" ? "用户名或邮箱" : "用户名"}
                  <input
                    id="vnss-username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    placeholder={mode === "login" ? "用户名或邮箱" : "至少 2 个字符"}
                  />
                </label>
              )}
              {(mode === "register" || mode === "forgot") && (
                <label htmlFor="vnss-email">
                  邮箱
                  <input
                    id="vnss-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                    placeholder="用于验证与找回密码"
                  />
                </label>
              )}
              {mode !== "forgot" && (
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
              )}
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
              {info && <p className={styles.okNote}>{info}</p>}
              <button type="submit" className={styles.submit} disabled={busy}>
                {busy
                  ? "处理中…"
                  : mode === "login"
                    ? "开始创作"
                    : mode === "register"
                      ? "注册并发送验证邮件"
                      : "发送重置链接"}
              </button>
              {mode === "login" && (
                <button
                  type="button"
                  className={styles.ghostLink}
                  onClick={() => {
                    setMode("forgot");
                    setError("");
                    setInfo("");
                  }}
                >
                  忘记密码
                </button>
              )}
              {mode === "register" && (
                <button
                  type="button"
                  className={styles.ghostLink}
                  onClick={() => {
                    setMode("checkEmail");
                    setEmail(email.trim());
                    setPendingEmail(email.trim());
                    setError("");
                    setInfo("填写注册邮箱即可重新发送验证邮件");
                  }}
                >
                  已注册但未验证？重发验证邮件
                </button>
              )}
              {mode === "forgot" && (
                <button
                  type="button"
                  className={styles.ghostLink}
                  onClick={() => {
                    setMode("login");
                    setError("");
                    setInfo("");
                  }}
                >
                  返回登录
                </button>
              )}
            </form>
          )}
          <p className={styles.finePrint}>
            <Link to="/help">帮助与 FAQ →</Link>
            <span aria-hidden> · </span>
            <Link to="/legal?doc=privacy">隐私政策</Link>
            <span aria-hidden> · </span>
            <Link to="/legal?doc=terms">服务条款</Link>
            <br />
            AI 生成内容请自行审稿后再用于发行。
          </p>
        </div>
      </section>
    </div>
  );
}
