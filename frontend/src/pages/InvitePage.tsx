import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/authContext";
import { acceptProjectInvite } from "../api/collab";
import { MascotFigure } from "../components/MascotFigure";
import styles from "./InvitePage.module.css";

/** 邀请链接落地页：登录后接受邀请加入项目。 */
export default function InvitePage() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const inviteToken = params.get("token") || "";
  const [state, setState] = useState<"idle" | "working" | "done" | "error">(
    "idle"
  );
  const [message, setMessage] = useState("");

  const accept = useCallback(async () => {
    if (!inviteToken) return;
    setState("working");
    try {
      const res = await acceptProjectInvite(inviteToken);
      setMessage(
        res.alreadyMember
          ? "你已是该项目成员，直接打开即可。"
          : `已加入项目（${res.role === "viewer" ? "你只能查看，不能修改" : "你可以一起编辑"}）。`
      );
      setState("done");
    } catch (e) {
      setState("error");
      setMessage(
        e instanceof Error ? e.message : "接受邀请失败，请稍后重试"
      );
    }
  }, [inviteToken]);

  useEffect(() => {
    if (token && state === "idle") void accept();
  }, [token, state, accept]);

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.head}>
          <h1>加入项目邀请</h1>
        </header>

        {!token ? (
          <>
            <p className={styles.hint}>需要登录后才能接受协作邀请。</p>
            <button
              type="button"
              className={styles.submit}
              onClick={() =>
                navigate(
                  `/login?return=${encodeURIComponent(
                    `/invite?token=${encodeURIComponent(inviteToken)}`
                  )}`
                )
              }
            >
              去登录 / 注册
            </button>
          </>
        ) : state === "working" ? (
          <p className={styles.hint}>正在加入项目…</p>
        ) : state === "done" ? (
          <>
            <MascotFigure mood="cheer" size="md" />
            <p className={styles.hint}>{message}</p>
            <button
              type="button"
              className={styles.submit}
              onClick={() => navigate("/")}
            >
              打开工作台
            </button>
          </>
        ) : (
          <>
            <p className={styles.hint}>{message}</p>
            <button
              type="button"
              className={styles.submit}
              onClick={() => void accept()}
            >
              重试
            </button>
          </>
        )}
      </div>
    </div>
  );
}
