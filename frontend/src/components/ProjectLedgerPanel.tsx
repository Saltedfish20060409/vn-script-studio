import { useMemo, useState } from "react";
import {
  buildChapterRows,
  groupCharacterStates,
  summarizeLedger,
} from "../lib/ledgerView";
import type { VnProject } from "../types/vn";
import styles from "./ProjectLedgerPanel.module.css";

type Props = {
  project: VnProject;
  /** 跳到写作区看某一章（可选：由 StudioApp 注入） */
  onOpenChapter?: (chapterId: string) => void;
};

function fmtTime(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

function clip(s: string, n: number): string {
  const t = (s || "").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

/**
 * 账本 / 摘要视图：把服务端**保存时自动攒**的两样东西翻给用户看。
 *
 * 为什么要有这一页（2026-09 结论）：自动生成的章节摘要此前 159/159 项目都有，
 * 但前端没有任何地方展示，等于没做；账本更是只躺在聊天流里。用户看不见，
 * 就会以为"这个功能不存在"。
 */
export function ProjectLedgerPanel({ project, onOpenChapter }: Props) {
  const ledger = useMemo(() => project.writingLedger || {}, [project.writingLedger]);
  const foreshadows = useMemo(() => ledger.foreshadows || [], [ledger.foreshadows]);
  const events = useMemo(() => ledger.events || [], [ledger.events]);
  const rows = useMemo(() => buildChapterRows(project), [project]);
  const byCharacter = useMemo(() => groupCharacterStates(project), [project]);
  const overview = useMemo(() => summarizeLedger(project), [project]);

  const [openChapter, setOpenChapter] = useState<string>("");
  const [openChar, setOpenChar] = useState<string>("");
  const [showEvents, setShowEvents] = useState(false);

  const paidCount = overview.paidForeshadows;

  return (
    <div className={styles.wrap} data-testid="project-ledger-panel">
      <div className={styles.head}>
        <div className={styles.cards}>
          <div className={styles.card}>
            <span>已入库章节</span>
            <strong>
              {overview.digested}/{overview.chapters}
            </strong>
          </div>
          <div className={styles.card}>
            <span>角色状态</span>
            <strong>{overview.states}</strong>
          </div>
          <div className={styles.card}>
            <span>未回收伏笔</span>
            <strong>{overview.openForeshadows}</strong>
          </div>
          <div className={styles.card}>
            <span>账本更新于</span>
            <strong className={styles.time}>{fmtTime(overview.updatedAt)}</strong>
          </div>
        </div>
        <p className={styles.note}>
          这些内容是<strong>保存时自动攒的</strong>（纯本地抽取，不调模型、不额外花钱）：
          章节摘要、出场角色、角色情绪与最近动作、章末钩子。它们会作为「项目硬锚」
          自动写进 AI 责编的上下文，让续写/审稿不跑偏——你不需要下任何命令。
        </p>
      </div>

      <section className={styles.block}>
        <h3 className={styles.blockTitle}>章节摘要</h3>
        {rows.length === 0 ? (
          <p className={styles.empty}>还没有章节。写第一章并保存后，这里会自动出现。</p>
        ) : (
          <ul className={styles.chapterList}>
            {rows.map((r, i) => {
              const id = r.entry.chapterId;
              const expanded = openChapter === id;
              return (
                <li key={id} className={styles.chapterItem}>
                  <button
                    type="button"
                    className={styles.chapterHead}
                    onClick={() => setOpenChapter(expanded ? "" : id)}
                    aria-expanded={expanded}
                  >
                    <span className={styles.chapterIdx}>{i + 1}</span>
                    <span className={styles.chapterTitle}>
                      {r.entry.title || "未命名章节"}
                    </span>
                    <span className={styles.badges}>
                      {r.fact ? (
                        <span className={styles.badgeOn}>已入库</span>
                      ) : (
                        <span className={styles.badgeOff}>待入库</span>
                      )}
                      {r.openForeshadows > 0 ? (
                        <span className={styles.badgeWarn}>
                          未回收钩子 {r.openForeshadows}
                        </span>
                      ) : null}
                      {r.states.length > 0 ? (
                        <span className={styles.badgeDim}>
                          状态 {r.states.length}
                        </span>
                      ) : null}
                    </span>
                    <span className={styles.chev}>{expanded ? "−" : "+"}</span>
                  </button>

                  {expanded ? (
                    <div className={styles.chapterBody}>
                      {r.entry.synopsis ? (
                        <p className={styles.line}>
                          <b>梗概</b>
                          {r.entry.synopsis}
                        </p>
                      ) : null}
                      {r.entry.speakers?.length ? (
                        <p className={styles.line}>
                          <b>出场</b>
                          {r.entry.speakers.join("、")}
                        </p>
                      ) : null}
                      {r.entry.openHook ? (
                        <p className={styles.line}>
                          <b>开场</b>
                          {clip(r.entry.openHook, 160)}
                        </p>
                      ) : null}
                      {r.entry.closeHook ? (
                        <p className={styles.line}>
                          <b>收束</b>
                          {clip(r.entry.closeHook, 160)}
                        </p>
                      ) : null}
                      {r.fact?.facts?.length ? (
                        <div className={styles.subBlock}>
                          <span className={styles.subTitle}>账本记录</span>
                          <ul className={styles.factList}>
                            {r.fact.facts.map((f, k) => (
                              <li key={k}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {r.states.length ? (
                        <div className={styles.subBlock}>
                          <span className={styles.subTitle}>
                            本章角色状态
                          </span>
                          <ul className={styles.stateList}>
                            {r.states.map((s, k) => (
                              <li key={s.id || k}>
                                <b>{s.characterName || "角色"}</b>
                                <span>情绪 {s.emotion || "—"}</span>
                                <span className={styles.dim}>
                                  {clip(s.body || "—", 60)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {r.fact?.keyQuotes?.length ? (
                        <div className={styles.subBlock}>
                          <span className={styles.subTitle}>对白锚</span>
                          <ul className={styles.quoteList}>
                            {r.fact.keyQuotes.map((q, k) => (
                              <li key={k}>{q}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      <div className={styles.bodyFoot}>
                        <span className={styles.dim}>
                          入库时间 {fmtTime(r.fact?.updatedAt)}
                        </span>
                        {onOpenChapter ? (
                          <button
                            type="button"
                            className={styles.linkBtn}
                            onClick={() => onOpenChapter(id)}
                          >
                            去写这一章
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={styles.block}>
        <h3 className={styles.blockTitle}>角色状态快照</h3>
        {byCharacter.length === 0 ? (
          <p className={styles.empty}>
            还没有角色状态。写完有对白的章节并保存，这里会自动记录每个角色的情绪与最近动作。
          </p>
        ) : (
          <ul className={styles.charList}>
            {byCharacter.map(([name, list]) => {
              const latest = list[list.length - 1];
              const expanded = openChar === name;
              return (
                <li key={name} className={styles.charItem}>
                  <button
                    type="button"
                    className={styles.charHead}
                    onClick={() => setOpenChar(expanded ? "" : name)}
                    aria-expanded={expanded}
                  >
                    <span className={styles.charName}>{name}</span>
                    <span className={styles.charNow}>
                      {latest.emotion || "—"} · {clip(latest.body || "—", 40)}
                    </span>
                    <span className={styles.dim}>
                      {latest.chapterTitle || ""}
                    </span>
                    <span className={styles.chev}>{expanded ? "−" : "+"}</span>
                  </button>
                  {expanded ? (
                    <ul className={styles.charHistory}>
                      {list
                        .slice()
                        .reverse()
                        .map((s, k) => (
                          <li key={s.id || k}>
                            <span className={styles.dim}>
                              {s.chapterTitle || s.chapterId || "—"}
                            </span>
                            <span>情绪 {s.emotion || "—"}</span>
                            <span>{clip(s.body || "—", 70)}</span>
                            {s.relations && s.relations !== "—" ? (
                              <span className={styles.dim}>
                                关系 {clip(s.relations, 40)}
                              </span>
                            ) : null}
                          </li>
                        ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={styles.block}>
        <h3 className={styles.blockTitle}>
          伏笔
          {paidCount > 0 ? (
            <span className={styles.dim}>（已回收 {paidCount}）</span>
          ) : null}
        </h3>
        {foreshadows.length === 0 ? (
          <p className={styles.empty}>
            还没有伏笔。章末钩子会被自动记为「未回收」，续写时提示模型回收它。
          </p>
        ) : (
          <ul className={styles.hookList}>
            {foreshadows
              .slice()
              .reverse()
              .map((f, k) => (
                <li
                  key={f.id || k}
                  className={f.status === "paid" ? styles.hookPaid : styles.hookOpen}
                >
                  <span className={styles.hookStatus}>
                    {f.status === "paid" ? "已回收" : "未回收"}
                  </span>
                  <span className={styles.hookText}>{clip(f.hook || "", 140)}</span>
                  <span className={styles.dim}>{f.note || ""}</span>
                </li>
              ))}
          </ul>
        )}
      </section>

      {events.length > 0 ? (
        <section className={styles.block}>
          <button
            type="button"
            className={styles.blockToggle}
            onClick={() => setShowEvents((v) => !v)}
            aria-expanded={showEvents}
          >
            <h3 className={styles.blockTitle}>入库日志（{events.length}）</h3>
            <span className={styles.chev}>{showEvents ? "−" : "+"}</span>
          </button>
          {showEvents ? (
            <ul className={styles.eventList}>
              {events
                .slice()
                .reverse()
                .map((e, k) => (
                  <li key={e.id || k}>
                    <span className={styles.dim}>{fmtTime(e.updatedAt)}</span>
                    <span>{clip(e.summary || "", 140)}</span>
                  </li>
                ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
