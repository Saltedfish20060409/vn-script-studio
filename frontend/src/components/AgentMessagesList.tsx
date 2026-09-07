import { useState } from "react";
import type { RefObject } from "react";
import { getChapterReviseDraft } from "../lib/chapterReviseDraft";
import { describeActions } from "../lib/agentFormat";
import type { AgentChatMessage, AgentTraceEvent } from "../types/vn";
import { AgentMessageBody } from "./AgentMarkdown";
import { WriterPortrait } from "./WriterPortrait";
import styles from "./AgentChat.module.css";

function AgentTracePanel({ events }: { events: AgentTraceEvent[] }) {
  const [open, setOpen] = useState(false);
  const useful = events.filter((e) => e.type !== "done");
  if (!useful.length) return null;
  const toolN = useful.filter((e) => e.type === "tool_call").length;
  const label =
    toolN > 0 ? `本轮轨迹 · ${toolN} 次工具` : `本轮轨迹 · ${useful.length} 步`;
  return (
    <div className={styles.traceBox}>
      <button
        type="button"
        className={styles.traceToggle}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "▾" : "▸"} {label}
      </button>
      {open ? (
        <ol className={styles.traceList}>
          {useful.map((e, i) => {
            if (e.type === "tool_call") {
              return (
                <li key={i} className={styles.traceItem}>
                  <strong>调用</strong> {e.name}
                  {e.arguments ? (
                    <code className={styles.traceCode}>
                      {JSON.stringify(e.arguments)}
                    </code>
                  ) : null}
                </li>
              );
            }
            if (e.type === "tool_result") {
              return (
                <li key={i} className={styles.traceItem}>
                  <strong>{e.ok === false ? "失败" : "结果"}</strong> {e.name}
                  <pre className={styles.tracePre}>
                    {(e.preview || "").slice(0, 800)}
                  </pre>
                </li>
              );
            }
            if (e.type === "actions") {
              const acts = Array.isArray(e.actions) ? e.actions : [];
              return (
                <li key={i} className={styles.traceItem}>
                  <strong>写入动作</strong> {describeActions(acts) || "（空）"}
                </li>
              );
            }
            if (e.type === "thought" && e.text) {
              return (
                <li key={i} className={styles.traceItem}>
                  <strong>思考</strong>
                  <span className={styles.traceThought}>
                    {e.text.slice(0, 280)}
                  </span>
                </li>
              );
            }
            return null;
          })}
        </ol>
      ) : null}
    </div>
  );
}

type Props = {
  messages: AgentChatMessage[];
  busy: boolean;
  thinking: string;
  liveStream: { events: AgentTraceEvent[]; text: string } | null;
  showEmptyStage: boolean;
  personaLabel: string;
  activeLensIds: string[];
  projectId: string;
  dossierOpen: boolean;
  personaOpen: boolean;
  helpOpen: boolean;
  selection: string;
  lastContext: string;
  error: string;
  undoCount: number;
  scrollerRef: RefObject<HTMLDivElement | null>;
  onOpenReviseReview: (chapterId: string) => void;
  onToggleDossier: () => void;
  onTogglePersona: () => void;
  onToggleHelp: () => void;
  onUndo: () => void;
};

/**
 * 主对话列：顶栏（卷宗 / 作家 / 说明）+ 消息滚动区（空态、气泡、轨迹、改稿 chip、
 * thinking、liveStream 流式气泡）+ 状态行 + 错误行。
 * 纯受控展示——state 与流式 / 发送 / 改稿逻辑留在 AgentChat。
 */
export function AgentMessagesList({
  messages,
  busy,
  thinking,
  liveStream,
  showEmptyStage,
  personaLabel,
  activeLensIds,
  projectId,
  dossierOpen,
  personaOpen,
  helpOpen,
  selection,
  lastContext,
  error,
  undoCount,
  scrollerRef,
  onOpenReviseReview,
  onToggleDossier,
  onTogglePersona,
  onToggleHelp,
  onUndo,
}: Props) {
  return (
    <>
      <div className={styles.cornerBar}>
        <button
          type="button"
          className={styles.dossierTab}
          aria-expanded={dossierOpen}
          aria-controls="agent-dossier"
          title="打开卷宗"
          onClick={onToggleDossier}
        >
          <img src="/agent/agent-dossier-tab.png" alt="" />
          <span>卷宗</span>
        </button>
        <div className={styles.cornerActions}>
          <button
            type="button"
            className={styles.hudBtn}
            aria-expanded={personaOpen}
            aria-label="切换作家 / 写手"
            title="切换作家 / 写手"
            onClick={onTogglePersona}
          >
            ⇄
          </button>
          <button
            type="button"
            className={styles.hudBtn}
            aria-expanded={helpOpen}
            aria-label="功能说明与推荐流程"
            title="功能说明与推荐流程"
            onClick={onToggleHelp}
          >
            !
          </button>
        </div>
      </div>

      <div
        className={styles.messages}
        ref={scrollerRef}
        onWheel={(e) => e.stopPropagation()}
      >
        {showEmptyStage ? (
          <div className={styles.emptyStage}>
            <div className={styles.emptyMark} aria-hidden>
              <span className={styles.emptySlash} />
              <span className={styles.emptyShard} />
            </div>
            <p className={styles.emptyHint}>直接输入需求开始聊，例如：「帮我改这一章」「给这段挑毛病」「续写下一场」。AI 不会在你确认前改动正文；只想听意见就加一句「先别改，只给意见」。</p>
          </div>
        ) : null}
        {messages.map((m, i) => {
          const reviseAction =
            m.role === "assistant" && m.action?.type === "open_revise_review"
              ? m.action
              : null;
          const reviseDraftAlive = reviseAction
            ? Boolean(getChapterReviseDraft(projectId, reviseAction.chapterId))
            : false;
          return (
            <div
              key={`${i}-${m.role}`}
              className={m.role === "user" ? styles.user : styles.bot}
            >
              <div className={styles.msgHead}>
                {m.role === "assistant" ? (
                  <WriterPortrait lensId={activeLensIds[0] || null} size="xs" />
                ) : null}
                <span className={styles.role}>
                  {m.role === "user"
                    ? "你"
                    : activeLensIds.length
                      ? personaLabel
                      : "编辑"}
                </span>
              </div>
              <AgentMessageBody
                content={m.content}
                mode={m.role === "user" ? "plain" : "markdown"}
              />
              {m.role === "assistant" && m.trace?.length ? (
                <AgentTracePanel events={m.trace} />
              ) : null}
              {reviseAction ? (
                <div className={styles.msgActions}>
                  <button
                    type="button"
                    className={styles.msgActionBtn}
                    disabled={busy || !reviseDraftAlive}
                    title={
                      reviseDraftAlive
                        ? "打开未写入的改稿对照"
                        : "预览已写入或已丢弃"
                    }
                    onClick={() => onOpenReviseReview(reviseAction.chapterId)}
                  >
                    {reviseDraftAlive
                      ? reviseAction.label || "打开改稿对照"
                      : "对照已结束"}
                  </button>
                </div>
              ) : null}
            </div>
          );
        })}
        {busy && (
          <div className={styles.thinkingRow}>
            <p className={styles.thinking}>
              {thinking}
              <span className={styles.typingDots} aria-hidden>
                <i />
                <i />
                <i />
              </span>
            </p>
          </div>
        )}
        {busy &&
          liveStream &&
          (liveStream.events.length > 0 || liveStream.text) && (
            <div className={styles.liveStream}>
              {liveStream.events.length > 0 && (
                <AgentTracePanel events={liveStream.events} />
              )}
              {liveStream.text && (
                <p className={styles.liveText}>{liveStream.text}</p>
              )}
            </div>
          )}
      </div>

      {(selection || lastContext) && (
        <p className={styles.statusLine} title={lastContext || undefined}>
          {selection ? `选区 ${selection.length} 字` : null}
          {selection && lastContext ? " · " : null}
          {lastContext || null}
        </p>
      )}
      {undoCount > 0 && (
        <div className={styles.undoRow}>
          <button
            type="button"
            className={styles.msgActionBtn}
            disabled={busy}
            onClick={onUndo}
            title="回滚最近一次 Agent 写入（当前对话内）"
          >
            撤回编辑（{undoCount} 步）
          </button>
        </div>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </>
  );
}
