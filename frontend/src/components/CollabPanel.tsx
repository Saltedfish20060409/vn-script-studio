import { useCallback, useEffect, useState } from "react";
import {
  addProjectMember,
  changeMemberRole,
  createProjectInvite,
  listProjectInvites,
  listProjectMembers,
  removeProjectMember,
  revokeProjectInvite,
  type InviteInfo,
  type MemberInfo,
} from "../api/collab";
import { useAuth } from "../lib/authContext";
import styles from "./CollabPanel.module.css";

type Props = {
  projectId: string;
};

/** 项目 → 成员子页：邀请 / 改角色 / 移除（仅 owner 可管理）。 */
export function CollabPanel({ projectId }: Props) {
  const { user } = useAuth();
  const [owner, setOwner] = useState<MemberInfo | null>(null);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [invites, setInvites] = useState<InviteInfo[]>([]);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<"editor" | "viewer">("editor");
  const [inviteRole, setInviteRole] = useState<"editor" | "viewer">("editor");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const isOwner = Boolean(user && owner && owner.userId === user.id);

  const refresh = useCallback(async () => {
    try {
      const [m, inv] = await Promise.all([
        listProjectMembers(projectId),
        listProjectInvites(projectId),
      ]);
      setOwner(m.owner);
      setMembers(m.members);
      setInvites(inv.invites);
    } catch (e) {
      setError(e instanceof Error ? e.message : "成员列表读取失败");
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const invite = useCallback(async () => {
    const name = username.trim();
    if (!name || busy) return;
    setBusy("invite");
    setError("");
    try {
      await addProjectMember(projectId, name, role);
      setUsername("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "邀请失败");
    } finally {
      setBusy("");
    }
  }, [projectId, username, role, busy, refresh]);

  const setRoleOf = useCallback(
    async (userId: string, next: "editor" | "viewer") => {
      setBusy("role");
      setError("");
      try {
        await changeMemberRole(projectId, userId, next);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "修改角色失败");
      } finally {
        setBusy("");
      }
    },
    [projectId, refresh]
  );

  const remove = useCallback(
    async (userId: string) => {
      setBusy("remove");
      setError("");
      try {
        await removeProjectMember(projectId, userId);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "移除成员失败");
      } finally {
        setBusy("");
      }
    },
    [projectId, refresh]
  );

  const genInvite = useCallback(async () => {
    setBusy("invite");
    setError("");
    try {
      await createProjectInvite(projectId, inviteRole);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成邀请失败");
    } finally {
      setBusy("");
    }
  }, [projectId, inviteRole, refresh]);

  const revoke = useCallback(
    async (token: string) => {
      setBusy("revoke");
      setError("");
      try {
        await revokeProjectInvite(projectId, token);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "撤销邀请失败");
      } finally {
        setBusy("");
      }
    },
    [projectId, refresh]
  );

  const copyInvite = useCallback(async (token: string) => {
    const url = `${window.location.origin}/invite?token=${encodeURIComponent(token)}`;
    try {
      await navigator.clipboard.writeText(url);
      setError("");
    } catch {
      setError(`复制失败，请手动复制：${url}`);
    }
  }, []);

  return (
    <section className={styles.panel}>
      <div className={styles.toolbar}>
        <span>成员可共同编辑剧本；只读成员（viewer）不能修改。</span>
      </div>

      {error && <p className={styles.error}>{error}</p>}

      <div className={styles.grid}>
        <div className={styles.card}>
          <div className={styles.cardHead}>
            <strong>{owner?.username ?? "—"}</strong>
            <span className={styles.kind}>owner</span>
          </div>
          <p className={styles.cardBody}>项目创建者</p>
        </div>
        {members.map((m) => (
          <div key={m.userId} className={styles.card}>
            <div className={styles.cardHead}>
              <strong>{m.username}</strong>
              <span className={styles.kind}>{m.role}</span>
            </div>
            <div className={styles.cardFoot}>
              {isOwner && m.role !== "owner" && (
                <>
                  <select
                    value={m.role}
                    disabled={busy !== ""}
                    onChange={(e) =>
                      void setRoleOf(
                        m.userId,
                        e.target.value as "editor" | "viewer"
                      )
                    }
                  >
                    <option value="editor">editor</option>
                    <option value="viewer">viewer</option>
                  </select>
                  <button
                    type="button"
                    className={styles.ghost}
                    disabled={busy !== ""}
                    onClick={() => void remove(m.userId)}
                  >
                    移除
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {isOwner && (
        <div className={styles.inviteRow}>
          <input
            className={styles.input}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void invite();
            }}
            placeholder="输入用户名邀请协作"
          />
          <select value={role} onChange={(e) => setRole(e.target.value as "editor" | "viewer")}>
            <option value="editor">可编辑</option>
            <option value="viewer">只读</option>
          </select>
          <button
            type="button"
            className={styles.primary}
            disabled={busy !== "" || !username.trim()}
            onClick={() => void invite()}
          >
            {busy === "invite" ? "邀请中…" : "邀请"}
          </button>
        </div>
      )}

      {isOwner && (
        <div className={styles.inviteLinks}>
          <div className={styles.inviteRow}>
            <span className={styles.linkHint}>邀请链接（对方打开链接登录后即加入）：</span>
            <select
              value={inviteRole}
              onChange={(e) =>
                setInviteRole(e.target.value as "editor" | "viewer")
              }
            >
              <option value="editor">可编辑</option>
              <option value="viewer">只读</option>
            </select>
            <button
              type="button"
              className={styles.primary}
              disabled={busy !== ""}
              onClick={() => void genInvite()}
            >
              {busy === "invite" ? "生成中…" : "生成链接"}
            </button>
          </div>
          {invites.length > 0 && (
            <ul className={styles.linkList}>
              {invites.map((inv) => (
                <li key={inv.token} className={styles.linkItem}>
                  <code className={styles.linkCode}>
                    {window.location.origin}/invite?token={inv.token.slice(0, 12)}…
                  </code>
                  <span className={styles.kind}>{inv.role}</span>
                  <span className={styles.kind}>至 {new Date(inv.expiresAt).toLocaleDateString()}</span>
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() => void copyInvite(inv.token)}
                  >
                    复制
                  </button>
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() => void revoke(inv.token)}
                  >
                    撤销
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
