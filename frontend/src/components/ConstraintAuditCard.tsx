import { useState } from "react";
import { auditConstraints } from "../lib/constraintAudit";
import type { LoreEntry, StoryBible } from "../types/vn";
import styles from "./ConstraintAuditCard.module.css";

type Props = {
  bible: StoryBible;
  loreEntries: LoreEntry[];
  /** 有没有文风样例（决定要不要提醒"补样例"） */
  hasStyleSamples: boolean;
};

/**
 * 约束体检：把作者写的设定分成「必须有 / 尽量 / 背景信息」三档，并指出互相冲突的约束。
 *
 * 为什么要这张卡片：约束混在一起，模型分不清红线与建议；约束互相打架，模型只会写
 * 「不会违规的空话」——两种情况都会让人得出"这工具还不如直接聊"的结论，而问题其实出在设定上。
 *
 * 这里按**当前编辑状态**就地算（不等保存、不发请求）：作者一边写就要一边看到"这两条在打架"。
 * 后端有一份同规则的实现，负责把硬规则挑出来放进提示词末尾。
 */
export function ConstraintAuditCard({ bible, loreEntries, hasStyleSamples }: Props) {
  const [open, setOpen] = useState(false);

  const audit = auditConstraints({
    bibleText: [bible.world, bible.notes, bible.themes, bible.outline]
      .map((v) => String(v ?? ""))
      .join("\n"),
    entryTexts: loreEntries.map((e) => `${e.title}：${e.body}`),
    hasStyleSamples,
  });

  const hardCount = audit.hard.length;
  if (hardCount === 0 && audit.conflicts.length === 0 && !audit.needsSamples) return null;

  return (
    <div className={styles.card} data-testid="constraint-audit">
      <div className={styles.head}>
        <strong className={styles.title}>约束体检</strong>
        <span className={styles.meta} data-testid="constraint-audit-counts">
          硬规则 {hardCount} · 尽量 {audit.soft.length} · 背景 {audit.info.length}
        </span>
        {audit.conflicts.length > 0 ? (
          <span className={styles.bad} data-testid="constraint-audit-conflicts">
            ⚠ {audit.conflicts.length} 处冲突
          </span>
        ) : null}
        <button type="button" className={styles.ghost} onClick={() => setOpen((v) => !v)}>
          {open ? "收起" : "看明细"}
        </button>
      </div>

      {open ? (
        <div className={styles.body}>
          {audit.conflicts.length > 0 ? (
            <div className={styles.section}>
              <span className={styles.sectionTitle}>
                互相冲突的约束（模型遇到冲突会只写「不会违规的空话」）
              </span>
              <ul className={styles.list}>
                {audit.conflicts.map((c, i) => (
                  <li key={i} className={styles.conflict}>
                    <strong>{c.topic}</strong>
                    <span className={styles.pair}>
                      「{c.a}」 ✕ 「{c.b}」
                    </span>
                    <em>{c.hint}</em>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {audit.hard.length > 0 ? (
            <div className={styles.section}>
              <span className={styles.sectionTitle}>
                硬规则（会被放进上下文末尾重复一次：长对话里中间的要求最容易被忽略）
              </span>
              <ul className={styles.list}>
                {audit.hard.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {audit.notes.length > 0 ? (
            <ul className={styles.notes}>
              {audit.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
