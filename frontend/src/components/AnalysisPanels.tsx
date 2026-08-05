import { useMemo, useState } from "react";
import { voiceCheck } from "../api/client";
import { buildBranchTree, type BranchNode } from "../lib/branchTree";
import { uid } from "../lib/vnLocal";
import type {
  CharacterLink,
  TimelineEvent,
  VoiceReport,
  VnProject,
} from "../types/vn";
import styles from "./AnalysisPanels.module.css";

type Props = {
  project: VnProject;
  chapterId: string;
  draft?: string;
  onChange: (updater: (p: VnProject) => VnProject) => void;
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

export function AnalysisPanels({ project, chapterId, onChange }: Props) {
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

  const tree = useMemo(
    () => buildBranchTree(project, chapterId),
    [project, chapterId]
  );

  const charLinks = project.characterLinks ?? [];
  const timeline = [...(project.timeline ?? [])].sort(
    (a, b) => a.order - b.order
  );

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
    };
    onChange((p) => ({
      ...p,
      characterLinks: [...(p.characterLinks ?? []), link],
    }));
  }

  function addTimelineEvent() {
    const title = window.prompt("时间节点标题", "新节点");
    if (!title) return;
    const ev: TimelineEvent = {
      id: uid("tl"),
      title,
      when: "未标注时间",
      summary: "",
      order: (project.timeline?.length ?? 0) + 1,
      chapterRef: chapterId,
    };
    onChange((p) => ({
      ...p,
      timeline: [...(p.timeline ?? []), ev],
    }));
  }

  return (
    <section className={styles.wrap}>
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
            根据当前章节的 label / menu / jump 自动生成。假选择与断链一目了然。
          </p>
          {tree[0]?.children.length ? (
            <BranchView nodes={tree} />
          ) : (
            <p className={styles.hint}>本章尚无分支结构。</p>
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
                <g key={l.id}>
                  <line
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke="currentColor"
                    strokeOpacity={0.35}
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
          <ul className={styles.linkList}>
            {charLinks.map((l) => {
              const a = project.characters.find((c) => c.id === l.fromId);
              const b = project.characters.find((c) => c.id === l.toId);
              return (
                <li key={l.id}>
                  <span>
                    {a?.displayName ?? "?"} —{l.label}→ {b?.displayName ?? "?"}
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
            <button type="button" onClick={addTimelineEvent}>
              添加时间节点
            </button>
          </div>
          <div className={styles.timeline}>
            {timeline.map((ev) => (
              <article key={ev.id} className={styles.tlCard}>
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
          <div className={styles.toolbar}>
            <button
              type="button"
              disabled={voiceBusy}
              onClick={() => void runVoice()}
            >
              {voiceBusy ? "检查中…" : "生成语气一致性报告"}
            </button>
          </div>
          {voiceError && <p className={styles.error}>{voiceError}</p>}
          {voiceReport && (
            <div className={styles.report}>
              <p className={styles.summary}>{voiceReport.summary}</p>
              {voiceReport.issues.length === 0 ? (
                <p className={styles.hint}>未发现明显破人设问题。</p>
              ) : (
                <ul className={styles.issueList}>
                  {voiceReport.issues.map((iss, i) => (
                    <li key={i} data-sev={iss.severity}>
                      <strong>
                        [{iss.severity}] {iss.character}
                      </strong>
                      <em>「{iss.quote}」</em>
                      <span>{iss.note}</span>
                      {iss.suggestion && <p>建议：{iss.suggestion}</p>}
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
