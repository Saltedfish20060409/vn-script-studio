import { useEffect, useMemo, useState } from "react";
import {
  factsAccept,
  factsAckStale,
  factsInbox,
  factsReconcile,
  factsReject,
  factsScan,
  voiceCheck,
} from "../api/client";
import { buildBranchTree, type BranchNode } from "../lib/branchTree";
import { weakSyncCharacters } from "../lib/factSync";
import { uid } from "../lib/vnLocal";
import { mascotLine } from "../lib/mascotCopy";
import type {
  CharacterLink,
  FactInboxItem,
  TimelineEvent,
  VoiceReport,
  VnProject,
} from "../types/vn";
import { EmptyStage } from "./EmptyStage";
import { FactExtractReview } from "./FactExtractReview";
import { usePrompt } from "./ConfirmDialog";
import styles from "./AnalysisPanels.module.css";

type Props = {
  project: VnProject;
  chapterId: string;
  draft?: string;
  onChange: (updater: (p: VnProject) => VnProject) => void;
  /** Server-persisted snapshot — must preserve updatedAt and skip autosave */
  onRemoteProject?: (project: VnProject) => void;
};

function BranchView({
  nodes,
  depth = 0,
}: {
  nodes: BranchNode[];
  depth?: number;
}) {
  return (
    <ul className={styles.tree} style={{ marginLeft: depth ? 12 : 0 }}>
      {nodes.map((n) => (
        <li key={n.id} data-kind={n.kind}>
          <span className={styles.treeNode}>{n.title}</span>
          {n.children.length > 0 && (
            <BranchView nodes={n.children} depth={depth + 1} />
          )}
        </li>
      ))}
    </ul>
  );
}

export function AnalysisPanels({
  project,
  chapterId,
  onChange,
  onRemoteProject,
}: Props) {
  const prompt = usePrompt();
  const [sub, setSub] = useState<"branch" | "chars" | "timeline" | "voice">(
    "branch"
  );
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceReport, setVoiceReport] = useState<VoiceReport | null>(null);
  const [voiceError, setVoiceError] = useState("");
  const [linkDraft, setLinkDraft] = useState({
    fromId: "",
    toId: "",
    label: "相识",
  });
  const [factBusy, setFactBusy] = useState(false);
  const [factMsg, setFactMsg] = useState("");
  const [scanPrompt, setScanPrompt] = useState<string | null>(null);
  const [inbox, setInbox] = useState<FactInboxItem[]>([]);
  const [reviewOpen, setReviewOpen] = useState(false);

  function applyRemote(next: VnProject) {
    if (onRemoteProject) onRemoteProject(next);
    else onChange(() => next);
  }

  const tree = useMemo(
    () => buildBranchTree(project, chapterId),
    [project, chapterId]
  );

  const charLinks = project.characterLinks ?? [];
  const timeline = [...(project.timeline ?? [])].sort(
    (a, b) => a.order - b.order
  );
  const staleCount =
    charLinks.filter((l) => l.stale).length +
    timeline.filter((t) => t.stale).length;

  const charLayout = useMemo(() => {
    const w = 640;
    const h = 360;
    const cx = w / 2;
    const cy = h / 2;
    const r = 120;
    return project.characters.map((c, i) => {
      const a =
        project.characters.length <= 1
          ? 0
          : (i / project.characters.length) * Math.PI * 2 - Math.PI / 2;
      return { ...c, x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r };
    });
  }, [project.characters]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        setFactBusy(true);
        const rec = await factsReconcile(project.id);
        if (cancelled) return;
        // Only replace local project when server actually wrote (avoids wiping unsaved editor)
        if (rec.wrote) {
          applyRemote(rec.project);
        }
        const box = await factsInbox(project.id);
        if (cancelled) return;
        setInbox(box.items || []);
        const chg = rec.changed;
        const dirty =
          chg.isFirstScan ||
          chg.bible ||
          chg.chapters.length > 0 ||
          chg.characters.length > 0;
        if (dirty) {
          setScanPrompt(
            chg.isFirstScan
              ? "尚未扫描过事实层。要根据剧本 / 圣经 / 角色卡生成关系与时间线候选吗？"
              : "检测到剧本或设定变更。要增量扫描并更新待审候选吗？"
          );
        } else if (rec.staleCount > 0) {
          setFactMsg(`有 ${rec.staleCount} 条已接受事实标为待复核（出处可能漂移）。`);
        }
      } catch (e) {
        if (!cancelled) {
          setFactMsg(e instanceof Error ? e.message : "对账失败");
        }
      } finally {
        if (!cancelled) setFactBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  // Refresh inbox when agent or other surfaces bump project.updatedAt
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const box = await factsInbox(project.id);
        if (!cancelled) setInbox(box.items || []);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [project.id, project.updatedAt]);

  async function runVoice() {
    setVoiceBusy(true);
    setVoiceError("");
    try {
      const data = await voiceCheck(project.id, { chapter_id: chapterId });
      setVoiceReport(data);
    } catch (e) {
      setVoiceError(e instanceof Error ? e.message : "检查失败");
    } finally {
      setVoiceBusy(false);
    }
  }

  async function runScan(full = false) {
    setFactBusy(true);
    setFactMsg("");
    setScanPrompt(null);
    try {
      const res = await factsScan(project.id, { full });
      applyRemote(res.project);
      const box = await factsInbox(project.id);
      setInbox(box.items || []);
      setFactMsg(
        res.summary.added > 0
          ? `扫描完成：新增 ${res.summary.added} 条待审（关系 ${res.summary.characterLinks} / 时间线 ${res.summary.timelineEvents}）。`
          : "扫描完成：没有新的待审候选。"
      );
      if ((box.items || []).length > 0) setReviewOpen(true);
    } catch (e) {
      setFactMsg(e instanceof Error ? e.message : "扫描失败");
    } finally {
      setFactBusy(false);
    }
  }

  async function refreshInbox() {
    try {
      const box = await factsInbox(project.id);
      setInbox(box.items || []);
    } catch {
      /* ignore */
    }
  }

  async function onAcceptFacts(ids: string[]) {
    setFactBusy(true);
    try {
      const res = await factsAccept(project.id, ids);
      applyRemote(res.project);
      await refreshInbox();
      setReviewOpen(false);
      const skipped = res.skippedIds?.length ?? 0;
      setFactMsg(
        skipped
          ? `已接受 ${res.acceptedIds.length} 条；${skipped} 条已存在故跳过。`
          : `已接受 ${res.acceptedIds.length} 条事实。`
      );
    } catch (e) {
      setFactMsg(e instanceof Error ? e.message : "接受失败");
    } finally {
      setFactBusy(false);
    }
  }

  async function onRejectFacts(ids: string[]) {
    setFactBusy(true);
    try {
      await factsReject(project.id, ids);
      await refreshInbox();
      setReviewOpen(false);
      setFactMsg(`已拒绝 ${ids.length} 条候选。`);
    } catch (e) {
      setFactMsg(e instanceof Error ? e.message : "拒绝失败");
    } finally {
      setFactBusy(false);
    }
  }

  async function ackAllStale() {
    setFactBusy(true);
    try {
      const res = await factsAckStale(project.id, { all: true });
      applyRemote(res.project);
      setFactMsg("已清除待复核标记。");
    } catch (e) {
      setFactMsg(e instanceof Error ? e.message : "清除失败");
    } finally {
      setFactBusy(false);
    }
  }

  function addCharLink() {
    if (
      !linkDraft.fromId ||
      !linkDraft.toId ||
      linkDraft.fromId === linkDraft.toId
    )
      return;
    const link: CharacterLink = {
      id: uid("clink"),
      fromId: linkDraft.fromId,
      toId: linkDraft.toId,
      label: linkDraft.label || "关系",
      evidence: [{ source: "manual", quote: "手动添加" }],
      acceptedAt: new Date().toISOString(),
    };
    onChange((p) => ({
      ...p,
      characters: weakSyncCharacters(
        p.characters,
        link.fromId,
        link.toId,
        link.label
      ),
      characterLinks: [...(p.characterLinks ?? []), link],
    }));
  }

  async function addTimelineEvent() {
    const title = await prompt({
      title: "时间节点标题",
      defaultValue: "新节点",
      confirmLabel: "添加",
    });
    if (title === null) return;
    const trimmed = title.trim() || "新节点";
    const ev: TimelineEvent = {
      id: uid("tl"),
      title: trimmed,
      when: "未标注时间",
      summary: "",
      order: (project.timeline?.length ?? 0) + 1,
      chapterRef: chapterId,
      evidence: [{ source: "agent", quote: "手动添加" }],
      acceptedAt: new Date().toISOString(),
    };
    onChange((p) => ({
      ...p,
      timeline: [...(p.timeline ?? []), ev],
    }));
  }

  return (
    <section className={styles.wrap}>
      <div className={styles.factBar}>
        <button
          type="button"
          disabled={factBusy}
          onClick={() => void runScan(false)}
        >
          {factBusy ? "处理中…" : "扫描更新"}
        </button>
        <button
          type="button"
          disabled={factBusy}
          title="忽略增量指纹，全量重扫"
          onClick={() => void runScan(true)}
        >
          全量扫描
        </button>
        <button
          type="button"
          disabled={factBusy || inbox.length === 0}
          onClick={() => setReviewOpen(true)}
        >
          待审托盘{inbox.length ? ` (${inbox.length})` : ""}
        </button>
        {staleCount > 0 ? (
          <>
            <span className={styles.staleBadge}>待复核 {staleCount}</span>
            <button
              type="button"
              disabled={factBusy}
              onClick={() => void ackAllStale()}
            >
              确认仍有效
            </button>
          </>
        ) : null}
        {factMsg ? <span className={styles.factMsg}>{factMsg}</span> : null}
      </div>

      {scanPrompt ? (
        <div className={styles.scanPrompt} role="status">
          <p>{scanPrompt}</p>
          <div className={styles.toolbar}>
            <button
              type="button"
              disabled={factBusy}
              onClick={() => void runScan(false)}
            >
              扫描更新
            </button>
            <button
              type="button"
              className={styles.ghostBtn}
              onClick={() => setScanPrompt(null)}
            >
              暂不
            </button>
          </div>
        </div>
      ) : null}

      {reviewOpen && inbox.length > 0 ? (
        <FactExtractReview
          items={inbox}
          project={project}
          busy={factBusy}
          onCancel={() => setReviewOpen(false)}
          onConfirm={(ids) => void onAcceptFacts(ids)}
          onReject={(ids) => void onRejectFacts(ids)}
        />
      ) : null}

      <div className={styles.tabs}>
        {(
          [
            ["branch", "分支树"],
            ["chars", "角色关系"],
            ["timeline", "时间线"],
            ["voice", "语气检查"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={sub === id ? styles.tabActive : styles.tab}
            onClick={() => setSub(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {sub === "branch" && (
        <div className={styles.panel}>
          <p className={styles.hint}>
            结构事实：根据当前章节的 label / menu / jump 自动生成，不进待审托盘。
          </p>
          {tree[0]?.children.length ? (
            <BranchView nodes={tree} />
          ) : (
            <EmptyStage
              stamp="ANL"
              title="本章尚无分支结构"
              line={mascotLine("emptyAnalysis")}
              compact
            />
          )}
        </div>
      )}

      {sub === "chars" && (
        <div className={styles.panel}>
          <div className={styles.toolbar}>
            <select
              value={linkDraft.fromId}
              onChange={(e) =>
                setLinkDraft((d) => ({ ...d, fromId: e.target.value }))
              }
            >
              <option value="">角色 A</option>
              {project.characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.displayName}
                </option>
              ))}
            </select>
            <input
              value={linkDraft.label}
              onChange={(e) =>
                setLinkDraft((d) => ({ ...d, label: e.target.value }))
              }
              placeholder="关系标签"
            />
            <select
              value={linkDraft.toId}
              onChange={(e) =>
                setLinkDraft((d) => ({ ...d, toId: e.target.value }))
              }
            >
              <option value="">角色 B</option>
              {project.characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.displayName}
                </option>
              ))}
            </select>
            <button type="button" onClick={addCharLink}>
              添加关系
            </button>
          </div>
          <svg
            className={styles.graph}
            viewBox="0 0 640 360"
            role="img"
            aria-label="角色关系图"
          >
            {charLinks.map((l) => {
              const a = charLayout.find((c) => c.id === l.fromId);
              const b = charLayout.find((c) => c.id === l.toId);
              if (!a || !b) return null;
              return (
                <g key={l.id} opacity={l.stale ? 0.45 : 1}>
                  <line
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke="currentColor"
                    strokeOpacity={0.35}
                    strokeDasharray={l.stale ? "4 3" : undefined}
                  />
                  <text
                    x={(a.x + b.x) / 2}
                    y={(a.y + b.y) / 2 - 4}
                    fontSize="11"
                    fill="currentColor"
                    textAnchor="middle"
                    opacity={0.7}
                  >
                    {l.label}
                    {l.stale ? " ?" : ""}
                  </text>
                </g>
              );
            })}
            {charLayout.map((c) => (
              <g key={c.id}>
                <circle
                  cx={c.x}
                  cy={c.y}
                  r={28}
                  fill="var(--field-bg)"
                  stroke="var(--accent)"
                  strokeWidth={1.5}
                />
                <text
                  x={c.x}
                  y={c.y + 4}
                  fontSize="11"
                  textAnchor="middle"
                  fill="currentColor"
                >
                  {c.displayName.slice(0, 4)}
                </text>
              </g>
            ))}
          </svg>
          <ul className={styles.list}>
            {charLinks.map((l) => {
              const a = project.characters.find((c) => c.id === l.fromId);
              const b = project.characters.find((c) => c.id === l.toId);
              return (
                <li key={l.id}>
                  <span>
                    {a?.displayName ?? "?"} —{l.label}→ {b?.displayName ?? "?"}
                    {l.stale ? (
                      <em className={styles.staleTag} title={l.staleReason}>
                        待复核
                      </em>
                    ) : null}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      onChange((p) => ({
                        ...p,
                        characterLinks: (p.characterLinks ?? []).filter(
                          (x) => x.id !== l.id
                        ),
                      }))
                    }
                  >
                    删除
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {sub === "timeline" && (
        <div className={styles.panel}>
          <div className={styles.toolbar}>
            <button type="button" onClick={() => void addTimelineEvent()}>
              添加时间节点
            </button>
          </div>
          <div className={styles.timeline}>
            {timeline.length === 0 ? (
              <EmptyStage
                stamp="ANL"
                title="时间线还是空的"
                line={mascotLine("emptyAnalysis")}
                compact
              />
            ) : null}
            {timeline.map((ev) => (
              <article
                key={ev.id}
                className={
                  ev.stale
                    ? `${styles.tlCard} ${styles.tlCardStale}`
                    : styles.tlCard
                }
              >
                {ev.stale ? (
                  <span className={styles.staleTag} title={ev.staleReason}>
                    待复核
                  </span>
                ) : null}
                <input
                  value={ev.title}
                  onChange={(e) =>
                    onChange((p) => ({
                      ...p,
                      timeline: (p.timeline ?? []).map((t) =>
                        t.id === ev.id ? { ...t, title: e.target.value } : t
                      ),
                    }))
                  }
                />
                <input
                  value={ev.when ?? ""}
                  placeholder="时间标注"
                  onChange={(e) =>
                    onChange((p) => ({
                      ...p,
                      timeline: (p.timeline ?? []).map((t) =>
                        t.id === ev.id ? { ...t, when: e.target.value } : t
                      ),
                    }))
                  }
                />
                <textarea
                  rows={2}
                  value={ev.summary ?? ""}
                  placeholder="摘要"
                  onChange={(e) =>
                    onChange((p) => ({
                      ...p,
                      timeline: (p.timeline ?? []).map((t) =>
                        t.id === ev.id ? { ...t, summary: e.target.value } : t
                      ),
                    }))
                  }
                />
                <button
                  type="button"
                  onClick={() =>
                    onChange((p) => ({
                      ...p,
                      timeline: (p.timeline ?? []).filter((t) => t.id !== ev.id),
                    }))
                  }
                >
                  删除
                </button>
              </article>
            ))}
          </div>
        </div>
      )}

      {sub === "voice" && (
        <div className={styles.panel}>
          <p className={styles.hint}>
            观点层：语气报告不写入关系图/时间线。二期将升级为对抗式审稿并按章节版本落库。
          </p>
          <div className={styles.toolbar}>
            <button
              type="button"
              disabled={voiceBusy}
              onClick={() => void runVoice()}
            >
              {voiceBusy ? "检查中…" : "生成语气一致性报告"}
            </button>
          </div>
          {voiceBusy ? (
            <div className={styles.busyBar} role="status" aria-live="polite">
              <span className={styles.busyStamp} aria-hidden>
                RUN
              </span>
              <span className={styles.busyPulse} aria-hidden />
              <span>语气检查进行中…</span>
            </div>
          ) : null}
          {voiceError && <p className={styles.error}>{voiceError}</p>}
          {!voiceBusy && !voiceReport && !voiceError ? (
            <EmptyStage
              stamp="ANL"
              title="还没有分析结果"
              line={mascotLine("emptyAnalysis")}
              compact
            />
          ) : null}
          {voiceReport && (
            <div className={styles.report}>
              <p className={styles.summary}>{voiceReport.summary}</p>
              {voiceReport.issues.length === 0 ? (
                <p className={styles.hint}>未发现明显破人设问题。</p>
              ) : (
                <ul className={styles.issueList}>
                  {voiceReport.issues.map((issue, i) => (
                    <li key={`${issue.character}-${i}`}>
                      <strong>
                        [{issue.severity}] {issue.character}
                      </strong>
                      <span>「{issue.quote}」</span>
                      <span>{issue.note}</span>
                      {issue.suggestion ? (
                        <em>建议：{issue.suggestion}</em>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
