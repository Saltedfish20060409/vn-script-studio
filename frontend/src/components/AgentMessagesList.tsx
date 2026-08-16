import { useState } from "react";
import type { RefObject } from "react";
import {
  type HarnessLintResult,
  type PipelineRunResult,
} from "../api/client";
import { getChapterReviseDraft } from "../lib/chapterReviseDraft";
import type {
  AgentAction,
  AgentChatMessage,
  AgentTraceEvent,
} from "../types/vn";
import { AgentMessageBody } from "./AgentMarkdown";
import { WriterPortrait } from "./WriterPortrait";
import styles from "./AgentChat.module.css";

const ACTION_LABEL: Record<string, string> = {
  add_character: "新增角色",
  update_character: "修改角色",
  delete_character: "删除角色",
  add_location: "新增地点",
  update_location: "修改地点",
  delete_location: "删除地点",
  add_location_link: "新增通路",
  delete_location_link: "删除通路",
  add_chapter: "新增章节",
  delete_chapter: "删除章节",
  rename_chapter: "重命名章节",
  append_script: "追加剧本",
  replace_script: "替换剧本",
  update_bible: "更新设定",
  update_meta: "更新元信息",
  propose_character_link: "提议关系",
  propose_timeline_event: "提议时间线",
  add_character_link: "写入关系",
  update_character_link: "更新关系",
  delete_character_link: "删除关系",
  add_timeline_event: "写入时间线",
  update_timeline_event: "更新时间线",
  delete_timeline_event: "删除时间线",
  scan_facts: "扫描事实",
};

const WELCOME_MARKER = "轻小说 / 视觉小说的写法底盘会自动带上";

export function describeActions(actions: AgentAction[]): string {
  if (actions.length === 0) return "";
  const names = actions.map((a) => ACTION_LABEL[a.op] ?? a.op);
  return names.length <= 2 ? names.join("；") : `${names[0]} 等 ${names.length} 项`;
}

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

export function defaultWelcome(): AgentChatMessage[] {
  return [
    {
      role: "assistant",
      content:
        "我是这部作品的驻场责编（通用文学编辑）。轻小说 / 视觉小说的写法底盘会自动带上——你只要用平常话说想续写、改哪段、卡在哪就行。\n\n若想换一位作家的眼光来参谋，点顶部 **⇄** 打开作家卡；需要多视角时可打开「多选」。右上角 **!** 有说明。卡壳或要整场戏时，再说「跑流水线」也不迟。",
    },
  ];
}

function isStaleWelcome(content: string): boolean {
  const t = (content || "").trim();
  if (!t.includes("驻场责编")) return false;
  return !t.includes(WELCOME_MARKER);
}

/** Refresh baked-in welcome from older sessions; keep real chat history. */
export function normalizeMessages(msgs: AgentChatMessage[]): AgentChatMessage[] {
  const welcome = defaultWelcome();
  if (!Array.isArray(msgs) || msgs.length === 0) return welcome;
  const onlyAssistant = msgs.every((m) => m.role === "assistant");
  if (onlyAssistant) return welcome;
  const first = msgs[0];
  if (first?.role === "assistant" && isStaleWelcome(first.content)) {
    return [{ role: "assistant", content: welcome[0].content }, ...msgs.slice(1)];
  }
  return msgs;
}

export function formatLintBlock(data: HarnessLintResult): string {
  const head = `${data.pass ? "无硬错误" : "存在硬错误"} · error ${data.errorCount} / warn ${data.warnCount} / info ${data.infoCount}`;
  if (!data.issues?.length) return `${head}\n未发现明显 AI 腔 / 社交问题。`;
  const lines = data.issues
    .slice(0, 24)
    .map((iss) => `- [${iss.severity}] ${iss.code}：${iss.message}`);
  return [head, ...lines].join("\n");
}

export function formatPipelineResult(data: PipelineRunResult): string {
  const parts: string[] = ["### 写作流水线结果"];
  parts.push(`阶段：${(data.stages || []).join(" → ") || "—"}`);
  if (typeof data.reviseRounds === "number" && data.reviseRounds > 0) {
    parts.push(`修正轮次：${data.reviseRounds}`);
  }
  if (data.runId) {
    parts.push(`运行记录：\`${data.runId}\``);
  }
  if (data.plan?.beatSheet) {
    parts.push(
      "#### 1. 规划（节拍表）\n```json\n" +
        JSON.stringify(data.plan.beatSheet, null, 2) +
        "\n```"
    );
  } else if (data.plan?.content) {
    parts.push(`#### 1. 规划\n\n${data.plan.content}`);
  }
  const draftText = data.finalDraft || data.draft || "";
  if (draftText) {
    parts.push(`#### 生成 / 修正稿\n\n${draftText}`);
  }
  if (data.check) {
    parts.push(
      `#### 检查\n\n${
        data.check.pass ? "无硬错误" : "存在硬错误"
      } · error ${data.check.errorCount ?? 0} / warn ${data.check.warnCount ?? 0}`
    );
    const issues = data.check.issues || [];
    if (issues.length) {
      parts.push(
        issues
          .slice(0, 16)
          .map((i) => `- [${i.severity}] ${i.code}：${i.message}`)
          .join("\n")
      );
    }
  }
  if (data.gate) {
    parts.push(
      `#### 质量门禁\n\n${data.gate.pass ? "✅ 通过" : "❌ 未通过"} — ${
        data.gate.message || ""
      }`
    );
  }
  if (data.applied) {
    parts.push("\n_已将通过门禁的终稿写入当前章节。_");
  } else if (data.applyError) {
    parts.push(`\n_未能写入章节：${data.applyError}_`);
  } else if (!data.gate?.pass) {
    parts.push(
      "\n_门禁未过，稿件未写入工程。可先改后再说「跑流水线」或「定稿」。_"
    );
  } else {
    parts.push("\n_门禁已过但未写入章节（未指定章节或未开启入库）。_");
  }
  const trace = data.trace;
  if (trace?.length) {
    parts.push(
      "#### 阶段耗时\n\n" +
        trace
          .map(
            (t) =>
              `- ${t.stage || "?"} · ${t.ms ?? "?"}ms · ${t.ok === false ? "失败" : "ok"}`
          )
          .join("\n")
    );
  }
  return parts.join("\n\n");
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
  scrollerRef: RefObject<HTMLDivElement | null>;
  onOpenReviseReview: (chapterId: string) => void;
  onToggleDossier: () => void;
  onTogglePersona: () => void;
  onToggleHelp: () => void;
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
  scrollerRef,
  onOpenReviseReview,
  onToggleDossier,
  onTogglePersona,
  onToggleHelp,
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
            <p className={styles.emptyHint}>点 ⇄ 选参谋，或直接开写</p>
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
        {busy && <p className={styles.thinking}>{thinking}</p>}
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
      {error && <p className={styles.error}>{error}</p>}
    </>
  );
}
