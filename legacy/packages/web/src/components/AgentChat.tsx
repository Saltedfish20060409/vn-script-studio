"use client";

import { useEffect, useRef, useState } from "react";
import {
  applyAgentActions,
  normalizeProject,
  type AgentChatMessage,
  type AgentTaskKind,
  type VnProject,
} from "@vnss/core";
import {
  prepareAgentChatPayload,
  clearAgentChat,
  defaultAgentWelcome,
  loadAgentChat,
  loadAgentUndo,
  popAgentUndo,
  pushAgentUndo,
  saveAgentChat,
} from "../lib/agentSession";
import styles from "./AgentChat.module.css";

type ApiConfig = {
  apiKey?: string;
  apiBaseUrl?: string;
  apiModel?: string;
  craftMode?: "auto" | "off" | "lite" | "full";
  selfReview?: "auto" | "on" | "off";
  criticApiKey?: string;
  criticApiBaseUrl?: string;
  criticApiModel?: string;
};

type Props = {
  project: VnProject;
  chapterId: string;
  selection: string;
  prepareProject?: () => VnProject;
  onProjectChange: (project: VnProject) => void;
  onChapterFocus?: (chapterId: string) => void;
  compact?: boolean;
  apiConfig?: ApiConfig;
  /** Hidden when float is minimized — keep mounted so state survives */
  hidden?: boolean;
};

type QuickAction = {
  label: string;
  task: AgentTaskKind;
  build: (selection: string) => string;
};

const QUICK_ACTIONS: QuickAction[] = [
  {
    label: "续写",
    task: "continue",
    build: () =>
      "【任务：续写】请只续写一小段可上演节拍，紧接当前章末尾的情绪与未完成的事。\n硬性要求：\n1) 人物设定/bio 是内部参考，禁止写进对白当说明书；\n2) 不要开场介绍人物是谁；\n3) 用行动、态度、潜台词推进——禁止同一角色连问盘人（陌生人尤其惜话）；\n4) 信息残缺优于一问一答把路线问清楚；\n5) 段末留钩子，不要作者总结。\n写完用 append_script 写入当前章。",
  },
  {
    label: "写一场戏",
    task: "scene",
    build: () =>
      "【任务：写一场戏】写完整一小场：进场氛围→冲突推进→对白交锋→收束钩子。设定溶于表演，禁止人物/世界观说明书开场。用 append_script 写入当前章。",
  },
  {
    label: "改写选区",
    task: "rewrite",
    build: (sel) =>
      sel
        ? "【任务：改写】请改写我提供的选区：保持剧情意图与人物语气，提升画面感与张力，输出 Ren'Py 片段；用 append_script 追加（在 message 说明改了什么）。"
        : "我想改写选区，但当前没有选中文字。请提醒我先在剧本页拖选一段，然后再改写。",
  },
  {
    label: "润色",
    task: "polish",
    build: (sel) =>
      sel
        ? "【任务：润色】请润色选区对白/旁白：更自然、更有画面感，情节与人设不变。用 append_script 把润色稿写入当前章节。"
        : "【任务：润色】请润色当前章节末尾最近几段对白与旁白，使其更自然有画面感，并用 append_script 写入。",
  },
  {
    label: "生成分支",
    task: "branch",
    build: () =>
      "【任务：分支】请为当前情节设计 2～4 个有意义的 Ren'Py menu 分支（每项后果不同：信息/关系/路线），避免假选择，并用 append_script 写入当前章节。",
  },
  {
    label: "大纲",
    task: "outline",
    build: () =>
      "【任务：大纲】请根据已有设定与章节目录，给出接下来 3～5 个场景大纲（场景标题 + 冲突 + 出场人物 + 可选分支）。先写在 message 里讨论；若我同意再写入设定 outline。",
  },
  {
    label: "统一语气",
    task: "voice",
    build: (sel) =>
      sel
        ? "【任务：语气】请检查选区对白是否符合角色 voice/bio，指出破功处并给出改写；需要落地时用 append_script。"
        : "【任务：语气】请抽查当前章节对白的人设一致性，指出破功处并给出改写；需要落地时用 append_script。",
  },
  {
    label: "查矛盾",
    task: "consistency",
    build: () =>
      "【任务：查矛盾】请对照 Variables、角色关系、地点氛围与各章摘要，列出矛盾 / 伏笔未回收 / 状态冲突，并给出最小改法（可建议 actions，勿擅自大删剧情）。",
  },
];

const TASK_LABEL: Record<AgentTaskKind, string> = {
  chat: "讨论",
  continue: "续写",
  rewrite: "改写",
  polish: "润色",
  branch: "分支",
  outline: "大纲",
  voice: "语气",
  consistency: "查矛盾",
  scene: "写一场戏",
};

export function AgentChat({
  project,
  chapterId,
  selection,
  prepareProject,
  onProjectChange,
  onChapterFocus,
  compact,
  apiConfig,
  hidden,
}: Props) {
  const projectId = project.id;
  const [messages, setMessages] = useState<AgentChatMessage[]>(() =>
    loadAgentChat(projectId)
  );
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastContext, setLastContext] = useState<string>("");
  const [undoCount, setUndoCount] = useState(() => loadAgentUndo(projectId).length);
  const scroller = useRef<HTMLDivElement>(null);
  const loadedFor = useRef(projectId);

  useEffect(() => {
    if (loadedFor.current === projectId) return;
    loadedFor.current = projectId;
    setMessages(loadAgentChat(projectId));
    setUndoCount(loadAgentUndo(projectId).length);
    setInput("");
    setError("");
    setLastContext("");
  }, [projectId]);

  useEffect(() => {
    if (loadedFor.current !== projectId) return;
    saveAgentChat(projectId, messages);
  }, [projectId, messages]);

  useEffect(() => {
    if (hidden) return;
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages, busy, lastContext, hidden]);

  function undoAgentEdit() {
    const popped = popAgentUndo(projectId);
    if (!popped) return;
    try {
      const restored = normalizeProject(
        JSON.parse(popped.entry.payload) as VnProject
      );
      onProjectChange({
        ...restored,
        id: projectId,
        snapshots: project.snapshots,
        shareId: project.shareId,
      });
      setUndoCount(popped.rest.length);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `已撤回「${popped.entry.label}」，工程回到该次 Agent 写入之前。`,
        },
      ]);
    } catch {
      setError("撤回失败：存档损坏");
      setUndoCount(loadAgentUndo(projectId).length);
    }
  }

  function clearChat() {
    if (
      !window.confirm(
        "清空本项目的 Agent 对话记录？不会改动剧本内容（撤回栈保留）。"
      )
    ) {
      return;
    }
    clearAgentChat(projectId);
    setMessages(defaultAgentWelcome());
  }

  async function sendText(text: string, task?: AgentTaskKind) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setError("");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: trimmed },
    ];
    setMessages(nextMessages);
    setBusy(true);
    try {
      const snapshot = prepareProject ? prepareProject() : project;
      const { chatMemory, apiMessages } = prepareAgentChatPayload(
        projectId,
        nextMessages.filter((m) => m.role === "user" || m.role === "assistant")
      );
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project: snapshot,
          messages: apiMessages.slice(-20),
          chatMemory: chatMemory || undefined,
          chapterId,
          selection: selection || undefined,
          task,
          craftMode: apiConfig?.craftMode || "auto",
          selfReview: apiConfig?.selfReview || "auto",
          criticApiKey: apiConfig?.criticApiKey || undefined,
          criticApiBaseUrl: apiConfig?.criticApiBaseUrl || undefined,
          criticApiModel: apiConfig?.criticApiModel || undefined,
          apiKey: apiConfig?.apiKey || undefined,
          apiBaseUrl: apiConfig?.apiBaseUrl || undefined,
          apiModel: apiConfig?.apiModel || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Agent 请求失败");

      const actions = data.actions ?? [];
      let updated = snapshot;
      let applied: string[] = [];
      let skipped: string[] = [];

      if (actions.length > 0) {
        const result = applyAgentActions(snapshot, actions, {
          defaultChapterId: chapterId,
        });
        updated = result.project;
        applied = result.applied;
        skipped = result.skipped;
        if (applied.length > 0) {
          const label =
            applied.length <= 2
              ? applied.join("；")
              : `${applied[0]} 等 ${applied.length} 项`;
          const stack = pushAgentUndo(projectId, snapshot, label);
          setUndoCount(stack.length);
          onProjectChange(updated);
        }
      }

      const meta = data.contextMeta as
        | {
            task?: AgentTaskKind;
            craftMode?: string;
            selfReview?: string;
          }
        | undefined;
      const taskName = meta?.task ? TASK_LABEL[meta.task] ?? meta.task : "";
      const resultBit =
        applied.length > 0
          ? "已写入工程"
          : actions.length > 0
            ? "未写入（动作失败或跳过）"
            : "仅讨论未改工程";
      const craftShort =
        meta?.craftMode === "full"
          ? "工艺全"
          : meta?.craftMode === "lite"
            ? "工艺轻"
            : meta?.craftMode === "off"
              ? "工艺关"
              : "";
      const reviewShort = meta?.selfReview
        ? meta.selfReview.includes("未通过") || meta.selfReview.includes("改写")
          ? "自检已改"
          : meta.selfReview.includes("通过")
            ? "自检过"
            : "自检"
        : "";
      setLastContext(
        [taskName, resultBit, craftShort, reviewShort].filter(Boolean).join(" · ")
      );

      const noteUndo =
        applied.length > 0
          ? `可用「撤回编辑」回滚（栈内 ${loadAgentUndo(projectId).length} 步）`
          : "";
      const foot = [
        applied.length ? `已落地：${applied.join("；")}` : "",
        skipped.length ? `未执行：${skipped.join("；")}` : "",
        noteUndo,
      ]
        .filter(Boolean)
        .join("\n");

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: foot ? `${data.message}\n\n${foot}` : data.message,
        },
      ]);

      if (actions.some((a: { op: string }) => a.op === "add_chapter")) {
        const last = updated.chapters[updated.chapters.length - 1];
        if (last) onChapterFocus?.(last.id);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "请求失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${msg}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    await sendText(text);
  }

  return (
    <div
      className={compact ? styles.shellCompact : styles.shell}
      style={hidden ? { display: "none" } : undefined}
      aria-hidden={hidden || undefined}
    >
      <div className={styles.quickRow}>
        {QUICK_ACTIONS.map((a) => (
          <button
            key={a.label}
            type="button"
            className={styles.quickBtn}
            disabled={busy}
            onClick={() => void sendText(a.build(selection), a.task)}
            title={a.label}
          >
            {a.label}
          </button>
        ))}
        <button
          type="button"
          className={styles.quickBtnMuted}
          disabled={busy || undoCount === 0}
          onClick={undoAgentEdit}
          title="撤回最近一次 Agent 对工程的写入"
        >
          撤回编辑{undoCount > 0 ? ` (${undoCount})` : ""}
        </button>
        <button
          type="button"
          className={styles.quickBtnMuted}
          disabled={busy}
          onClick={clearChat}
          title="清空对话记录（不改剧本）"
        >
          清空对话
        </button>
      </div>
      {lastContext ? (
        <p className={styles.ctxMeta} title="只显示是否写入工程；详细工艺在设置里可调">
          {lastContext}
        </p>
      ) : null}
      {selection ? (
        <p className={styles.selHint}>已带入选区 {selection.length} 字</p>
      ) : (
        <p className={styles.selHint}>
          长篇：本地章摘要 + 大纲节拍检索 + 对话记忆压缩（无需服务器）
        </p>
      )}
      <div
        className={styles.messages}
        ref={scroller}
        onWheel={(e) => e.stopPropagation()}
      >
        {messages.map((m, i) => (
          <div
            key={`${i}-${m.role}`}
            className={m.role === "user" ? styles.user : styles.bot}
          >
            <span className={styles.role}>
              {m.role === "user" ? "你" : "编辑"}
            </span>
            <p>{m.content}</p>
          </div>
        ))}
        {busy && (
          <p className={styles.thinking}>编辑正在检索设定 / 读当前章…</p>
        )}
      </div>
      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.composer}>
        <textarea
          rows={compact ? 2 : 3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="谈剧情、要改稿、要下一场戏…或点上方专业化任务"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button
          type="button"
          disabled={busy || !input.trim()}
          onClick={() => void send()}
        >
          {busy ? "…" : "发送"}
        </button>
      </div>
    </div>
  );
}
