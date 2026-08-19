import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, verifyEmail } from "../api/client";
import styles from "./InvitePage.module.css";

export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [state, setState] = useState<"working" | "done" | "error">(
    token ? "working" : "error"
  );
  const [message, setMessage] = useState(
    token ? "正在验证邮箱…" : "链接缺少 token，请从邮件中重新打开"
  );

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await verifyEmail(token);
        if (!cancelled) {
          setState("done");
          setMessage(r.message || "邮箱已验证");
        }
      } catch (err) {
        if (!cancelled) {
          setState("error");
          setMessage(
            err instanceof ApiError ? err.message : "验证失败，请重试或重新发送邮件"
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.head}>
          <h1>验证邮箱</h1>
        </header>
        <p className={styles.hint}>{message}</p>
        {state !== "working" && (
          <Link to="/login" className={styles.submit}>
            去登录
          </Link>
        )}
      </div>
    </div>
  );
}
