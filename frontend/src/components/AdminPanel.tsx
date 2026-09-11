import { useCallback, useEffect, useState } from "react";
import {
  banUser,
  fetchAdminFunnel,
  fetchAdminOverview,
  grantAdmin,
  revokeAdmin,
  unbanUser,
  type AdminFunnelOut,
  type AdminOverviewOut,
  type AdminUserOut,
} from "../api/admin";
import { ApiError } from "../api/http";
import styles from "./AdminPanel.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function AdminPanel({ open, onClose }: Props) {
  const [data, setData] = useState<AdminOverviewOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "anomalies" | "disabled">("all");
  const [acting, setActing] = useState<string | null>(null);
  const [funnel, setFunnel] = useState<AdminFunnelOut | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const overview = await fetchAdminOverview({
        anomaliesOnly: filter === "anomalies",
        disabledOnly: filter === "disabled",
      });
      setData(overview);
      // 漏斗单独取（失败不影响用户列表展示）
      try {
        setFunnel(await fetchAdminFunnel(30));
      } catch {
        setFunnel(null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [filter]);

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function toggleBan(u: AdminUserOut) {
    const name = u.username;
    if (u.disabled_at) {
      if (!window.confirm(`解禁「${name}」？`)) return;
    } else if (
      !window.confirm(
        `封禁「${name}」？对方将无法登录与刷新令牌。`
      )
    ) {
      return;
    }
    setActing(`ban:${name}`);
    setError("");
    try {
      if (u.disabled_at) await unbanUser(name);
      else await banUser(name);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    } finally {
      setActing(null);
    }
  }

  async function toggleAdmin(u: AdminUserOut) {
    const name = u.username;
    if (u.is_admin) {
      if (!window.confirm(`撤销「${name}」的管理员？`)) return;
    } else if (!window.confirm(`授予「${name}」管理员？`)) {
      return;
    }
    setActing(`admin:${name}`);
    setError("");
    try {
      if (u.is_admin) await revokeAdmin(name);
      else await grantAdmin(name);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    } finally {
      setActing(null);
    }
  }

  const alertCount = (data?.danger_count ?? 0) + (data?.warn_count ?? 0);

  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-panel-title"
      onClick={onClose}
    >
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <header className={styles.head}>
          <div>
            <p className={styles.idx}>ADMIN</p>
            <h2 id="admin-panel-title" className={styles.title}>
              用户管理
            </h2>
            <p className={styles.lead}>
              每行右侧有「授管理 / 撤管理」和「封禁」。管理员写在数据库，改完立即生效。
            </p>
          </div>
          <button type="button" className={styles.close} onClick={onClose}>
            关闭
          </button>
        </header>

        <div className={`${styles.stats} vnss-stagger`}>
          <div className={styles.stat}>
            <span>用户</span>
            <strong>{data?.user_count ?? "—"}</strong>
          </div>
          <div
            className={`${styles.stat} ${
              (data?.danger_count ?? 0) > 0 ? styles.statDanger : ""
            }`}
          >
            <span>需关注</span>
            <strong>{alertCount || 0}</strong>
          </div>
          <div className={styles.stat}>
            <span>管理员</span>
            <strong>{data?.admin_count ?? "—"}</strong>
          </div>
          <div className={styles.stat}>
            <span>已封禁</span>
            <strong>{data?.disabled_count ?? "—"}</strong>
          </div>
        </div>

        {(data?.danger_count ?? 0) > 0 ? (
          <p className={styles.banner} role="status">
            有 {data?.danger_count} 个账号触发红色异常，建议先看下方标红行。
          </p>
        ) : null}

        {funnel ? (
          <div className={styles.funnelBox} data-testid="admin-funnel">
            <p className={styles.funnelTitle}>
              激活漏斗（近 {funnel.days} 天，人数为累计去重）
            </p>
            <ul className={styles.funnelList}>
              {funnel.funnel.map((step, i) => {
                const first = funnel.funnel[0]?.users || 0;
                const prev = i === 0 ? step.users : funnel.funnel[i - 1].users;
                const pct = first > 0 ? Math.round((step.users / first) * 100) : 0;
                const drop = i === 0 || prev <= 0 ? null : Math.round(((prev - step.users) / prev) * 100);
                return (
                  <li key={step.key}>
                    <span className={styles.funnelLabel}>{step.label}</span>
                    <span className={styles.funnelBar} aria-hidden>
                      <span style={{ width: `${Math.max(pct, 2)}%` }} />
                    </span>
                    <span className={styles.funnelNum}>
                      {step.users}
                      {i > 0 ? ` · ${pct}%` : ""}
                      {drop !== null && drop > 0 ? `（↓${drop}%）` : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
            {funnel.sources.length > 0 ? (
              <p className={styles.funnelSources}>
                渠道：
                {funnel.sources.map((s) => (
                  <span key={s.source} className={styles.sourceChip}>
                    {s.source} · {s.signups} 注册 / {s.active7d} 活跃
                  </span>
                ))}
              </p>
            ) : null}
            {funnel.notes ? <p className={styles.funnelNote}>{funnel.notes}</p> : null}
          </div>
        ) : null}

        <div className={styles.toolbar}>
          <div className={styles.filters} role="tablist" aria-label="筛选">
            {(
              [
                ["all", "全部"],
                ["anomalies", "仅异常"],
                ["disabled", "已封禁"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={filter === id}
                className={filter === id ? styles.tabOn : styles.tab}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={styles.refresh}
            onClick={() => void load()}
            disabled={busy}
          >
            {busy ? "刷新中…" : "刷新"}
          </button>
        </div>

        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.colActions}>操作</th>
                <th>用户</th>
                <th>项目</th>
                <th>今日调用</th>
                <th>异常</th>
              </tr>
            </thead>
            <tbody>
              {(data?.users ?? []).map((u) => (
                <tr
                  key={u.id}
                  className={
                    u.severity === "danger"
                      ? styles.rowDanger
                      : u.severity === "warn"
                        ? styles.rowWarn
                        : u.disabled_at
                          ? styles.rowDisabled
                          : undefined
                  }
                >
                  <td className={styles.colActions}>
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className={u.is_admin ? styles.revoke : styles.grant}
                        disabled={acting === `admin:${u.username}`}
                        onClick={() => void toggleAdmin(u)}
                      >
                        {acting === `admin:${u.username}`
                          ? "…"
                          : u.is_admin
                            ? "撤管理"
                            : "授管理"}
                      </button>
                      <button
                        type="button"
                        className={
                          u.disabled_at ? styles.unban : styles.ban
                        }
                        disabled={acting === `ban:${u.username}`}
                        onClick={() => void toggleBan(u)}
                      >
                        {acting === `ban:${u.username}`
                          ? "…"
                          : u.disabled_at
                            ? "解禁"
                            : "封禁"}
                      </button>
                    </div>
                  </td>
                  <td>
                    <div className={styles.name}>
                      {u.username}
                      {u.is_admin ? (
                        <span className={styles.adminBadge}>管理</span>
                      ) : null}
                    </div>
                    <div className={styles.meta}>
                      {u.email || "无邮箱"}
                      {u.created_at
                        ? ` · 注册 ${new Date(u.created_at).toLocaleDateString()}`
                        : ""}
                      {u.disabled_at ? " · 已封禁" : ""}
                    </div>
                  </td>
                  <td>{u.project_count}</td>
                  <td>
                    {u.calls_today}
                    <span className={styles.meta}>
                      {" "}
                      / {u.tokens_today.toLocaleString()} tok
                    </span>
                  </td>
                  <td>
                    {u.flag_labels.length ? (
                      <ul className={styles.flags}>
                        {u.flag_labels.map((lab) => (
                          <li key={lab}>{lab}</li>
                        ))}
                      </ul>
                    ) : (
                      <span className={styles.ok}>正常</span>
                    )}
                  </td>
                </tr>
              ))}
              {!busy && (data?.users?.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={5} className={styles.empty}>
                    暂无匹配用户
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
