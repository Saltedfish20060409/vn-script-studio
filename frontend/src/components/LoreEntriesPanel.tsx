import { useMemo, useState } from "react";
import { uploadAgentAttachment } from "../api/projects";
import type { LoreEntry } from "../types/vn";
import {
  draftFromImport,
  draftsToImports,
  importToEntries,
  keywordsToText,
  newLoreEntry,
  parseKeywords,
  parseLoreImport,
  toggleKeyword,
  type LoreImportDraft,
} from "../lib/loreEntries";
import styles from "./LoreEntriesPanel.module.css";

type Props = {
  entries: LoreEntry[];
  onChange: (next: LoreEntry[]) => void;
  /** 有 projectId 才能把 .docx/.md 等文件交给服务端解析（没有就只支持粘贴） */
  projectId?: string;
};

/**
 * 设定条目编辑器：给"设定很多"的作者用的。
 *
 * 与「世界观 / 大纲」那五个字段的区别：那五个各有长度上限（单次参考会被截断），
 * 适合放最关键的几段；条目则可以堆很多条，每条带**触发词**，AI 提问命中哪条带哪条。
 * 所以设定总量再大，单次进模型的也只有相关的那几条。
 *
 * 导入刻意做成「先预览、再确认」：把一大堆设定文档塞进来的作者，
 * 最怕一次切错几百条又得手工重排；预览里可以逐条取消、改标题、点掉不要的触发词。
 */
export function LoreEntriesPanel({ entries, onChange, projectId }: Props) {
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [filter, setFilter] = useState("");
  const [notice, setNotice] = useState("");
  const [drafts, setDrafts] = useState<LoreImportDraft[] | null>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const [fileError, setFileError] = useState("");

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
    setDrafts(parsed.map(draftFromImport));
    setNotice("");
    setFileError("");
  }

  /** 直接选文件：txt/md 本地读，docx 等交给服务端解析（复用附件的解析能力）。 */
  async function onPickFiles(files: FileList | null) {
    if (!files?.length) return;
    setFileBusy(true);
    setFileError("");
    setNotice("");
    try {
      const chunks: string[] = [];
      for (const file of Array.from(files)) {
        if (projectId) {
          const att = await uploadAgentAttachment(projectId, file, false);
          chunks.push(att.text || "");
          if (att.warning) setFileError(att.warning);
        } else {
          chunks.push(await file.text());
        }
      }
      const parsed = parseLoreImport(chunks.join("\n\n"));
      if (!parsed.length) {
        setFileError("没从文件里认出条目：确认文件里有小标题（`# 标题`）或空行分段");
        return;
      }
      setDrafts(parsed.map(draftFromImport));
      setImportOpen(true);
    } catch (e) {
      setFileError(e instanceof Error ? e.message : "读取文件失败");
    } finally {
      setFileBusy(false);
    }
  }

  function toggleDraft(index: number) {
    setDrafts((prev) =>
      prev ? prev.map((d, i) => (i === index ? { ...d, include: !d.include } : d)) : prev
    );
  }

  function patchDraft(index: number, next: Partial<LoreImportDraft>) {
    setDrafts((prev) =>
      prev ? prev.map((d, i) => (i === index ? { ...d, ...next } : d)) : prev
    );
  }

  function confirmImport() {
    if (!drafts) return;
    const kept = draftsToImports(drafts);
    if (!kept.length) {
      setNotice("一条都没选中，什么都没导入");
      setDrafts(null);
      return;
    }
    const created = importToEntries(kept, entries);
    onChange([...entries, ...created]);
    const keywordless = created.filter((e) => !(e.keywords ?? []).length).length;
    setNotice(
      `已导入 ${created.length} 条。` +
        (keywordless
          ? `还有 ${keywordless} 条没有触发词——有了触发词，你随口一问它就能被带上。`
          : "每条都带上了触发词，提问命中就会自动带上。")
    );
    setDrafts(null);
    setImportText("");
    setImportOpen(false);
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
        设定多就写在这里：一条一个主题，可以一直加。每条填几个<strong>触发词</strong>，
        提问里出现哪个词就带哪条给 AI。钉住 ☆ 的条目每轮都带。
      </p>
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      {importOpen ? (
        <div className={styles.importBox}>
          {drafts ? (
            <div className={styles.preview} data-testid="lore-import-preview">
              <div className={styles.previewHead}>
                <strong>
                  识别到 {drafts.length} 条
                  {drafts.some((d) => !d.include) ? `（已取消 ${drafts.filter((d) => !d.include).length} 条）` : ""}
                </strong>
                <span className={styles.hint}>
                  取消勾选就不导入。触发词 = 你提问时可能怎么称呼它，点一下可加/可去。
                </span>
              </div>
              <ul className={styles.previewList}>
                {drafts.map((d, i) => (
                  <li key={`${d.title}-${i}`} className={styles.previewRow}>
                    <label className={styles.previewCheck}>
                      <input
                        type="checkbox"
                        checked={d.include}
                        onChange={() => toggleDraft(i)}
                        aria-label={`导入第 ${i + 1} 条`}
                      />
                    </label>
                    <div className={styles.previewBody}>
                      <input
                        className={styles.previewTitle}
                        value={d.title}
                        onChange={(e) => patchDraft(i, { title: e.target.value })}
                        aria-label={`第 ${i + 1} 条标题`}
                      />
                      <div className={styles.chips}>
                        {d.suggested.length === 0 ? (
                          <span className={styles.hint}>没有可推荐的触发词，可以手动加</span>
                        ) : (
                          d.suggested.map((s) => {
                            const on = d.keywords.includes(s);
                            return (
                              <button
                                key={s}
                                type="button"
                                className={on ? `${styles.chip} ${styles.chipOn}` : styles.chip}
                                aria-pressed={on}
                                onClick={() => patchDraft(i, { keywords: toggleKeyword(d.keywords, s) })}
                              >
                                {on ? "✓ " : "+ "}
                                {s}
                              </button>
                            );
                          })
                        )}
                      </div>
                      <p className={styles.previewText}>
                        {(d.body || "（这条没有正文）").slice(0, 160)}
                        {(d.body ?? "").length > 160 ? "…" : ""}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
              <div className={styles.importActions}>
                <button
                  type="button"
                  className={styles.primary}
                  data-testid="lore-import-confirm"
                  onClick={confirmImport}
                >
                  导入这 {drafts.filter((d) => d.include).length} 条
                </button>
                <button type="button" className={styles.ghost} onClick={() => setDrafts(null)}>
                  返回重选
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className={styles.fileRow}>
                <label className={styles.filePick}>
                  <input
                    type="file"
                    accept=".txt,.md,.markdown,.docx,.json,.csv,text/plain,text/markdown"
                    multiple
                    disabled={fileBusy}
                    data-testid="lore-import-file"
                    onChange={(e) => void onPickFiles(e.target.files)}
                  />
                  {fileBusy ? "正在读取…" : "📄 选设定文档（txt / md / docx，可多选）"}
                </label>
                <span className={styles.hint}>
                  也可以直接粘在下面。整份 Word / Notion 笔记丢进来就行，按小标题或空行自动分段。
                </span>
              </div>
              {fileError ? <p className={styles.error}>{fileError}</p> : null}
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
                  解析并预览
                </button>
                <span className={styles.hint}>
                  每段第一行当标题；以「关键词：a、b」开头的一行会被当作触发词（不写也行，会替你推荐）
                </span>
              </div>
            </>
          )}
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
