import { useCallback, useEffect, useMemo, useState } from "react";
import {
  aiTranslateLocalization,
  downloadLocalizationZip,
  fetchLocalization,
  prefillLocalization,
  saveLocalization,
  type LocalizationEntry,
} from "../api/projects";
import { ApiError } from "../api/http";
import {
  groupByChapter,
  hasUntranslated,
  nextUntranslated,
  progressFor,
  type ChapterLike,
} from "../lib/localizationView";
import styles from "./LocalizationPanel.module.css";

type Props = {
  projectId: string;
  /** 用于把 ch1 显示成「第一章」（否则界面上会出现内部 id） */
  chapters: ChapterLike[];
  /** 保存成功后通知外层刷新项目（保持其它页面数据一致） */
  onSaved?: () => void;
};

type Draft = {
  locales: Array<{ code: string; name: string; status: string }>;
  entries: LocalizationEntry[];
  glossary: Array<{ term: string; targets: Record<string, string>; note?: string }>;
};

const SUGGESTED: Array<{ code: string; name: string }> = [
  { code: "en", name: "English" },
  { code: "ja", name: "日本語" },
  { code: "ko", name: "한국어" },
  { code: "zh-Hans", name: "简体中文" },
];

const KIND_LABEL: Record<string, string> = {
  dialogue: "台词",
  narration: "旁白",
  choice: "选项",
  prompt: "菜单提示",
};

const STATUS_LABEL: Record<string, string> = {
  "": "未翻",
  todo: "未翻",
  ai: "AI 译·待校对",
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
 * 本地化工作台：把剧本翻译成其它语言，导出给 Ren'Py。
 *
 * 这一页是给"没接触过本地化"的作者用的，所以整个界面按 4 步组织：
 * ① 加目标语言 → ② 填术语表 → ③ 逐句翻译 → ④ 导出。
 * 空页面直接给可点的建议语言，章节显示标题而不是 ch1，术语表放在逐句翻译之前；
 * 「指纹对账」这类实现细节收进折叠区，不占正文。
 */
export function LocalizationPanel({ projectId, chapters, onSaved }: Props) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [active, setActive] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newTerm, setNewTerm] = useState("");
  const [newTermTarget, setNewTermTarget] = useState("");
  const [filter, setFilter] = useState<"all" | "todo">("all");
  const [onlyChapter, setOnlyChapter] = useState("");
  const [showWhy, setShowWhy] = useState(false);
  const [dirty, setDirty] = useState(false);

  /** 所有改动都走这里：统一标记"有未保存的改动"，避免翻了一堆却忘了保存。 */
  const mutate = useCallback((fn: (d: Draft) => Draft) => {
    setDraft((d) => (d ? fn(d) : d));
    setDirty(true);
  }, []);

  // 有未保存改动时拦截关窗/刷新（站内切 tab 拦不住，所以按钮上也写了提示）
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

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
      setDirty(false);
      setMsg(out.locales.length ? `剧本里共有 ${out.entries.length} 句需要翻译` : "");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const entries = useMemo(() => draft?.entries ?? [], [draft]);
  const groups = useMemo(
    () => groupByChapter(entries, chapters, active),
    [entries, chapters, active]
  );
  const overall = useMemo(() => progressFor(entries, active), [entries, active]);

  function addLocale(code: string, name: string) {
    const c = code.trim();
    if (!c) return;
    mutate((d) =>
      d.locales.some((x) => x.code === c)
        ? d
        : { ...d, locales: [...d.locales, { code: c, name: name.trim() || c, status: "draft" }] }
    );
    setActive(c);
    setNewCode("");
    setNewName("");
    setMsg(`已添加 ${name.trim() || c}，下面开始逐句翻译`);
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      const out = await saveLocalization(projectId, {
        locales: draft.locales,
        entries: draft.entries,
        glossary: draft.glossary,
      });
      setDirty(false);
      setMsg(`已保存（共 ${out.stats.entries} 句）`);
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
      setMsg(
        out.filled > 0
          ? `按术语表预填了 ${out.filled} 句（只填空着的），逐句核对一下`
          : "术语表里还没有可用的译名，先在步骤 ② 填几个人名或专有名词"
      );
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "预填失败");
    } finally {
      setBusy(false);
    }
  }

  /**
   * AI 代翻：只翻未翻的句子，写成草稿（状态「AI 译·待校对」），由作者逐句校对。
   * 人工已填的译文不会被覆盖（除非显式勾选"重新翻译"）。
   */
  async function aiTranslate(overwrite = false) {
    if (!active) return;
    if (dirty && !window.confirm("AI 会基于已保存的剧本翻译。当前有未保存的改动，先保存再翻译？\n\n点「取消」将丢弃本地改动继续翻译。")) {
      await save();
      return;
    }
    setBusy(true);
    setError("");
    try {
      const out = await aiTranslateLocalization(projectId, {
        locale: active,
        localeName: draft?.locales.find((l) => l.code === active)?.name ?? active,
        overwrite,
        limit: 25,
      });
      setMsg(out.message);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "AI 翻译失败");
    } finally {
      setBusy(false);
    }
  }

  async function exportZip() {
    setError("");
    try {
      const blob = await downloadLocalizationZip(projectId);
      downloadBlob(blob, "localization-tl.zip");
      setMsg("已导出。解压后把 tl 文件夹放进 Ren'Py 项目的 game/ 目录即可");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "导出失败");
    }
  }

  function jumpToNextUntranslated() {
    const next = nextUntranslated(entries, active);
    if (!next) {
      setMsg("这个语言已经全部翻完了 🎉");
      return;
    }
    if (onlyChapter) setOnlyChapter("");
    if (filter === "all") setFilter("all");
    const el = document.querySelector(`[data-loc-key="${next.key}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    (el as HTMLElement | null)?.querySelector("textarea")?.focus();
  }

  if (!draft) {
    return <p className={styles.note}>{error || "正在读取剧本…"}</p>;
  }

  const hasLocale = Boolean(active);

  return (
    <div className={styles.wrap} data-testid="localization-panel">
      <p className={styles.lead}>
        把剧本翻成别的语言，导出后玩家用哪种语言就显示哪种译文；
        <strong>没翻的句子自动用原文</strong>，所以可以一句一句慢慢来，不会出现空白对话。
        这一页只读取台词/旁白/选项，不改动你的正文。
      </p>

      <div className={styles.head}>
        <div className={styles.steps}>
          <span className={hasLocale ? styles.stepDone : styles.stepNow}>① 加语言</span>
          <span className={styles.stepSep}>→</span>
          <span className={hasLocale ? styles.stepNow : styles.stepIdle}>② 术语表</span>
          <span className={styles.stepSep}>→</span>
          <span className={hasLocale ? styles.stepNow : styles.stepIdle}>③ 逐句翻译</span>
          <span className={styles.stepSep}>→</span>
          <span className={styles.stepIdle}>④ 导出</span>
        </div>
        <button type="button" className={styles.btn} onClick={() => void save()} disabled={busy}>
          {busy ? "处理中…" : dirty ? "保存（有改动）" : "保存"}
        </button>
      </div>

      {msg ? <p className={styles.ok}>{msg}</p> : null}
      {error ? <p className={styles.bad}>{error}</p> : null}

      {/* ── 步骤 ① 语言 ── */}
      <section className={styles.blocks}>
        <span className={styles.subTitle}>① 要翻成哪些语言</span>
        <div className={styles.chips}>
          {draft.locales.map((l) => {
            const p = progressFor(entries, l.code);
            return (
              <button
                key={l.code}
                type="button"
                className={l.code === active ? styles.chipOn : styles.chip}
                onClick={() => setActive(l.code)}
              >
                {l.name}
                {p.total ? (
                  <span className={styles.chipNum}>
                    {p.done}/{p.total}
                  </span>
                ) : null}
              </button>
            );
          })}
          {SUGGESTED.filter((s) => !draft.locales.some((l) => l.code === s.code)).map((s) => (
            <button
              key={s.code}
              type="button"
              className={styles.chipAdd}
              onClick={() => addLocale(s.code, s.name)}
            >
              + {s.name}
            </button>
          ))}
        </div>
        <div className={styles.chips}>
          <input
            className={styles.mini}
            value={newCode}
            onChange={(e) => setNewCode(e.target.value)}
            placeholder="语言代码，如 fr"
            aria-label="语言代码"
          />
          <input
            className={styles.mini}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="显示名，如 Français"
            aria-label="语言显示名"
          />
          <button
            type="button"
            className={styles.btn}
            disabled={!newCode.trim()}
            onClick={() => addLocale(newCode, newName)}
          >
            添加其它语言
          </button>
        </div>
      </section>

      {!hasLocale ? (
        <p className={styles.note}>
          点上面的语言就能开始，可以同时加好几种。加完之后下面会出现术语表与逐句翻译列表。
        </p>
      ) : (
        <>
          {/* ── 步骤 ② 术语表 ── */}
          <section className={styles.blocks}>
            <span className={styles.subTitle}>② 术语表（建议先填：人名、地名、专有名词）</span>
            <p className={styles.note}>
              填好后，含这些词的句子可以一键预填译名，你只改句子部分；也能保证同一个词全书译法一致。
            </p>
            <ul className={styles.glossary}>
              {draft.glossary.map((g, i) => (
                <li key={`${g.term}-${i}`}>
                  <span className={styles.term}>{g.term}</span>
                  <span className={styles.arrow}>→</span>
                  <input
                    className={styles.mini}
                    value={g.targets?.[active] ?? ""}
                    onChange={(ev) =>
                      mutate((d) => ({
                        ...d,
                        glossary: d.glossary.map((x, j) =>
                          j === i
                            ? { ...x, targets: { ...x.targets, [active]: ev.target.value } }
                            : x
                        ),
                      }))
                    }
                    placeholder={`${active} 译名`}
                    aria-label={`${g.term} 的译名`}
                  />
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() =>
                      mutate((d) => ({
                        ...d,
                        glossary: d.glossary.filter((_, j) => j !== i),
                      }))
                    }
                  >
                    删除
                  </button>
                </li>
              ))}
              {draft.glossary.length === 0 ? (
                <li className={styles.note}>
                  还没有术语。用下面这行加一个，例如「林夏 → Linxia」
                </li>
              ) : null}
            </ul>
            <div className={styles.chips}>
              <input
                className={styles.mini}
                value={newTerm}
                onChange={(e) => setNewTerm(e.target.value)}
                placeholder="原文，如 林夏"
                aria-label="术语原文"
              />
              <span className={styles.arrow}>→</span>
              <input
                className={styles.mini}
                value={newTermTarget}
                onChange={(e) => setNewTermTarget(e.target.value)}
                placeholder={`${active} 译名`}
                aria-label="术语译名"
              />
              <button
                type="button"
                className={styles.btn}
                disabled={!newTerm.trim()}
                onClick={() => {
                  const term = newTerm.trim();
                  const target = newTermTarget.trim();
                  mutate((d) => ({
                    ...d,
                    glossary: [
                      ...d.glossary,
                      { term, targets: target ? { [active]: target } : {} },
                    ],
                  }));
                  setNewTerm("");
                  setNewTermTarget("");
                }}
              >
                添加术语
              </button>
            </div>
          </section>

          {/* ── 步骤 ③ 逐句翻译 ── */}
          <section className={styles.blocks}>
            <div className={styles.progressRow}>
              <span className={styles.subTitle}>
                ③ 逐句翻译 · {active} 已完成 {overall.done}/{overall.total}（{overall.pct}%）
              </span>
              {hasUntranslated(entries, active) ? (
                <button type="button" className={styles.btn} onClick={jumpToNextUntranslated}>
                  跳到下一条未翻
                </button>
              ) : null}
              <button
                type="button"
                className={styles.btnPrimary}
                onClick={() => void aiTranslate(false)}
                disabled={busy || !hasUntranslated(entries, active)}
                title="用站点模型把这批还没翻的句子译成草稿，之后你逐句校对"
              >
                {busy ? "AI 翻译中…" : "AI 代翻（未翻的句子）"}
              </button>
              <button
                type="button"
                className={styles.btn}
                onClick={() => void prefill()}
                disabled={busy}
              >
                用术语表预填
              </button>
            </div>
            <p className={styles.note}>
              AI 只会把这批句子译成<strong>草稿</strong>，状态标成「AI 译·待校对」，
              已有人工译文不会被覆盖；<strong>导出前请逐句过一遍</strong>——
              机器译文会写错语气、人称和双关，这类错只有你能发现。
            </p>
            <div className={styles.bar} aria-hidden>
              <span style={{ width: `${Math.max(overall.pct, 1)}%` }} />
            </div>
            <div className={styles.chips}>
              <button
                type="button"
                className={filter === "all" ? styles.chipOn : styles.chip}
                onClick={() => setFilter("all")}
              >
                全部
              </button>
              <button
                type="button"
                className={filter === "todo" ? styles.chipOn : styles.chip}
                onClick={() => setFilter("todo")}
              >
                只看没翻的
              </button>
              <select
                className={styles.mini}
                value={onlyChapter}
                onChange={(e) => setOnlyChapter(e.target.value)}
                aria-label="按章节筛选"
              >
                <option value="">全部章节</option>
                {groups.map((g) => (
                  <option key={g.chapterId} value={g.chapterId}>
                    {g.title}（{g.translated}/{g.total}）
                  </option>
                ))}
              </select>
            </div>

            <ul className={styles.entries}>
              {groups
                .filter((g) => !onlyChapter || g.chapterId === onlyChapter)
                .map((g) => {
                  const visible = (filter === "todo"
                    ? g.entries.filter((e) => !(e.targets?.[active] || "").trim())
                    : g.entries
                  ).slice();
                  if (!visible.length) return null;
                  return (
                    <li key={g.chapterId} className={styles.group}>
                      <p className={styles.groupTitle}>
                        {g.title}
                        <span className={styles.groupNum}>
                          {g.translated}/{g.total}
                        </span>
                      </p>
                      <ul className={styles.entries}>
                        {visible.map((e) => (
                          <li key={e.key} className={styles.entry} data-loc-key={e.key}>
                            <div className={styles.entryHead}>
                              <span className={styles.status}>
                                {STATUS_LABEL[e.status?.[active] ?? ""] ?? "未翻"}
                              </span>
                              <span className={styles.kind}>
                                {KIND_LABEL[e.kind] ?? e.kind}
                              </span>
                              <button
                                type="button"
                                className={styles.link}
                                onClick={() =>
                                  mutate((d) => ({
                                    ...d,
                                    entries: d.entries.map((x) =>
                                      x.key === e.key
                                        ? {
                                            ...x,
                                            status: {
                                              ...x.status,
                                              [active]:
                                                x.status?.[active] === "reviewed"
                                                  ? "translated"
                                                  : "reviewed",
                                            },
                                          }
                                        : x
                                    ),
                                  }))
                                }
                              >
                                {e.status?.[active] === "reviewed" ? "取消校对" : "标记已校对"}
                              </button>
                            </div>
                            <p className={styles.source}>{e.source}</p>
                            <textarea
                              className={styles.target}
                              value={e.targets?.[active] ?? ""}
                              onChange={(ev) =>
                                mutate((d) => ({
                                  ...d,
                                  entries: d.entries.map((x) =>
                                    x.key === e.key
                                      ? {
                                          ...x,
                                          targets: { ...x.targets, [active]: ev.target.value },
                                          status: {
                                            ...x.status,
                                            [active]: ev.target.value.trim()
                                              ? "translated"
                                              : "",
                                          },
                                        }
                                      : x
                                  ),
                                }))
                              }
                              placeholder={`在这里写 ${active} 译文（留空则游戏里显示上面的原文）`}
                              rows={2}
                            />
                          </li>
                        ))}
                      </ul>
                    </li>
                  );
                })}
            </ul>
            {filter === "todo" && !hasUntranslated(entries, active) ? (
              <p className={styles.ok}>这个语言已经没有未翻的句子了。</p>
            ) : null}
          </section>

          {/* ── 步骤 ④ 导出 ── */}
          <section className={styles.blocks}>
            <span className={styles.subTitle}>④ 导出给 Ren'Py</span>
            <p className={styles.note}>
              导出的 zip 里是 <code>tl/&lt;语言&gt;/strings.rpy</code>。解压后把 <code>tl</code>{" "}
              文件夹整个放进 Ren'Py 项目的 <code>game/</code> 目录，游戏内切换语言就会显示你的译文
              （只导出已翻好的句子）。
            </p>
            <div className={styles.chips}>
              <button type="button" className={styles.btn} onClick={() => void exportZip()}>
                导出 tl 包（.zip）
              </button>
              <button type="button" className={styles.link} onClick={() => void load()}>
                剧本改过了？点这里同步改动
              </button>
            </div>
          </section>

          <button type="button" className={styles.link} onClick={() => setShowWhy((v) => !v)}>
            {showWhy ? "收起说明" : "改稿之后译文会怎样？（点开看）"}
          </button>
          {showWhy ? (
            <p className={styles.note}>
              译文按「句子内容」对账，不是按位置：插入新段落后，原来翻过的句子会自动接回去；
              如果某一句的原文被改写了，那一句的旧译文会被清空（宁可让你重翻一句，
              也不会把上一句的译文贴到新句子上）；删掉的句子会从列表里消失，译文一并清掉。
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
