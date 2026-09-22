import { useMemo, useState } from "react";
import { auditGraph } from "../lib/graphAudit";
import type { VnProject } from "../types/vn";
import styles from "./GraphAuditCard.module.css";

type Props = {
  project: VnProject;
};

/**
 * 关系图体检：用确定性规则查图上的矛盾（关系互指、包含成环、悬空绑定…），**零 token**。
 *
 * 为什么值得单独一张卡片：一致性排查原来是"让模型读一遍再自己比"，可图上有一批问题
 * 是机器一眼可判的——别人不可能既是你的父亲又是你的子女、包含关系不可能绕成环、
 * 变量不可能绑在一个已删角色上。这些交给模型是浪费，而且模型偶尔会漏。
 * 所以顺序应该是：**机器先查一遍 → 模型只看剩下的**。
 *
 * 没有 error/warn 时整张卡片不显示（不制造噪音）。
 */
export function GraphAuditCard({ project }: Props) {
  const [open, setOpen] = useState(false);
  const audit = useMemo(() => auditGraph(project), [project]);

  const { error, warn, info } = audit.counts;
  if (error === 0 && warn === 0 && info === 0) return null;

  const tone = error > 0 ? styles.bad : warn > 0 ? styles.warn : styles.soft;

  return (
    <div className={styles.card} data-testid="graph-audit">
      <div className={styles.head}>
        <strong className={styles.title}>关系图体检</strong>
        <span className={`${styles.meta} ${tone}`} data-testid="graph-audit-counts">
          {error > 0 ? `${error} 处矛盾` : ""}
          {error > 0 && warn > 0 ? " · " : ""}
          {warn > 0 ? `${warn} 处可疑` : ""}
          {(error > 0 || warn > 0) && info > 0 ? " · " : ""}
          {info > 0 ? `${info} 条建议` : ""}
        </span>
        <span className={styles.size} data-testid="graph-audit-size">
          {audit.size.characters} 角色 · {audit.size.relations} 关系 · {audit.size.locations} 地点 ·{" "}
          {audit.size.timeline} 时间线
        </span>
        <button type="button" className={styles.ghost} onClick={() => setOpen((v) => !v)}>
          {open ? "收起" : "看明细"}
        </button>
      </div>

      {open ? (
        <ul className={styles.list} data-testid="graph-audit-detail">
          {audit.issues.map((i, idx) => (
            <li key={`${i.code}-${idx}`} className={styles[`s_${i.severity}`]}>
              <span className={styles.tag}>
                {i.severity === "error" ? "矛盾" : i.severity === "warn" ? "可疑" : "建议"}
              </span>
              <span className={styles.msg}>{i.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
