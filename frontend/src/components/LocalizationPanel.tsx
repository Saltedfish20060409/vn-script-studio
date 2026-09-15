import { useCallback, useEffect, useMemo, useState } from "react";
import {
  downloadLocalizationZip,
  fetchLocalization,
  prefillLocalization,
  saveLocalization,
  type LocalizationEntry,
} from "../api/projects";
import { ApiError } from "../api/http";
import styles from "./LocalizationPanel.module.css";

type Props = {
  projectId: string;
  /** 保存成功后通知外层刷新项目（保持其它页面数据一致） */
  onSaved?: () => void;
};

type Draft = {
  locales: Array<{ code: string; name: string; status: string }>;
  entries: LocalizationEntry[];
  glossary: Array<{ term: string; targets: Record<string, string>; note?: string }>;
};

const STATUS_LABEL: Record<string, string> = {
  "": "未翻",
  todo: "待翻",
  translated: "已翻",
  reviewed: "已校对",
};

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * 本地化工作台：多语言文本、术语表、翻译状态、导出 Ren'Py 翻译文件。
 *
 * 之前完全没有这一块，而"提高本地化效率"正是核心目标之一。
 * 关键设计：源文本永远来自当前剧本（服务端重新提取），译文按「键 + 内容指纹」对账，
 * 所以改稿后不会把译文贴到错的句子上。
 */
export function LocalizationPanel({ projectId, onSaved }: Props) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [active, setActive] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newTerm, setNewTerm] = useState("");
  const [filter, setFilter] = useState<"all" | "todo" | "done">("all");
  const [onlyChapter, setOnlyChapter] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const out = await fetchLocalization(projectId);
      setDraft({
        locales: out.locales.map((l) => ({
          code: l.code,
          name: l.name || l.code,
          status: l.status || "draft",
        })),
        entries: out.entries.map((e) => ({
          ...e,
          targets: { ...(e.targets || {}) },
          status: { ...(e.status || {}) },
        })),
        glossary: (out.glossary || []).map((g) => ({
          term: g.term,
          targets: { ...(g.targets || {}) },
          note: g.note,
        })),
      });
      setActive((cur) => cur || out.locales[0]?.code || "");
      setMsg(`已提取 ${out.entries.length} 条可翻译文本`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const chapters = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of draft?.entries ?? []) {
      m.set(e.chapterId, (m.get(e.chapterId) ?? 0) + 1);
    }
    return [...m.entries()];
  }, [draft]);

  const filtered = useMemo(() => {
    const list = draft?.entries ?? [];
    return list.filter((e) => {
      if (onlyChapter && e.chapterId !== onlyChapter) return false;
      const done = Boolean((e.targets?.[active] || "").trim());
      if (filter === "todo") return !done;
      if (filter === "done") return done;
      return true;
    });
  }, [draft, active, filter, onlyChapter]);

  const progress = useMemo(() => {
    const list = draft?.entries ?? [];
    const done = list.filter((e) => (e.targets?.[active] || "").trim()).length;
    return { done, total: list.length, pct: list.length ? Math.round((done / list.length) * 100) : 0 };
  }, [draft, active]);

  function patchEntry(key: string, patch: Partial<LocalizationEntry>) {
    setDraft((d) =>
      d
        ? { ...d, entries: d.entries.map((e) => (e.key === key ? { ...e, ...patch } : e)) }
        : d
    );
  }

  function setTarget(key: string, text: string) {
    setDraft((d) =>
      d
        ? {
            ...d,
            entries: d.entries.map((e) =>
              e.key === key
                ? {
                    ...e,
                    targets: { ...e.targets, [active]: text },
                    status: { ...e.status, [active]: text.trim() ? "translated" : "" },
                  }
                : e
            ),
          }
        : d
    );
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const out = await saveLocalization(projectId, {
        locales: draft.locales,
        entries: draft.entries,
        glossary: draft.glossary,
      });
      setMsg(`已保存（${out.stats.entries} 条词条）`);
      onSaved?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function prefill() {
    if (!active) return;
    setBusy(true);
    setError("");
    try {
      const out = await prefillLocalization(projectId, active);
      setMsg(`术语表预填了 ${out.filled} 条（只填空着的条目）`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "预填失败");
    } finally {
      setBusy(false);
    }
  }

  async function exportZip() {
    setError("");
    try {
      const blob = await downloadLocalizationZip(projectId);
      downloadBlob(blob, "localization-tl.zip");
      setMsg("已导出 tl/ 目录（解压后放进 Ren'Py 项目的 game/ 下）");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "导出失败");
    }
  }

  if (!draft) {
    return <p className={styles.note}>{error || "正在提取可翻译文本…"}</p>;
  }

  return (
    <div className={styles.wrap} data-testid="localization-panel">
      <div className={styles.head}>
        <strong className={styles.title}>本地化</strong>
        <button type="button" className={styles.btn} onClick={() => void load()} disabled={busy}>
          重新提取
        </button>
        <button type="button" className={styles.btn} onClick={() => void save()} disabled={busy}>
          {busy ? "处理中…" : "保存"}
        </button>
        <button type="button" className={styles.btn} onClick={() => void exportZip()}>
          导出 .rpy
        </button>
      </div>

      {msg ? <p className={styles.ok}>{msg}</p> : null}
      {error ? <p className={styles.bad}>{error}</p> : null}

      <div className={styles.blocks}>
        <span className={styles.subTitle}>语言</span>
        <div className={styles.chips}>
          {draft.locales.map((l) => (
            <button
              key={l.code}
              type="button"
              className={l.code === active ? styles.chipOn : styles.chip}
              onClick={() => setActive(l.code)}
            >
              {l.name}（{l.code}）
            </button>
          ))}
          <input
            className={styles.mini}
            value={newCode}
            onChange={(e) => setNewCode(e.target.value)}
            placeholder="en"
            aria-label="语言代码"
          />
          <input
            className={styles.mini}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="English"
            aria-label="语言名"
          />
          <button
            type="button"
            className={styles.btn}
            onClick={() => {
              const code = newCode.trim();
              if (!code) return;
              setDraft((d) =>
                d && !d.locales.some((x) => x.code === code)
                  ? {
                      ...d,
                      locales: [
                        ...d.locales,
                        { code, name: newName.trim() || code, status: "draft" },
                      ],
                    }
                  : d
              );
              setActive(code);
              setNewCode("");
              setNewName("");
            }}
          >
            添加语言
          </button>
        </div>
      </div>

      {active ? (
        <>
          <div className={styles.blocks}>
            <span className={styles.subTitle}>
              进度 {progress.done}/{progress.total}（{progress.pct}%）
            </span>
            <div className={styles.bar} aria-hidden>
              <span style={{ width: `${Math.max(progress.pct, 1)}%` }} />
            </div>
            <div className={styles.chips}>
              {(["all", "todo", "done"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={filter === f ? styles.chipOn : styles.chip}
                  onClick={() => setFilter(f)}
                >
                  {f === "all" ? "全部" : f === "todo" ? "未翻" : "已翻"}
                </button>
              ))}
              <select
                className={styles.mini}
                value={onlyChapter}
                onChange={(e) => setOnlyChapter(e.target.value)}
                aria-label="按章节筛选"
              >
                <option value="">全部章节</option>
                {chapters.map(([cid, n]) => (
                  <option key={cid} value={cid}>
                    {cid}（{n}）
                  </option>
                ))}
              </select>
              <button type="button" className={styles.btn} onClick={() => void prefill()}>
                术语表预填
              </button>
            </div>
          </div>

          <ul className={styles.entries}>
            {filtered.map((e) => (
              <li key={e.key} className={styles.entry}>
                <div className={styles.entryHead}>
                  <code className={styles.key}>{e.key}</code>
                  <span className={styles.kind}>{e.kind}</span>
                  <span className={styles.status}>
                    {STATUS_LABEL[e.status?.[active] ?? ""] ?? e.status?.[active]}
                  </span>
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() =>
                      patchEntry(e.key, {
                        status: {
                          ...e.status,
                          [active]:
                            e.status?.[active] === "reviewed" ? "translated" : "reviewed",
                        },
                      })
                    }
                  >
                    标记校对
                  </button>
                </div>
                <p className={styles.source}>{e.source}</p>
                <textarea
                  className={styles.target}
                  value={e.targets?.[active] ?? ""}
                  onChange={(ev) => setTarget(e.key, ev.target.value)}
                  placeholder={`${active} 译文`}
                  rows={2}
                />
              </li>
            ))}
          </ul>
          {filtered.length === 0 ? <p className={styles.note}>这个筛选下没有条目。</p> : null}

          <div className={styles.blocks}>
            <span className={styles.subTitle}>术语表（{draft.glossary.length}）</span>
            <div className={styles.chips}>
              <input
                className={styles.mini}
                value={newTerm}
                onChange={(e) => setNewTerm(e.target.value)}
                placeholder="原文术语，如 林夏"
                aria-label="术语"
              />
              <button
                type="button"
                className={styles.btn}
                onClick={() => {
                  const term = newTerm.trim();
                  if (!term) return;
                  setDraft((d) =>
                    d ? { ...d, glossary: [...d.glossary, { term, targets: {} }] } : d
                  );
                  setNewTerm("");
                }}
              >
                添加术语
              </button>
            </div>
            <ul className={styles.glossary}>
              {draft.glossary.map((g, i) => (
                <li key={`${g.term}-${i}`}>
                  <span className={styles.term}>{g.term}</span>
                  <input
                    className={styles.mini}
                    value={g.targets?.[active] ?? ""}
                    onChange={(ev) =>
                      setDraft((d) =>
                        d
                          ? {
                              ...d,
                              glossary: d.glossary.map((x, j) =>
                                j === i
                                  ? {
                                      ...x,
                                      targets: { ...x.targets, [active]: ev.target.value },
                                    }
                                  : x
                              ),
                            }
                          : d
                      )
                    }
                    placeholder={`${active} 译名`}
                    aria-label={`${g.term} 的译名`}
                  />
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() =>
                      setDraft((d) =>
                        d ? { ...d, glossary: d.glossary.filter((_, j) => j !== i) } : d
                      )
                    }
                  >
                    删除
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <p className={styles.note}>
            改稿后点「重新提取」：源文本按当前剧本更新，译文用「键 + 内容指纹」对账——
            句子没变就接回去，句子改了则宁可留空，也不会把上一句的译文贴到新句子上。
            导出的是官方字符串翻译（tl/&lt;lang&gt;/strings.rpy），未翻条目自动回落原文。
          </p>
        </>
      ) : (
        <p className={styles.note}>先添加一个目标语言（例如 en / ja / ko）再开始翻译。</p>
      )}
    </div>
  );
}
