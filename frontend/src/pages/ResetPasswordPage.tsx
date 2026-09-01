import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, resetPassword } from "../api/client";
import styles from "./InvitePage.module.css";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [message, setMessage] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!token) {
      setError("链接无效，请从邮件中重新打开");
      return;
    }
    if (password.length < 8) {
      setError("密码至少 8 位");
      return;
    }
    if (password !== confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    setBusy(true);
    try {
      const r = await resetPassword(token, password);
      setDone(true);
      setMessage(r.message || "密码已更新");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "重置失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.head}>
          <h1>重置密码</h1>
        </header>
        {done ? (
          <>
            <p className={styles.hint}>{message}</p>
            <Link to="/login" className={styles.submit}>
              去登录
            </Link>
          </>
        ) : (
          <form
            onSubmit={onSubmit}
            style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}
          >
            <p className={styles.hint}>设置新密码后即可登录。</p>
            <label style={{ textAlign: "left", fontSize: "0.85rem" }}>
              新密码
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                style={{
                  display: "block",
                  width: "100%",
                  marginTop: "0.35rem",
                  minHeight: 40,
                  padding: "0.5rem 0.65rem",
                }}
              />
            </label>
            <label style={{ textAlign: "left", fontSize: "0.85rem" }}>
              确认密码
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                style={{
                  display: "block",
                  width: "100%",
                  marginTop: "0.35rem",
                  minHeight: 40,
                  padding: "0.5rem 0.65rem",
                }}
              />
            </label>
            {error && (
              <p className={styles.hint} role="alert" style={{ color: "var(--danger)" }}>
                {error}
              </p>
            )}
            <button type="submit" className={styles.submit} disabled={busy || !token}>
              {busy ? "保存中…" : "更新密码"}
            </button>
            <Link to="/login" style={{ fontSize: "0.85rem" }}>
              返回登录
            </Link>
          </form>
        )}
      </div>
    </div>
  );
}
