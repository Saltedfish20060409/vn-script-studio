import { useCallback, useEffect, useState } from "react";
import {
  fetchNovelAudit,
  type AuditSeverity,
  type NovelAuditChapter,
  type NovelAuditOut,
} from "../api/projects";
import { formatWords } from "../lib/wordCount";
import styles from "./NovelAuditPanel.module.css";

type Props = {
  projectId: string;
  /** 点线索里的章节 → 跳到那一章去改 */
  onOpenChapter: (chapterId: string) => void;
};

const LEVEL_LABEL: Record<string, string> = {
  strong: "强",
  medium: "中",
  weak: "偏弱",
  empty: "空章",
};

const SEVERITY_LABEL: Record<AuditSeverity, string> = {
  error: "错误",
  warn: "提醒",
  info: "提示",
};

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

function HookCell({ score, level }: { score: number; level: string }) {
  return (
    <span className={level === "weak" ? styles.hookWeak : styles.hookOk}>
      {score.toFixed(2)}（{LEVEL_LABEL[level] ?? level}）
    </span>
  );
}

/**
 * 稿件体检面板。
 *
 * 全部数字都来自后端的**确定性统计**（正则 + 计数），不调用模型——所以它便宜到可以
 * 每改完一章点一次，也不会因为模型心情好坏给出不同答案。面板只做两件事：
 * 把线索按"第几章第几行"摊开（点一下跳过去改），以及**如实说明覆盖到哪**：
 * 哪几章没正文、哪几章被截断、问题是否被截断显示——作者不该看到一个"全绿"却不知其所以然的面板。
 *
 * 视角 / 称呼那两组是启发式（后端在 `notes` 与 `heuristic` 标志里写明），这里照原样标出，
 * 不包装成结论。
 */
export function NovelAuditPanel({ projectId, onOpenChapter }: Props) {
  const [data, setData] = useState<NovelAuditOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showNotes, setShowNotes] = useState(false);

  const run = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      // 三部分都要：表记/视角一致性、文面读数（含文体剖面）、改编检查表。
      // 都是离线统计（不调模型），所以一次拿全比来回点便宜。
      setData(await fetchNovelAudit(projectId, { parts: "consistency,craft,adapt" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "体检失败");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  useEffect(() => {
    void run();
  }, [run]);

  const consistency = data?.consistency;
  const craft = data?.craft;
  const adapt = data?.adapt;
  const sev = consistency?.counts?.bySeverity ?? {};
  const issues = consistency?.issues ?? [];
  const rubyIssues = craft?.rubyIssues ?? [];

  return (
    <div className={styles.wrap} data-testid="novel-audit-panel">
      <div className={styles.toolbar}>
        <span>
          稿件体检 — 标点/引号/人名/视角 + 注音/拟声/章末钩子
          <span className={styles.badge}>不调用模型</span>
        </span>
        <button type="button" className={styles.ghost} disabled={busy} onClick={() => void run()}>
          {busy ? "体检中…" : "重新体检"}
        </button>
      </div>

      {error ? <p className={styles.error}>{error}</p> : null}
      {!data && !error ? <p className={styles.hint}>正在跑体检…</p> : null}

      {data ? (
        <>
          {consistency ? (
            <div className={styles.cards}>
              <div className={styles.card}>
                <span className={styles.cardLabel}>表记线索</span>
                <strong className={styles.cardValue}>
                  {sev.error ?? 0}
                  <span className={styles.cardUnit}> 错误</span>
                </strong>
                <span className={styles.cardSub}>
                  {sev.warn ?? 0} 提醒 · {sev.info ?? 0} 提示
                </span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>扫描覆盖</span>
                <strong className={styles.cardValue}>
                  {consistency.coverage.chaptersScanned}
                  <span className={styles.cardUnit}>
                    {" "}
                    / {consistency.coverage.chaptersTotal} 章
                  </span>
                </strong>
                <span className={styles.cardSub}>
                  有正文 {consistency.coverage.chaptersWithText} 章 ·{" "}
                  {Math.round(consistency.coverage.coverageRatio * 100)}%
                </span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>主导视角（启发式）</span>
                <strong className={styles.cardValue}>{consistency.pov.dominantLabel || "信号不足"}</strong>
                <span className={styles.cardSub}>
                  我 {consistency.pov.bookFirstPerson} · 他/她 {consistency.pov.bookThirdPerson}
                </span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>注音问题</span>
                <strong className={styles.cardValue}>{rubyIssues.length}</strong>
                <span className={styles.cardSub}>
                  统计 {craft?.coverage.chaptersAnalyzed ?? 0} 章 ·{" "}
                  {formatWords(craft?.coverage.wordsScanned ?? 0)} 字
                </span>
              </div>
            </div>
          ) : null}

          {consistency && consistency.coverage.issuesTruncated > 0 ? (
            <p className={styles.warnLine}>
              线索太多，这里只列了前 {consistency.coverage.issuesReported} 条（共检出{" "}
              {consistency.coverage.issuesFound} 条）。
            </p>
          ) : null}
          {consistency && consistency.coverage.textTruncatedChapters.length > 0 ? (
            <p className={styles.warnLine}>
              有 {consistency.coverage.textTruncatedChapters.length} 章超过单章扫描上限，
              尾部未被检查。
            </p>
          ) : null}
          {craft && craft.coverage.truncated ? (
            <p className={styles.warnLine}>
              文面统计触到了章数/字数上限，只统计了前 {craft.coverage.chaptersAnalyzed} 章。
            </p>
          ) : null}

          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>线索（点章节跳过去改）</h3>
            {issues.length === 0 ? (
              <p className={styles.hint}>
                没有发现表记类问题。注意这只说明"没查到这些模式"，不等于稿子没有问题。
              </p>
            ) : (
              <ul className={styles.issues}>
                {issues.slice(0, 80).map((iss, i) => (
                  <li key={`${iss.code}-${iss.chapterId}-${i}`} className={styles.issue}>
                    <span className={styles[`sev_${iss.severity}`]}>
                      {SEVERITY_LABEL[iss.severity] ?? iss.severity}
                    </span>
                    <button
                      type="button"
                      className={styles.chapterBtn}
                      onClick={() => onOpenChapter(iss.chapterId)}
                    >
                      第 {iss.chapterOrdinal} 章 {iss.chapterTitle}
                      {iss.line ? ` · 第 ${iss.line} 行` : ""}
                    </button>
                    <span className={styles.issueMsg}>
                      {iss.message}
                      {/* 依据随手可查：作者看到提示的第一反应是"凭什么"，不藏在文档里 */}
                      {iss.basis ? (
                        <span className={styles.issueBasis}>依据：{iss.basis}</span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {issues.length > 80 ? (
              <p className={styles.hint}>还有 {issues.length - 80} 条未列出。</p>
            ) : null}
          </div>

          {rubyIssues.length > 0 ? (
            <div className={styles.section}>
              <h3 className={styles.sectionTitle}>注音写法</h3>
              <ul className={styles.issues}>
                {rubyIssues.slice(0, 40).map((iss, i) => (
                  <li key={`${iss.code}-${i}`} className={styles.issue}>
                    <span className={styles[`sev_${iss.severity}`]}>
                      {SEVERITY_LABEL[iss.severity] ?? iss.severity}
                    </span>
                    <button
                      type="button"
                      className={styles.chapterBtn}
                      onClick={() => onOpenChapter(iss.chapterId)}
                    >
                      第 {iss.chapterTitle}
                      {iss.line ? ` · 第 ${iss.line} 行` : ""}
                    </button>
                    <span className={styles.issueMsg}>{iss.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {craft?.styleProfile && craft.styleProfile.readings.length > 0 ? (
            <div className={styles.section} data-testid="novel-audit-style-profile">
              <h3 className={styles.sectionTitle}>文体剖面（读数，不是评分）</h3>
              <ul className={styles.list}>
                {craft.styleProfile.readings.map((r, i) => (
                  <li key={`${r.label}-${i}`}>
                    <strong>{r.label}</strong>：{r.value}
                    {/* 每条读数都带依据：作者能核对"这个数凭什么这么说" */}
                    <span className={styles.hint}>（依据：{r.basis}）</span>
                  </li>
                ))}
              </ul>
              <p className={styles.hint}>{craft.styleProfile.note}</p>
            </div>
          ) : null}

          {adapt && adapt.items.length > 0 ? (
            <div className={styles.section} data-testid="novel-audit-adapt">
              <h3 className={styles.sectionTitle}>
                改编检查表（小说 → 视觉小说）
                <span className={styles.badge}>
                  {adapt.counts.warn} 条要动手 · {adapt.counts.info} 条提示
                </span>
              </h3>
              <ul className={styles.list}>
                {adapt.items.map((item, i) => (
                  <li key={`${item.code}-${i}`}>
                    <strong>{item.title}</strong>
                    {item.where ? <em>（{item.where}）</em> : null}
                    {/* why = 依据，action = 具体改法：两者都要显示，不能只给结论 */}
                    <span className={styles.hint}>{item.why}</span>
                    <span className={styles.hint}>改法：{item.action}</span>
                  </li>
                ))}
              </ul>
              <p className={styles.hint}>
                只统计有正文的章节（{adapt.coverage.chaptersWithText}/
                {adapt.coverage.chaptersTotal} 章 · 分场块 {adapt.coverage.sceneBlocks} 个）。
                检查表**不评写得好不好**，也**不把「没有选项」当缺陷**（kinetic 是合法形态）。
              </p>
            </div>
          ) : null}

          {craft && craft.perChapter.length > 0 ? (
            <div className={styles.section}>
              <h3 className={styles.sectionTitle}>每章文面读数</h3>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>章</th>
                    <th>字数</th>
                    <th>对白占比</th>
                    <th>平均段长</th>
                    <th>句长中位</th>
                    <th>长段落</th>
                    <th>拟声/千字</th>
                    <th>注音/千字</th>
                    <th>章末钩子</th>
                  </tr>
                </thead>
                <tbody>
                  {craft.perChapter.map((c: NovelAuditChapter) => (
                    <tr key={c.chapterId}>
                      <td>
                        <button
                          type="button"
                          className={styles.chapterBtn}
                          onClick={() => onOpenChapter(c.chapterId)}
                        >
                          {c.chapterTitle}
                        </button>
                      </td>
                      <td>{formatWords(c.words.total)}</td>
                      <td>{pct(c.ratio.dialogue)}</td>
                      <td>{c.paragraphs.avgChars}</td>
                      <td>{c.sentence?.p50 ?? "—"}</td>
                      <td>{c.paragraphs.longCount}</td>
                      <td>{c.onomatopoeia.per1000Chars.toFixed(1)}</td>
                      <td>{c.ruby.per1000Chars.toFixed(1)}</td>
                      <td>
                        <HookCell score={c.hook.score} level={c.hook.level} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className={styles.hint}>
                钩子是**启发式评分**（末段类型/长度/收尾标点/账本记账四项加权），不是文学判断；
                对白占比在"混合行"口径下会略微偏低；句长按句末标点切句（逗号不断句）。
              </p>
            </div>
          ) : null}

          <div className={styles.section}>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => setShowNotes((v) => !v)}
            >
              {showNotes ? "收起" : "口径与局限（这些数字能说明什么、不能说明什么）"}
            </button>
            {showNotes ? (
              <div className={styles.notes}>
                {[...(consistency?.notes ?? []), ...(craft?.notes ?? [])].map((n, i) => (
                  <p key={i} className={styles.hint}>
                    · {n}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
