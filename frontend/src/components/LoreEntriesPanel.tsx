import { useMemo, useState } from "react";
import type { LoreEntry } from "../types/vn";
import {
  importToEntries,
  keywordsToText,
  newLoreEntry,
  parseKeywords,
  parseLoreImport,
} from "../lib/loreEntries";
import styles from "./LoreEntriesPanel.module.css";

type Props = {
  entries: LoreEntry[];
  onChange: (next: LoreEntry[]) => void;
};

/**
 * 设定条目编辑器：给"设定很多"的作者用的。
 *
 * 与「世界观 / 大纲」那五个字段的区别：那五个各有长度上限（单次参考会被截断），
 * 适合放最关键的几段；条目则可以堆很多条，每条带**触发词**，AI 提问命中哪条带哪条。
 * 所以设定总量再大，单次进模型的也只有相关的那几条。
 */
export function LoreEntriesPanel({ entries, onChange }: Props) {
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [filter, setFilter] = useState("");
  const [notice, setNotice] = useState("");

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      (e) =>
        e.title.toLowerCase().includes(q) ||
        (e.keywords ?? []).some((k) => k.toLowerCase().includes(q)) ||
        e.body.toLowerCase().includes(q)
    );
  }, [entries, filter]);

  function patch(id: string, next: Partial<LoreEntry>) {
    onChange(entries.map((e) => (e.id === id ? { ...e, ...next } : e)));
  }

  function remove(id: string) {
    onChange(entries.filter((e) => e.id !== id));
  }

  function addOne() {
    onChange([...entries, newLoreEntry()]);
    setNotice("已新增一条空条目，填好标题和触发词后 AI 就能检索到它");
  }

  function doImport() {
    const parsed = parseLoreImport(importText);
    if (!parsed.length) {
      setNotice("没解析出条目：用「标题 + 空行 + 正文」或 `# 标题` 的写法试试");
      return;
    }
    const created = importToEntries(parsed, entries);
    onChange([...entries, ...created]);
    setImportText("");
    setImportOpen(false);
    setNotice(
      `已导入 ${created.length} 条。建议给每条补一句触发词（提问里出现的说法），命中会准得多。`
    );
  }

  const keywordless = entries.filter((e) => !(e.keywords ?? []).some((k) => k.trim())).length;

  return (
    <section className={styles.wrap}>
      <div className={styles.toolbar}>
        <span className={styles.count}>
          共 {entries.length} 条
          {keywordless > 0 ? `（${keywordless} 条还没填触发词）` : ""}
        </span>
        <input
          className={styles.filter}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="按标题 / 触发词 / 正文筛选"
          aria-label="筛选设定条目"
        />
        <button type="button" className={styles.ghost} onClick={() => setImportOpen((v) => !v)}>
          {importOpen ? "收起批量导入" : "批量导入"}
        </button>
        <button type="button" className={styles.primary} onClick={addOne}>
          新增条目
        </button>
      </div>

      <p className={styles.lead}>
        设定很多的时候用这里：条目可以一直加，每条填**触发词**，提问里出现哪个词就带哪条进上下文——
        所以总设定再大，单次给 AI 的仍然只有相关的那几条。钉住 ☆ 的条目每轮都会带上。
      </p>
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      {importOpen ? (
        <div className={styles.importBox}>
          <textarea
            rows={7}
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            placeholder={
              "把设定粘进来，按「空行分段」或「# 标题」自动切成条目：\n\n" +
              "青云门\n关键词：青云、掌门\n东域正道之首，山门在青云山落霞峰。\n\n" +
              "太虚宗\n专研神魂与禁术。"
            }
          />
          <div className={styles.importActions}>
            <button type="button" className={styles.primary} onClick={doImport}>
              解析并导入
            </button>
            <span className={styles.hint}>
              每段第一行当标题；以「关键词：a、b」开头的一行会被当作触发词
            </span>
          </div>
        </div>
      ) : null}

      {entries.length === 0 ? (
        <p className={styles.empty}>
          还没有设定条目。可以点「批量导入」把 Word / 笔记里的设定一次粘进来。
        </p>
      ) : null}

      <div className={styles.list}>
        {shown.map((e) => (
          <article key={e.id} className={e.pinned ? `${styles.card} ${styles.cardPinned}` : styles.card}>
            <div className={styles.cardHead}>
              <button
                type="button"
                className={e.pinned ? `${styles.pin} ${styles.pinOn}` : styles.pin}
                onClick={() => patch(e.id, { pinned: !e.pinned })}
                title={e.pinned ? "已钉住：每轮都带上（点一下取消）" : "钉住：不管问什么，每轮都带上"}
                aria-label={e.pinned ? "取消钉住" : "钉住这条"}
              >
                {e.pinned ? "★" : "☆"}
              </button>
              <input
                className={styles.title}
                value={e.title}
                onChange={(ev) => patch(e.id, { title: ev.target.value })}
                placeholder="条目标题（如 青云门 / 夺魂案）"
              />
              <button type="button" className={styles.danger} onClick={() => remove(e.id)}>
                删除
              </button>
            </div>
            <label className={styles.field}>
              <span>
                触发词
                <small>（提问里出现这些词就命中；顿号分隔）</small>
              </span>
              <input
                value={keywordsToText(e.keywords)}
                onChange={(ev) => patch(e.id, { keywords: parseKeywords(ev.target.value) })}
                placeholder="如 青云、青云门、掌门"
              />
            </label>
            <label className={styles.field}>
              正文
              <textarea
                rows={4}
                value={e.body}
                onChange={(ev) => patch(e.id, { body: ev.target.value })}
                placeholder="这条设定的内容（AI 只在命中时看到它，不会整段搬进正文）"
              />
            </label>
          </article>
        ))}
        {entries.length > 0 && shown.length === 0 ? (
          <p className={styles.empty}>没有匹配「{filter}」的条目。</p>
        ) : null}
      </div>
    </section>
  );
}
