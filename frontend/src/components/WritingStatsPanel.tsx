import { useEffect, useState } from "react";
import {
  getProjectStats,
  type ProjectStats,
  type WritingActivityDay,
} from "../api/projects";
import styles from "./WritingStatsPanel.module.css";

type Props = {
  projectId: string;
};

const fmt = (n: number) => (n >= 10000 ? `${(n / 10000).toFixed(1)}万` : String(n));

/** Heatmap cell intensity for a day's net word change (0..1). */
function intensity(net: number, max: number): number {
  if (net <= 0 || max <= 0) return 0;
  return Math.min(1, net / max);
}

/** Writing stats dashboard: totals, 30-day heatmap, per-chapter breakdown. */
export function WritingStatsPanel({ projectId }: Props) {
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    getProjectStats(projectId)
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "统计加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) return <p className={styles.error}>{error}</p>;
  if (!stats) return <p className={styles.hint}>加载写作统计…</p>;

  const { totals, chapters, activity } = stats;
  const maxDay = Math.max(1, ...activity.map((d) => Math.abs(d.net)));
  // Build a full 30-day calendar (oldest → newest) so gaps render as empty cells.
  const days: (WritingActivityDay | null)[] = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate()
    ).padStart(2, "0")}`;
    const hit = activity.find((a) => a.date === key);
    days.push(hit ?? null);
  }
  const writtenDays = activity.filter((d) => d.net > 0).length;

  return (
    <div className={styles.wrap}>
      <div className={styles.toolbar}>
        <span>写作统计 — 跟踪进度，保持手感</span>
      </div>

      <div className={styles.cards}>
        <div className={styles.card}>
          <span className={styles.cardLabel}>总字数</span>
          <strong className={styles.cardValue}>{fmt(totals.words)}</strong>
          <span className={styles.cardSub}>{totals.lines} 行</span>
        </div>
        <div className={styles.card}>
          <span className={styles.cardLabel}>章节</span>
          <strong className={styles.cardValue}>{totals.chapters}</strong>
          <span className={styles.cardSub}>平均 {fmt(totals.avgChapterWords)} 字/章</span>
        </div>
        <div className={styles.card}>
          <span className={styles.cardLabel}>近 30 天写作</span>
          <strong className={styles.cardValue}>{writtenDays}</strong>
          <span className={styles.cardSub}>天有产出</span>
        </div>
      </div>

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>近 30 天热力图</h3>
        <div className={styles.heatmap}>
          {days.map((d, i) => {
            const net = d?.net ?? 0;
            const level = Math.round(intensity(net, maxDay) * 4);
            return (
              <div
                key={i}
                className={`${styles.cell} ${net > 0 ? styles[`lvl${level}`] : ""}`}
                title={d ? `${d.date} · 净增 ${net} 字` : "无记录"}
              />
            );
          })}
        </div>
        <p className={styles.hint}>
          颜色越深当天写得越多（按净增字数）。日常小幅改动会累积成浅格。
        </p>
      </div>

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>章节字数</h3>
        {chapters.length === 0 ? (
          <div className={styles.empty}>
            <p>还没有章节。去写第一章吧。</p>
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>章</th>
                <th>标题</th>
                <th>字数</th>
                <th>行数</th>
                <th>对话占比</th>
                <th>出场角色</th>
              </tr>
            </thead>
            <tbody>
              {chapters.map((c) => (
                <tr key={c.id}>
                  <td>{c.index}</td>
                  <td className={styles.title}>{c.title}</td>
                  <td>{fmt(c.words)}</td>
                  <td>{c.lines}</td>
                  <td>{Math.round(c.dialogueRatio * 100)}%</td>
                  <td className={styles.speakers}>
                    {c.speakers.length ? c.speakers.join("、") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
