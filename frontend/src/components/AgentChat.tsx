import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import {
  createAgentConversation,
  deleteAgentConversation,
  getAgentConversation,
  getProjectLenses,
  getProjectMentors,
  harnessLint,
  listLenses,
  pipelineGate,
  pipelineLedgerDigest,
  pipelineRun,
  pipelineRunStream,
  waitProjectJob,
  putProjectLenses,
  runBrainstorm,
  listAgentConversations,
  putAgentConversation,
  renameAgentConversation,
  runAgentStream,
  uploadAgentAttachment,
  ingestAttachmentSettings,
  chapterRevise,
  chapterReviseApply,
  factsScan,
  type AgentAttachment,
  type AgentConversationOut,
  type AgentConversationSummary,
  type LensPackMeta,
  type PipelineRunResult,
} from "../api/client";
import { inferAgentIntent } from "../lib/agentIntent";
import {
  getChapterRevisePrefs,
  prefsToNoteSuffix,
  setChapterRevisePrefs,
  type ReviseMode,
} from "../lib/chapterRevisePrefs";
import {
  getHarnessPrefs,
  setHarnessPrefs,
  type HarnessPrefs,
} from "../lib/harnessPrefs";
import {
  clearChapterReviseDraft,
  getChapterReviseDraft,
  OPEN_REVISE_REVIEW_EVENT,
  REVISE_DRAFT_EVENT,
  saveChapterReviseDraft,
  type ChapterReviseDraft,
} from "../lib/chapterReviseDraft";
import { blocksToEditable } from "../lib/scriptCodec";
import { buildWriterCards, DEFAULT_WRITER } from "../lib/agentWriterCards";
import type {
  AgentChatMessage,
  AgentTaskKind,
  AgentTraceEvent,
  VnProject,
} from "../types/vn";
import { AgentAttachList } from "./AgentAttachList";
import { AgentComposerBox } from "./AgentComposerBox";
import { AgentConversationRail } from "./AgentConversationRail";
import { AgentHelpOverlay } from "./AgentHelpOverlay";
import {
  describeActions,
  defaultWelcome,
  formatLintBlock,
  formatPipelineResult,
  normalizeMessages,
} from "../lib/agentFormat";
import { AgentMessagesList } from "./AgentMessagesList";
import { AgentPersonaOverlay } from "./AgentPersonaOverlay";
import { ChapterReviseModePicker } from "./ChapterReviseModePicker";
import { ChapterReviseReview } from "./ChapterReviseReview";
import { useConfirm } from "../lib/confirmDialog";
import { WriterPortrait } from "./WriterPortrait";
import styles from "./AgentChat.module.css";

type Props = {
  project: VnProject;
  chapterId: string;
  selection: string;
  /** Current chapter script text (editor buffer) for lint / pipeline / gate */
  draft?: string;
  prepareProject?: () => VnProject;
  onProjectChange: (project: VnProject) => void;
  onChapterFocus?: (chapterId: string) => void;
  compact?: boolean;
  /** Hidden when float is minimized — keep mounted so state survives */
  hidden?: boolean;
};

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

function convStorageKey(projectId: string) {
  return `vnss-agent-conv:${projectId}`;
}

type UndoEntry = { label: string; project: VnProject };

function parseUndoStack(raw: unknown[]): UndoEntry[] {
  const out: UndoEntry[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const obj = item as Record<string, unknown>;
    if (obj.project && typeof obj.project === "object") {
      out.push({
        label: typeof obj.label === "string" ? obj.label : "编辑",
        project: obj.project as VnProject,
      });
    } else if (obj.id && obj.chapters) {
      out.push({ label: "编辑", project: item as VnProject });
    }
  }
  return out.slice(-20);
}

export function AgentChat({
  project,
  chapterId,
  selection,
  draft = "",
  prepareProject,
  onProjectChange,
  onChapterFocus,
  compact,
  hidden,
}: Props) {
  const projectId = project.id;
  const [conversations, setConversations] = useState<AgentConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // 上次运行检查点摘要（run_state）：status=interrupted/error 时显示"继续上次"
  const [runState, setRunState] = useState<NonNullable<
    AgentConversationOut["run_state"]
  > | null>(null);
  const resumeMode = useRef(false);
  const [titleDrafts, setTitleDrafts] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<AgentChatMessage[]>(defaultWelcome);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<AgentAttachment[]>([]);
  const [attachBusy, setAttachBusy] = useState(false);
  const [pendingRevise, setPendingReviseState] = useState<ChapterReviseDraft | null>(
    () => getChapterReviseDraft(project.id, chapterId)
  );
  const [reviseReviewOpen, setReviseReviewOpen] = useState(false);
  const [reviseModeOpen, setReviseModeOpen] = useState(false);
  /** Aborts the in-flight streaming agent/pipeline request on unmount or when
   * a new request supersedes the current one (prevents leaked streams that
   * keep consuming LLM quota after the user navigates away). */
  const streamAbortRef = useRef<AbortController | null>(null);
  const pendingReviseRef = useRef<ChapterReviseDraft | null>(pendingRevise);
  pendingReviseRef.current = pendingRevise;

  function setPendingRevise(
    next: ChapterReviseDraft | null,
    opts?: { persist?: boolean; clearChapterId?: string }
  ) {
    setPendingReviseState(next);
    if (opts?.persist === false) return;
    if (next) {
      saveChapterReviseDraft(projectId, next);
    } else {
      const cid =
        opts?.clearChapterId || pendingReviseRef.current?.chapterId || chapterId;
      if (cid) clearChapterReviseDraft(projectId, cid);
    }
  }
  const revisePendingArgs = useRef<{
    note?: string;
    mode?: ReviseMode;
    skipModePicker?: boolean;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [loadingConv, setLoadingConv] = useState(true);
  const [error, setError] = useState("");
  const [lastContext, setLastContext] = useState<string>("");
  const [undoCount, setUndoCount] = useState(0);
  const [thinking, setThinking] = useState("编辑正在检索设定 / 读当前章…");
  const [liveStream, setLiveStream] = useState<{
    events: AgentTraceEvent[];
    text: string;
  } | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [personaOpen, setPersonaOpen] = useState(false);
  const [harnessPrefs, setHarnessPrefsState] = useState<HarnessPrefs>(() =>
    getHarnessPrefs()
  );
  const [multiSelect, setMultiSelect] = useState(false);
  const [brainstormTopic, setBrainstormTopic] = useState("");
  const [detailKey, setDetailKey] = useState<string | null>(null);
  const [dossierOpen, setDossierOpen] = useState(false);
  const [lensCatalog, setLensCatalog] = useState<LensPackMeta[]>([]);
  const confirm = useConfirm();
  const [activeLensIds, setActiveLensIds] = useState<string[]>([]);
  const [lensBusy, setLensBusy] = useState(false);
  const [sidebarW, setSidebarW] = useState(() => {
    try {
      const n = Number(localStorage.getItem("vnss-agent-sidebar-w"));
      if (Number.isFinite(n) && n >= 140 && n <= 420) return n;
    } catch {
      /* ignore */
    }
    return 200;
  });
  const undoStack = useRef<UndoEntry[]>([]);
  const scroller = useRef<HTMLDivElement>(null);
  const sessionReady = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const messagesRef = useRef(messages);
  const renameTimer = useRef<Record<string, number>>({});
  const focusTitleId = useRef<string | null>(null);
  const titleInputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const splitRef = useRef<HTMLDivElement>(null);
  const resizing = useRef(false);

  conversationIdRef.current = conversationId;
  messagesRef.current = messages;

  // Restore / switch chapter draft without wiping other chapters' storage
  useEffect(() => {
    setPendingReviseState(getChapterReviseDraft(projectId, chapterId));
  }, [projectId, chapterId]);

  // Cancel any in-flight stream when the panel unmounts.
  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
    };
  }, []);

  // Writing toolbar / short command: reopen对照 for a saved draft
  useEffect(() => {
    function onOpen(e: Event) {
      const detail =
        (e as CustomEvent<{ projectId?: string; chapterId?: string }>).detail || {};
      if (detail.projectId && detail.projectId !== projectId) return;
      const cid = detail.chapterId || chapterId;
      const draft = getChapterReviseDraft(projectId, cid);
      if (!draft) {
        setError("本章没有保存的改稿预览。先说「帮我改这一章」。");
        return;
      }
      setPendingReviseState(draft);
      setReviseReviewOpen(true);
      setError("");
    }
    function onDraftChanged() {
      // Refresh action-chip enabled state when draft saved/cleared
      setPendingReviseState((prev) => {
        const cid = prev?.chapterId || chapterId;
        return getChapterReviseDraft(projectId, cid);
      });
    }
    window.addEventListener(OPEN_REVISE_REVIEW_EVENT, onOpen);
    window.addEventListener(REVISE_DRAFT_EVENT, onDraftChanged);
    return () => {
      window.removeEventListener(OPEN_REVISE_REVIEW_EVENT, onOpen);
      window.removeEventListener(REVISE_DRAFT_EVENT, onDraftChanged);
    };
  }, [projectId, chapterId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [catalog, cur] = await Promise.all([
          listLenses(),
          getProjectLenses(projectId),
        ]);
        if (cancelled) return;
        setLensCatalog(catalog.packs || []);
        setActiveLensIds(cur.activeIds || []);
      } catch {
        /* optional UI */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Sync from project prop if parent updated authorLenses
  useEffect(() => {
    const ids = project.authorLenses?.activeIds;
    if (Array.isArray(ids)) setActiveLensIds(ids);
  }, [project.authorLenses]);

  const persistActiveId = useCallback((projectKey: string, id: string) => {
    try {
      localStorage.setItem(convStorageKey(projectKey), id);
    } catch {
      /* ignore */
    }
  }, []);

  const flushSave = useCallback(async () => {
    const cid = conversationIdRef.current;
    if (!cid || !sessionReady.current) return;
    try {
      await putAgentConversation(projectId, cid, {
        messages: messagesRef.current.slice(-120),
        chat_memory: "",
        undo_stack: undoStack.current.slice(-20),
      });
    } catch {
      /* best-effort */
    }
  }, [projectId]);

  const applyConversation = useCallback(
    (conv: {
      id: string;
      title: string;
      messages: AgentChatMessage[];
      undo_stack: unknown[];
      run_state?: AgentConversationOut["run_state"];
    }) => {
      setConversationId(conv.id);
      persistActiveId(projectId, conv.id);
      setRunState(conv.run_state ?? null);
      const raw = Array.isArray(conv.messages) ? conv.messages : [];
      const next = normalizeMessages(raw);
      setMessages(next);
      undoStack.current = parseUndoStack(
        Array.isArray(conv.undo_stack) ? conv.undo_stack : []
      );
      setUndoCount(undoStack.current.length);
      setLastContext("");
      setError("");
      setInput("");
      sessionReady.current = true;
      // Persist refreshed welcome so old text doesn't keep coming back
      const changed =
        next.length !== raw.length ||
        next.some((m, i) => m.content !== raw[i]?.content || m.role !== raw[i]?.role);
      if (changed) {
        void putAgentConversation(projectId, conv.id, {
          messages: next.slice(-120),
          chat_memory: "",
          undo_stack: undoStack.current.slice(-20),
        }).catch(() => undefined);
      }
    },
    [persistActiveId, projectId]
  );

  const refreshList = useCallback(async () => {
    const list = await listAgentConversations(projectId);
    setConversations((prev) => {
      const prevById = Object.fromEntries(prev.map((c) => [c.id, c.title || "新对话"]));
      setTitleDrafts((drafts) => {
        const next = { ...drafts };
        for (const c of list) {
          const server = c.title || "新对话";
          const d = next[c.id];
          if (d === undefined || d === prevById[c.id] || d === server) {
            next[c.id] = server;
          }
        }
        for (const id of Object.keys(next)) {
          if (!list.some((c) => c.id === id)) delete next[id];
        }
        return next;
      });
      return list;
    });
    return list;
  }, [projectId]);

  useEffect(() => {
    if (!focusTitleId.current) return;
    const id = focusTitleId.current;
    focusTitleId.current = null;
    requestAnimationFrame(() => {
      const el = titleInputRefs.current[id];
      if (!el) return;
      el.focus();
      el.select();
    });
  }, [conversations]);

  useEffect(() => {
    try {
      localStorage.setItem("vnss-agent-sidebar-w", String(sidebarW));
    } catch {
      /* ignore */
    }
  }, [sidebarW]);

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (!resizing.current || !splitRef.current) return;
      const rect = splitRef.current.getBoundingClientRect();
      const next = Math.round(e.clientX - rect.left);
      setSidebarW(Math.min(420, Math.max(140, next)));
    }
    function onUp() {
      if (!resizing.current) return;
      resizing.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    sessionReady.current = false;
    setLoadingConv(true);
    setMessages(defaultWelcome());
    undoStack.current = [];
    setUndoCount(0);
    setConversationId(null);
    setInput("");
    setError("");
    setLastContext("");

    (async () => {
      try {
        let list = await listAgentConversations(projectId);
        if (cancelled) return;
        if (list.length === 0) {
          const created = await createAgentConversation(projectId);
          if (cancelled) return;
          list = [
            {
              id: created.id,
              title: created.title,
              message_count: created.messages?.length ?? 0,
              created_at: created.created_at,
              updated_at: created.updated_at,
            },
          ];
          setConversations(list);
          applyConversation(created);
          return;
        }
        setConversations(list);
        let preferred: string | null = null;
        try {
          preferred = localStorage.getItem(convStorageKey(projectId));
        } catch {
          preferred = null;
        }
        const targetId =
          (preferred && list.some((c) => c.id === preferred) && preferred) ||
          list[0].id;
        const detail = await getAgentConversation(projectId, targetId);
        if (cancelled) return;
        applyConversation(detail);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "加载对话失败");
        sessionReady.current = true;
      } finally {
        if (!cancelled) setLoadingConv(false);
      }
    })();

    return () => {
      cancelled = true;
      void flushSave();
    };
  }, [projectId, applyConversation, flushSave]);

  useEffect(() => {
    if (!sessionReady.current || !conversationId) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void flushSave().then(() => {
        void refreshList().catch(() => undefined);
      });
    }, 800);
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, [projectId, conversationId, messages, flushSave, refreshList]);

  useEffect(() => {
    if (hidden) return;
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages, busy, lastContext, hidden]);

  async function switchConversation(nextId: string) {
    if (!nextId || nextId === conversationId || busy) return;
    setBusy(true);
    setError("");
    try {
      await flushSave();
      sessionReady.current = false;
      const detail = await getAgentConversation(projectId, nextId);
      applyConversation(detail);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "切换对话失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleNewConversation() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await flushSave();
      sessionReady.current = false;
      const created = await createAgentConversation(projectId, "新对话");
      focusTitleId.current = created.id;
      setTitleDrafts((prev) => ({
        ...prev,
        [created.id]: created.title || "新对话",
      }));
      applyConversation(created);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "新建对话失败");
      sessionReady.current = true;
    } finally {
      setBusy(false);
    }
  }

  function scheduleRename(id: string, title: string) {
    const prev = renameTimer.current[id];
    if (prev) window.clearTimeout(prev);
    renameTimer.current[id] = window.setTimeout(() => {
      void commitRename(id, title);
    }, 450);
  }

  async function commitRename(id: string, raw: string) {
    const title = raw.trim() || "新对话";
    setTitleDrafts((prev) => ({ ...prev, [id]: title }));
    const current = conversations.find((c) => c.id === id)?.title;
    if (current === title) return;
    try {
      await renameAgentConversation(projectId, id, title);
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
      await refreshList().catch(() => undefined);
    }
  }

  function handleRenameChange(id: string, value: string) {
    setTitleDrafts((prev) => ({ ...prev, [id]: value }));
    scheduleRename(id, value);
  }

  function handleRenameCommit(id: string, raw: string) {
    const t = renameTimer.current[id];
    if (t) window.clearTimeout(t);
    void commitRename(id, raw);
  }

  function handleOpenReviseReview(chapterId: string) {
    const draft = getChapterReviseDraft(projectId, chapterId);
    if (!draft) {
      setError("改稿预览已写入或已丢弃，可再说「帮我改这一章」。");
      return;
    }
    setPendingReviseState(draft);
    setReviseReviewOpen(true);
    setError("");
  }

  function handleResizeStart(e: ReactPointerEvent<HTMLDivElement>) {
    e.preventDefault();
    resizing.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  }

  function handleToggleDossier() {
    setPersonaOpen(false);
    setHelpOpen(false);
    setDossierOpen((v) => !v);
  }

  function handleTogglePersona() {
    setDossierOpen(false);
    setHelpOpen(false);
    setPersonaOpen((v) => !v);
  }

  function handleToggleHelp() {
    setDossierOpen(false);
    setPersonaOpen(false);
    setHelpOpen((v) => !v);
  }

  async function handleDeleteConversation(targetId?: string) {
    const id = targetId ?? conversationId;
    if (!id || busy) return;
    const ok = await confirm({
      title: "删除当前对话？",
      body: "消息记录将从服务器移除，不会改动剧本内容。",
      danger: true,
      confirmLabel: "确认删除",
    });
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      if (id === conversationId) sessionReady.current = false;
      await deleteAgentConversation(projectId, id);
      setTitleDrafts((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      const list = await refreshList();
      if (id !== conversationId && conversationId) {
        return;
      }
      const next = list[0];
      if (next) {
        const detail = await getAgentConversation(projectId, next.id);
        applyConversation(detail);
      } else {
        const created = await createAgentConversation(projectId);
        focusTitleId.current = created.id;
        applyConversation(created);
        await refreshList();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除对话失败");
      sessionReady.current = true;
    } finally {
      setBusy(false);
    }
  }

  function undoAgentEdit() {
    const popped = undoStack.current[undoStack.current.length - 1];
    if (!popped) return;
    undoStack.current = undoStack.current.slice(0, -1);
    setUndoCount(undoStack.current.length);
    onProjectChange({ ...popped.project, id: projectId });
    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        content: `已撤回「${popped.label}」，工程回到该次 Agent 写入之前。`,
      },
    ]);
  }

  /** Agent 流式运行主体：普通消息与断点续跑共用（resume=true 时从 run_state 续跑）。 */
  async function streamAgentRun(opts: {
    resume: boolean;
    apiMessages: AgentChatMessage[];
    nextMessages: AgentChatMessage[];
    task?: AgentTaskKind;
    attachments?: AgentAttachment[];
  }) {
    const convId = conversationId;
    if (!convId) return;
    const pendingAttach = opts.attachments ?? [];
    setError("");
    setThinking(
      opts.resume
        ? "正在从断点继续上次运行…"
        : pendingAttach.length
          ? "编辑正在阅读附件 / 检索设定…"
          : "编辑正在检索设定 / 读当前章…"
    );
    setBusy(true);
    // 防御：90s 内一个事件都没收到（模型连接黑洞/后端异常未上报）就中止，
    // 否则 busy 永远为 true，界面卡死在"正在检索设定"。（声明在 try 外，
    // 供 finally 清理）
    let noEventTimer: number | undefined;
    try {
      const snapshot = prepareProject ? prepareProject() : project;
      const streamEvents: AgentTraceEvent[] = [];
      setLiveStream({ events: [], text: "" });
      streamAbortRef.current?.abort();
      const controller = new AbortController();
      streamAbortRef.current = controller;
      let gotEvent = false;
      noEventTimer = window.setTimeout(() => {
        if (gotEvent || controller.signal.aborted) return;
        controller.abort();
        setBusy(false);
        setThinking("");
        setError("Agent 长时间无响应：请检查模型配置（Base URL / API Key / 模型名）后重试");
      }, 90_000);
      const res = await runAgentStream(
        projectId,
        {
          messages: opts.apiMessages,
          chapter_id: chapterId,
          selection: selection || undefined,
          task: opts.task,
          conversation_id: convId,
          apply_actions: true,
          resume: opts.resume || undefined,
          // 与 UI 选中同步；勿仅依赖 DB（避免 PUT 未完成时本轮漏注入）
          lens_ids: activeLensIds,
          attachments: opts.resume
            ? undefined
            : pendingAttach.map((a) => ({
                filename: a.filename,
                text: a.text,
                id: a.id,
              })),
        },
        (evt) => {
          gotEvent = true;
          if (evt.type === "thought") {
            setLiveStream((p) => ({ events: p?.events ?? [], text: evt.text ?? "" }));
            return;
          }
          if (evt.type === "memory") {
            // 对话记忆归档提示：以工具结果样式进 trace 面板
            streamEvents.push({
              type: "tool_result",
              name: "memory",
              ok: true,
              preview: evt.note ?? "已归档早期对话记忆",
            } as AgentTraceEvent);
            setLiveStream((p) => ({ events: [...streamEvents], text: p?.text ?? "" }));
            return;
          }
          if (
            evt.type === "task" ||
            evt.type === "tool_call" ||
            evt.type === "tool_result" ||
            evt.type === "actions"
          ) {
            streamEvents.push(evt as unknown as AgentTraceEvent);
            setLiveStream((p) => ({ events: [...streamEvents], text: p?.text ?? "" }));
          }
        },
        controller.signal
      );

      const actions = res.actions ?? [];
      const applied = res.applied && !!res.project;

      if (applied && res.project) {
        undoStack.current = [
          ...undoStack.current,
          { label: describeActions(actions), project: snapshot },
        ].slice(-20);
        setUndoCount(undoStack.current.length);
        onProjectChange(res.project);
      }

      const meta = res.context_meta;
      const taskName = meta?.task ? (TASK_LABEL[meta.task] ?? meta.task) : "";
      const resultBit = applied
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
      const lensShort =
        Array.isArray(meta?.lensIds) && meta.lensIds.length
          ? `视角×${meta.lensIds.length}`
          : "";
      // 透明性：本次注入了哪些上下文（设定卡/设定bible/角色等）
      const refs = Array.isArray(meta?.included)
        ? meta.included.filter((x) =>
            /工艺卡|bible|角色|地点|摘录|长程|对话记忆|上传|文风/.test(x)
          )
        : [];
      const refShort = refs.length ? `参考 ${refs.join("·")}` : "";
      setLastContext(
        [taskName, resultBit, craftShort, reviewShort, lensShort, refShort]
          .filter(Boolean)
          .join(" · ")
      );

      const warnings = res.warnings ?? [];
      const noteUndo = applied
        ? `可用「撤回编辑」回滚（当前对话内 ${undoStack.current.length} 步）`
        : "";
      const foot = [
        applied ? `已落地：${describeActions(actions)}` : "",
        warnings.length ? `未执行：${warnings.join("；")}` : "",
        noteUndo,
      ]
        .filter(Boolean)
        .join("\n");

      const assistantMsg: AgentChatMessage = {
        role: "assistant",
        content: foot ? `${res.message}\n\n${foot}` : res.message,
        trace: Array.isArray(res.trace) ? res.trace : undefined,
      };
      const finalMessages = [...opts.nextMessages, assistantMsg];
      setMessages(finalMessages);

      await putAgentConversation(projectId, convId, {
        messages: finalMessages.slice(-120),
        chat_memory: "",
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
      void refreshList();

      if (actions.some((a) => a.op === "add_chapter") && res.project) {
        const last = res.project.chapters[res.project.chapters.length - 1];
        if (last) onChapterFocus?.(last.id);
      }
    } catch (e) {
      // Aborted by unmount / superseded request — stay quiet (no error bubble).
      if (
        (e instanceof Error && e.message === "请求已取消") ||
        (e instanceof Error && e.name === "AbortError") ||
        streamAbortRef.current?.signal.aborted
      ) {
        return;
      }
      const msg = e instanceof Error ? e.message : "请求失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${msg}` },
      ]);
    } finally {
      if (noEventTimer !== undefined) window.clearTimeout(noEventTimer);
      setBusy(false);
      setLiveStream(null);
      // 同步服务器端 run_state（成功后为 done/空；失败后为 error → 显示"继续"）
      getAgentConversation(projectId, convId)
        .then((d) => setRunState(d.run_state ?? null))
        .catch(() => undefined);
    }
  }

  /** 断点续跑：上次多步运行中断/失败后，从检查点继续（不再重烧前面步骤）。 */
  async function resumeLastRun() {
    if (busy || !conversationId || !runState) return;
    setRunState(null);
    await streamAgentRun({
      resume: true,
      apiMessages: [],
      nextMessages: messages,
    });
  }

  async function sendText(text: string, task?: AgentTaskKind) {
    const trimmed = text.trim();
    const pendingAttach = attachments;
    if ((!trimmed && pendingAttach.length === 0) || busy || !conversationId) return;

    const userVisible =
      trimmed ||
      (pendingAttach.length
        ? `（已附上 ${pendingAttach.map((a) => a.filename).join("、")}，请阅读并协助整理）`
        : "");

    const intent = inferAgentIntent(userVisible, pendingAttach.length);

    if (intent.kind === "pipeline") {
      await runPipelineFlow(intent.note || trimmed);
      return;
    }
    if (intent.kind === "chapter_lock_name") {
      const name = intent.lockName || "";
      if (name && chapterId) {
        setChapterRevisePrefs(projectId, chapterId, { lockedNames: [name] });
        const userMsg: AgentChatMessage = { role: "user", content: userVisible };
        const assistantMsg: AgentChatMessage = {
          role: "assistant",
          content: `好，本章会尽量别动「${name}」。下次回炉会带上这条偏好。`,
        };
        const next = [...messagesRef.current, userMsg, assistantMsg].slice(-120);
        setMessages(next);
        messagesRef.current = next;
        setInput("");
        await putAgentConversation(projectId, conversationId, {
          messages: next,
        }).catch(() => undefined);
      }
      return;
    }
    if (intent.kind === "chapter_open_review") {
      const draft = pendingRevise || getChapterReviseDraft(projectId, chapterId);
      if (draft) {
        setPendingReviseState(draft);
        setReviseReviewOpen(true);
        const userMsg: AgentChatMessage = { role: "user", content: userVisible };
        const assistantMsg: AgentChatMessage = {
          role: "assistant",
          content:
            "已打开对照面板，逐段选「改稿」或「原文」即可。刷新后也可从写作区「改稿对照」再进。",
        };
        const next = [...messagesRef.current, userMsg, assistantMsg].slice(-120);
        setMessages(next);
        messagesRef.current = next;
        setInput("");
      } else {
        setError("还没有改稿预览。先说「帮我改这一章」，出预览后再对照挑选。");
      }
      return;
    }
    if (intent.kind === "chapter_polish") {
      await runChapterReviseFlow(intent.note || "再润一版，轻润不改结构", {
        mode: "light_touch",
        skipModePicker: true,
      });
      return;
    }
    if (intent.kind === "chapter_revise") {
      await runChapterReviseFlow(intent.note || trimmed, {
        mode: intent.mode,
        skipModePicker: Boolean(intent.mode),
      });
      return;
    }
    if (intent.kind === "settings_ingest") {
      if (!pendingAttach.length) {
        setError("要写入设定请先附上资料文件，再说一次即可");
        return;
      }
      await ingestSettingsFromAttachments();
      return;
    }
    if (intent.kind === "facts_scan") {
      await runFactsScanFlow(intent.note || trimmed);
      return;
    }
    if (intent.kind === "style_lint") {
      await runStyleLint();
      return;
    }
    if (intent.kind === "finalize") {
      await runQualityFinalize();
      return;
    }
    if (intent.kind === "ledger_digest") {
      await runLedgerDigest();
      return;
    }
    if (intent.kind === "brainstorm") {
      await runBrainstormFlow(intent.note || "");
      return;
    }
    if (intent.kind === "list_mentors") {
      await runListMentors();
      return;
    }

    let outbound = userVisible;
    if (intent.kind === "critique_only") {
      outbound = `${userVisible}\n\n【系统】本轮以文字审稿为主：完整意见写进 message；未明确要求写入前不要 replace_script。`;
    }

    setError("");
    setThinking(
      pendingAttach.length
        ? "编辑正在阅读附件 / 检索设定…"
        : "编辑正在检索设定 / 读当前章…"
    );
    const attachNote = pendingAttach.length
      ? `\n\n📎 附件：${pendingAttach
          .map((a) => `${a.filename}（${a.chars ?? a.text.length} 字）`)
          .join("、")}`
      : "";
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: `${outbound}${attachNote}` },
    ];
    setMessages(nextMessages);
    setAttachments([]);
    await streamAgentRun({
      resume: false,
      apiMessages: nextMessages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-20),
      nextMessages,
      task,
      attachments: pendingAttach,
    });
  }

  async function runListMentors() {
    if (busy || !conversationId) return;
    setError("");
    setThinking("读取写作导师配置…");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: "列出写作导师" },
    ];
    setMessages(nextMessages);
    setBusy(true);
    setLastContext("写作导师 · 列表");
    try {
      const data = await getProjectMentors(projectId);
      const activeNames =
        (data.active || []).map((p) => `**${p.name}** (\`${p.id}\`)`).join("、") ||
        "（将使用默认写作导师）";
      const content =
        `### 写作导师\n\n` +
        `当前启用：${activeNames}\n\n` +
        `这是**一份完整的 LN/VN 文学编辑方法论**（可演对白、钩子、类型热度），无需切换角色。\n` +
        `硬门禁仍以风格 Skill 为准；导师只提供写法判断。`;
      const finalMessages = [...nextMessages, { role: "assistant" as const, content }];
      setMessages(finalMessages);
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages.slice(-120),
        chat_memory: "",
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取导师失败");
    } finally {
      setBusy(false);
      setThinking("");
    }
  }

  async function commitLensIds(next: string[]) {
    setLensBusy(true);
    setError("");
    try {
      const res = await putProjectLenses(projectId, { activeIds: next });
      setActiveLensIds(res.activeIds || next);
      if (res.project) onProjectChange(res.project);
      if (!next.length) {
        setLastContext("对话对象 · 通用文学编辑");
      } else {
        const names = (res.active || []).map((p) => p.name).join("、");
        setLastContext(`对话对象 · ${names || next.join(",")}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "切换作家失败");
    } finally {
      setLensBusy(false);
    }
  }

  async function onWriterCardClick(id: string | null) {
    if (lensBusy) return;
    // Default editor
    if (id === null) {
      if (activeLensIds.length) await commitLensIds([]);
      if (!multiSelect) setPersonaOpen(false);
      return;
    }
    if (multiSelect) {
      const on = activeLensIds.includes(id);
      const next = on ? activeLensIds.filter((x) => x !== id) : [...activeLensIds, id];
      if (!on && next.length > 3) {
        setError("多选最多 3 位作家/写手");
        return;
      }
      await commitLensIds(next);
      return;
    }
    // Single-select: click again on current → back to default editor
    if (activeLensIds.length === 1 && activeLensIds[0] === id) {
      await commitLensIds([]);
      setPersonaOpen(false);
      return;
    }
    await commitLensIds([id]);
    setPersonaOpen(false);
  }

  async function runBrainstormFlow(topicOverride?: string) {
    if (busy || !conversationId) return;
    const topic =
      (topicOverride ?? brainstormTopic).trim() ||
      "请就当前章节与选区，从各自擅长角度给建议（未指定具体议题）。";
    if (activeLensIds.length < 2) {
      setError("强头脑风暴至少多选 2 位作家（点 ⇄ 打开多选）");
      setPersonaOpen(true);
      setMultiSelect(true);
      return;
    }
    setError("");
    setThinking("头脑风暴中：各位作家独立发言 → 责编综合…");
    const userLine = `【头脑风暴】${topic}`;
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: userLine },
    ];
    setMessages(nextMessages);
    setBusy(true);
    setLastContext("头脑风暴 · 分视角独立 → 综合");
    setPersonaOpen(false);
    try {
      const data = await runBrainstorm(projectId, {
        question: topic,
        lens_ids: activeLensIds,
        chapter_id: chapterId,
        selection: selection || undefined,
        draft: (draft || "").trim() || undefined,
      });
      const content = data.markdown || data.synthesis || "（无结果）";
      const finalMessages = [...nextMessages, { role: "assistant" as const, content }];
      setMessages(finalMessages);
      setLastContext(`头脑风暴完成 · ${data.okCount}/${data.authorCount} 视角`);
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages.slice(-120),
        chat_memory: "",
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "头脑风暴失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${msg}` },
      ]);
    } finally {
      setBusy(false);
      setThinking("");
    }
  }

  async function runStyleLint() {
    if (busy || !conversationId) return;
    const text = (draft || "").trim();
    if (!text) {
      setError("文风体检需要脚本区有正文");
      return;
    }
    setError("");
    setThinking("正在对照风格 Skill 做体检…");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: "【文风体检】请检查当前章节草稿。" },
    ];
    setMessages(nextMessages);
    setBusy(true);
    setLastContext("文风体检 · 风格 Skill + 去AI味");
    try {
      const data = await harnessLint(projectId, text);
      const content = `### 文风体检\n\n${formatLintBlock(data)}`;
      const finalMessages = [...nextMessages, { role: "assistant" as const, content }];
      setMessages(finalMessages);
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages.slice(-120),
        chat_memory: "",
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
      void refreshList();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "体检失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${msg}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function runPipelineFlow(instruction: string) {
    if (busy || !conversationId) return;
    const userLine =
      instruction.trim() || "请按风格 Skill 与项目硬锚，续写下一场可上演戏。";
    setError("");
    setThinking("流水线运行中：规划 → 生成 → 检查 → 修正…");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: `【流水线】${userLine}` },
    ];
    setMessages(nextMessages);
    setBusy(true);
    setLastContext("流水线 · Plan→Write→Check→Revise");
    try {
      const prefs = getHarnessPrefs();
      const body = {
        instruction: userLine,
        draft: (draft || "").trim() || undefined,
        selection: selection || undefined,
        chapter_id: chapterId,
        apply_to_chapter: true,
        max_revise_rounds: prefs.maxReviseRounds ?? 2,
        voice_check: prefs.voiceCheck !== false,
        voice_hard: Boolean(prefs.voiceHard),
      };
      const STAGE_LABEL: Record<string, string> = {
        plan: "规划",
        write: "生成",
        check: "检查",
        revise: "修正",
        done: "完成",
      };
      let job: import("../api/pipeline").JobStatus;
      let liveDraft = "";
      let controller: AbortController | undefined;
      try {
        setThinking("流水线启动（流式）…");
        streamAbortRef.current?.abort();
        controller = new AbortController();
        streamAbortRef.current = controller;
        job = await pipelineRunStream(projectId, body, (evt) => {
          if (evt.type === "token") {
            liveDraft += evt.delta;
            setThinking(`生成中… ${liveDraft.slice(-160)}`);
            return;
          }
          if (evt.type === "stage") {
            const label = STAGE_LABEL[evt.stage] ?? evt.stage;
            const ms = evt.ms ? ` · ${evt.ms}ms` : "";
            const extra =
              evt.errorCount != null
                ? ` · error ${evt.errorCount}`
                : evt.warnCount != null
                  ? ` · warn ${evt.warnCount}`
                  : "";
            setThinking(`流水线：${label} 完成${ms}${extra}`);
          }
        }, controller.signal);
      } catch (e) {
        // User cancelled (component unmount / superseded request) — don't
        // fall back to a polling job that would keep consuming quota.
        if (
          controller?.signal.aborted ||
          (e instanceof Error && e.message === "请求已取消")
        ) {
          throw new Error("请求已取消", { cause: e });
        }
        // Fallback: non-streaming kick + poll
        const kicked = await pipelineRun(projectId, {
          ...body,
          async_mode: true,
        });
        if (!("jobId" in kicked) || !kicked.jobId) {
          throw new Error("流水线启动失败", { cause: e });
        }
        setThinking("流水线已后台启动，正在等待各阶段…");
        job = await waitProjectJob(projectId, kicked.jobId, {
          onTick: (j) => {
            const pct = Math.round((j.progress ?? 0) * 100);
            setThinking(
              `流水线 ${j.stage || "运行中"} · ${pct}%${
                j.message ? ` — ${j.message}` : ""
              }`
            );
          },
        });
      }
      if (job.status === "error") {
        throw new Error(job.error || job.message || "流水线任务失败");
      }
      const data = (job.result ?? {}) as unknown as PipelineRunResult;
      const content = formatPipelineResult(data);
      const finalMessages = [...nextMessages, { role: "assistant" as const, content }];
      setMessages(finalMessages);
      if (data.applied && data.project) {
        onProjectChange(data.project);
      }
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages.slice(-120),
        chat_memory: "",
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
      void refreshList();
      setLastContext(
        data.applied
          ? "流水线完成 · 已写入章节"
          : data.gate?.pass
            ? "流水线完成 · 门禁通过"
            : `流水线完成 · 门禁未过（error ${data.gate?.errorCount ?? "?"}）`
      );
    } catch (e) {
      if (
        (e instanceof Error && e.message === "请求已取消") ||
        streamAbortRef.current?.signal.aborted
      ) {
        return;
      }
      const msg = e instanceof Error ? e.message : "流水线失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${msg}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function runQualityFinalize() {
    if (busy || !conversationId) return;
    setError("");
    setBusy(true);
    try {
      const prefs = getHarnessPrefs();
      const data = await pipelineGate(projectId, {
        draft: (draft || "").trim() || undefined,
        chapter_id: chapterId,
        finalize: true,
        update_ledger: true,
        enrich_ledger: true,
        voice_check: prefs.voiceCheck !== false,
        voice_hard: Boolean(prefs.voiceHard),
      });
      const ok = data.gate?.pass;
      const enrichBit = data.enrichMeta?.enrich
        ? `（账本 LLM 充实：事实 ${data.enrichMeta.factCount ?? 0} / 状态 ${data.enrichMeta.stateCount ?? 0} / 伏笔 ${data.enrichMeta.foreshadowCount ?? 0}）`
        : data.enrichMeta?.error
          ? `（账本充实回退启发式：${data.enrichMeta.error}）`
          : "";
      const content = ok
        ? `### 定稿入库\n\n${data.gate?.message || "已通过质量门禁"}${enrichBit}\n\n章节事实摘要已写入写作账本，供后续生成作硬锚。`
        : `### 定稿被门禁拦截\n\n${data.gate?.message || "未通过"}\n\n${(
            data.check?.issues || []
          )
            .filter((i) => i.severity === "error")
            .slice(0, 12)
            .map((i) => `- ${i.code}：${i.message}`)
            .join("\n")}`;
      setMessages((prev) => [...prev, { role: "assistant", content }]);
      if (data.project) {
        onProjectChange(data.project);
      }
      setLastContext(
        ok ? "定稿 · 门禁通过 · 账本已更新" : "定稿 · 门禁拦截（已记运行历史）"
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "定稿失败");
    } finally {
      setBusy(false);
    }
  }

  async function runLedgerDigest() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await pipelineLedgerDigest(projectId, chapterId, {
        enrich: true,
      });
      onProjectChange(data.project);
      const enrichBit = data.enrichMeta?.enrich
        ? `（LLM 充实：事实 ${data.enrichMeta.factCount ?? 0} / 状态 ${data.enrichMeta.stateCount ?? 0} / 伏笔 ${data.enrichMeta.foreshadowCount ?? 0}）`
        : data.enrichMeta?.error
          ? `（LLM 充实未成功，已用启发式：${data.enrichMeta.error}）`
          : "（启发式摘要）";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `### 章节锚点已入库${enrichBit}\n\n已将当前章的事实摘要 / 出场状态 / 章末钩子写入写作账本。\n\n${(
            data.agentBlock || ""
          ).slice(0, 1200)}`,
        },
      ]);
      setLastContext(
        data.enrichMeta?.enrich ? "账本 · LLM 充实已更新" : "账本 · 章节摘要已更新"
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "账本更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text && attachments.length === 0) return;
    setInput("");
    await sendText(text);
  }

  async function onPickFiles(files: FileList | null) {
    if (!files?.length || !conversationId) return;
    setAttachBusy(true);
    setError("");
    try {
      const next: AgentAttachment[] = [...attachments];
      for (const file of Array.from(files)) {
        if (next.length >= 5) {
          setError("一次最多 5 个附件");
          break;
        }
        const att = await uploadAgentAttachment(projectId, file, true);
        next.push(att);
        if (att.warning) setError(att.warning);
      }
      setAttachments(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setAttachBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function ingestSettingsFromAttachments() {
    if (!attachments.length || !conversationId || busy) return;
    const pending = [...attachments];
    const snapshot = prepareProject ? prepareProject() : project;
    setError("");
    setBusy(true);
    setThinking("正在把附件结构化写入设定页…");
    setAttachments([]);
    const userMsg: AgentChatMessage = {
      role: "user",
      content: `【写入设定页】请根据附件更新故事设定与角色卡。\n\n📎 ${pending
        .map((a) => `${a.filename}（${a.chars ?? a.text.length} 字）`)
        .join("、")}`,
    };
    const withUser = [...messagesRef.current, userMsg].slice(-120);
    setMessages(withUser);
    messagesRef.current = withUser;
    try {
      const res = await ingestAttachmentSettings(projectId, {
        attachments: pending,
        note: "请把附件信息写入设定页（世界观/背景/大纲/主题/备忘）与角色卡",
        conversation_id: conversationId,
      });
      if (res.wrote && res.project) {
        undoStack.current = [
          ...undoStack.current,
          { label: describeActions(res.actions || []), project: snapshot },
        ].slice(-20);
        setUndoCount(undoStack.current.length);
        onProjectChange(res.project);
      }
      const foot = [
        res.wrote
          ? `已落地：${(res.applied || []).join("；") || describeActions(res.actions || [])}`
          : "未写入工程",
        (res.skipped || []).length ? `未执行：${res.skipped.join("；")}` : "",
        res.wrote
          ? `可用「撤回编辑」回滚（当前对话内 ${undoStack.current.length} 步）· 请打开「设定」页查看`
          : "",
      ]
        .filter(Boolean)
        .join("\n");
      const assistantMsg: AgentChatMessage = {
        role: "assistant",
        content: foot ? `${res.message}\n\n${foot}` : res.message,
      };
      const finalMessages = [...withUser, assistantMsg].slice(-120);
      setMessages(finalMessages);
      messagesRef.current = finalMessages;
      setLastContext(res.wrote ? "已写入设定页" : "设定写入未完成");
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages,
      }).catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "写入设定失败");
      setAttachments(pending);
    } finally {
      setBusy(false);
      setThinking("");
    }
  }

  async function runFactsScanFlow(note?: string) {
    if (!conversationId || busy) return;
    const pending = [...attachments];
    const snapshot = prepareProject ? prepareProject() : project;
    setError("");
    setBusy(true);
    setThinking("正在扫描关系 / 时间线事实…");
    setAttachments([]);
    const paste = pending
      .map((a) => a.text)
      .filter(Boolean)
      .join("\n\n");
    const userMsg: AgentChatMessage = {
      role: "user",
      content: pending.length
        ? `【整理关系/时间线】${note?.trim() || ""}\n\n📎 ${pending
            .map((a) => `${a.filename}（${a.chars ?? a.text.length} 字）`)
            .join("、")}`
        : `【整理关系/时间线】${note?.trim() || "请扫描当前章事实"}`,
    };
    const withUser = [...messagesRef.current, userMsg].slice(-120);
    setMessages(withUser);
    messagesRef.current = withUser;
    try {
      const res = await factsScan(projectId, {
        chapter_id: chapterId,
        paste_text: paste || undefined,
        persist_paste: Boolean(paste),
        full: /全文|整本|全扫|full/i.test(note || ""),
      });
      if (res.project) {
        undoStack.current = [
          ...undoStack.current,
          { label: "事实扫描", project: snapshot },
        ].slice(-20);
        setUndoCount(undoStack.current.length);
        onProjectChange(res.project);
      }
      const n = res.inbox?.length ?? 0;
      const s = res.summary;
      const assistantMsg: AgentChatMessage = {
        role: "assistant",
        content: [
          "已跑完事实扫描，候选进**写作分析待审托盘**（需你确认后才进关系图/时间线）。",
          s
            ? `摘要：新增候选 ${s.added}（关系 ${s.characterLinks} / 时间线 ${s.timelineEvents}）。`
            : "",
          n ? `当前托盘约 ${n} 条。` : "本轮没有新的待审条目。",
          paste ? "已把附件正文当作临时粘贴源。" : "",
        ]
          .filter(Boolean)
          .join("\n"),
      };
      const finalMessages = [...withUser, assistantMsg].slice(-120);
      setMessages(finalMessages);
      messagesRef.current = finalMessages;
      setLastContext("事实扫描完成");
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages,
      }).catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "事实扫描失败");
      if (pending.length) setAttachments(pending);
    } finally {
      setBusy(false);
      setThinking("");
    }
  }

  async function runChapterReviseFlow(
    note?: string,
    opts?: { mode?: ReviseMode; skipModePicker?: boolean }
  ) {
    if (!conversationId || busy) return;
    // 用户主动改章时再弹模式选择；话里已点明模式（或「再润」）则跳过
    if (!opts?.skipModePicker) {
      revisePendingArgs.current = { note, mode: opts?.mode };
      setReviseModeOpen(true);
      return;
    }
    const prefs = getChapterRevisePrefs(projectId, chapterId);
    const resolvedMode: ReviseMode = opts?.mode || prefs.mode || "human_warmth";
    setChapterRevisePrefs(projectId, chapterId, { mode: resolvedMode });

    const pending = [...attachments];
    setError("");
    setBusy(true);
    setThinking("正在准备改稿预览…");
    setAttachments([]);
    const prefNote = prefsToNoteSuffix({ ...prefs, mode: resolvedMode });
    const noteCombined = [note?.trim(), prefNote].filter(Boolean).join("\n");
    const userMsg: AgentChatMessage = {
      role: "user",
      content: pending.length
        ? `【改稿】${note?.trim() || "请改一版"}\n\n📎 ${pending
            .map((a) => `${a.filename}（${a.chars ?? a.text.length} 字）`)
            .join("、")}`
        : `【改稿】${note?.trim() || "请改当前章"}`,
    };
    const withUser = [...messagesRef.current, userMsg].slice(-120);
    setMessages(withUser);
    messagesRef.current = withUser;
    setInput("");
    try {
      const kicked = await chapterRevise(projectId, {
        chapter_id: chapterId,
        note: noteCombined || undefined,
        conversation_id: conversationId,
        attachments: pending,
        mode: resolvedMode,
        preferences: {
          lockedNames: prefs.lockedNames,
          preferKeepOriginal: prefs.preferKeepOriginal,
          notes: prefs.notes,
          mode: resolvedMode,
        },
        async_mode: true,
      });
      let res: {
        message: string;
        revisedText?: string;
        chapterId?: string | null;
        sourceText?: string;
        diagnosisMd?: string;
        [k: string]: unknown;
      };
      if ("jobId" in kicked && kicked.jobId) {
        setThinking("回炉已后台启动…");
        const job = await waitProjectJob(projectId, kicked.jobId, {
          onTick: (j) => {
            const pct = Math.round((j.progress ?? 0) * 100);
            setThinking(
              `回炉 ${j.stage || "运行中"} · ${pct}%${
                j.message ? ` — ${j.message}` : ""
              }`
            );
          },
        });
        if (job.status === "error") {
          throw new Error(job.error || job.message || "回炉任务失败");
        }
        res = (job.result || {}) as typeof res;
      } else {
        res = kicked as typeof res;
      }
      const reviseChapterId = res.chapterId || chapterId;
      const assistantMsg: AgentChatMessage = {
        role: "assistant",
        content: res.message,
        ...(res.revisedText && reviseChapterId
          ? {
              action: {
                type: "open_revise_review" as const,
                chapterId: reviseChapterId,
                label: "打开改稿对照",
              },
            }
          : {}),
      };
      const finalMessages = [...withUser, assistantMsg].slice(-120);
      setMessages(finalMessages);
      messagesRef.current = finalMessages;
      if (res.revisedText && reviseChapterId) {
        const snap = prepareProject ? prepareProject() : project;
        const ch = snap.chapters.find((c) => c.id === reviseChapterId);
        const fromEditor =
          ch != null ? blocksToEditable(ch.blocks, snap.characters) : "";
        setPendingRevise({
          chapterId: reviseChapterId,
          revisedText: res.revisedText,
          // Always prefer API sourceText (same plain format as the rewrite).
          // Never fall back to Ren'Py editable — that breaks side-by-side align.
          originalText: (res.sourceText || "").trim() || fromEditor,
          chapterTitle:
            typeof res.chapterTitle === "string" ? res.chapterTitle : ch?.title,
          diagnosisMd:
            typeof res.diagnosisMd === "string" ? res.diagnosisMd : undefined,
          savedAt: Date.now(),
        });
        setReviseReviewOpen(true);
      }
      setLastContext("改稿预览（未写入）");
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages,
      }).catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "改稿失败");
      if (pending.length) setAttachments(pending);
    } finally {
      setBusy(false);
      setThinking("");
    }
  }

  async function applyChapterRevise(text?: string) {
    if (!pendingRevise || busy) return;
    const snapshot = prepareProject ? prepareProject() : project;
    const bodyText = (text ?? pendingRevise.revisedText).trim();
    if (bodyText.length < 40) {
      setError("合并后的正文过短，请再挑选几段");
      return;
    }
    setError("");
    setBusy(true);
    setThinking("正在写入改稿…");
    try {
      const res = await chapterReviseApply(projectId, {
        chapter_id: pendingRevise.chapterId,
        text: bodyText,
        conversation_id: conversationId || undefined,
      });
      if (res.wrote && res.project) {
        undoStack.current = [
          ...undoStack.current,
          { label: "改稿写入", project: snapshot },
        ].slice(-20);
        setUndoCount(undoStack.current.length);
        onProjectChange(res.project);
        if (onChapterFocus) onChapterFocus(pendingRevise.chapterId);
      }
      setPendingRevise(null, { clearChapterId: pendingRevise.chapterId });
      setReviseReviewOpen(false);
      const assistantMsg: AgentChatMessage = {
        role: "assistant",
        content: `${res.message}\n\n可用「撤回编辑」回滚（当前对话内 ${undoStack.current.length} 步）。`,
      };
      // Drop stale「打开对照」chips once written
      const cleared = messagesRef.current.map((m) =>
        m.action?.type === "open_revise_review"
          ? { role: m.role, content: m.content }
          : m
      );
      const finalMessages = [...cleared, assistantMsg].slice(-120);
      setMessages(finalMessages);
      messagesRef.current = finalMessages;
      setLastContext("改稿已写入");
      if (conversationId) {
        await putAgentConversation(projectId, conversationId, {
          messages: finalMessages,
        }).catch(() => undefined);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "写入失败");
    } finally {
      setBusy(false);
      setThinking("");
    }
  }

  const personaLabel = !activeLensIds.length
    ? DEFAULT_WRITER.name
    : activeLensIds
        .map((id) => lensCatalog.find((p) => p.id === id)?.name || id)
        .join(" · ");

  const writerCards = buildWriterCards(lensCatalog);

  const detailCard =
    writerCards.find((c) => (c.id ?? "__default__") === detailKey) || null;

  const partyCards = activeLensIds
    .map((id) => writerCards.find((c) => c.id === id))
    .filter(Boolean) as typeof writerCards;

  const showEmptyStage = !loadingConv && messages.length <= 1 && !busy && !input.trim();
  const turnCount = messages.filter((m) => m.role === "user").length;

  return (
    <div
      className={`${compact ? styles.shellCompact : styles.shell} ${styles.gameShell}`}
      style={hidden ? { display: "none" } : undefined}
      aria-hidden={hidden || undefined}
    >
      <div className={styles.stage} ref={splitRef}>
        <AgentConversationRail
          conversations={conversations}
          conversationId={conversationId}
          titleDrafts={titleDrafts}
          busy={busy}
          loadingConv={loadingConv}
          sidebarW={sidebarW}
          dossierOpen={dossierOpen}
          onNew={() => void handleNewConversation()}
          onSwitch={(id) => void switchConversation(id)}
          onClose={() => setDossierOpen(false)}
          onRenameChange={handleRenameChange}
          onRenameCommit={handleRenameCommit}
          onDelete={(id) => void handleDeleteConversation(id)}
          onTitleRef={(id, el) => {
            titleInputRefs.current[id] = el;
          }}
          onResizeStart={handleResizeStart}
        />

        <div className={styles.main}>
          {runState &&
            (runState.status === "interrupted" || runState.status === "error") && (
              <div className={styles.resumeBar} role="status">
                <span>
                  上次运行{runState.status === "interrupted" ? "中断" : "失败"}
                  {typeof runState.step === "number" &&
                  typeof runState.steps === "number"
                    ? `（已完成 ${runState.step}/${runState.steps} 步）`
                    : ""}
                  ——可从断点继续，不会重复已完成的步骤。
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void resumeLastRun()}
                >
                  {busy ? "运行中…" : "继续上次运行"}
                </button>
              </div>
            )}
          <AgentMessagesList
            messages={messages}
            busy={busy}
            thinking={thinking}
            liveStream={liveStream}
            showEmptyStage={showEmptyStage}
            personaLabel={personaLabel}
            activeLensIds={activeLensIds}
            projectId={projectId}
            dossierOpen={dossierOpen}
            personaOpen={personaOpen}
            helpOpen={helpOpen}
            selection={selection}
            lastContext={lastContext}
            error={error}
            undoCount={undoCount}
            scrollerRef={scroller}
            onOpenReviseReview={handleOpenReviseReview}
            onToggleDossier={handleToggleDossier}
            onTogglePersona={handleTogglePersona}
            onToggleHelp={handleToggleHelp}
            onUndo={() => void undoAgentEdit()}
          />

          <AgentAttachList
            attachments={attachments}
            busy={busy}
            attachBusy={attachBusy}
            conversationId={conversationId}
            onRemove={(i) =>
              setAttachments((prev) => prev.filter((_, j) => j !== i))
            }
            onIngest={() => void ingestSettingsFromAttachments()}
            onScan={() => void runFactsScanFlow("请根据附件整理关系与时间线")}
          />

          <AgentComposerBox
            value={input}
            onChange={setInput}
            onSend={() => void send()}
            compact={compact}
            busy={busy}
            disabled={busy || loadingConv || !conversationId}
            canSend={Boolean(input.trim()) || attachments.length > 0}
            turnCount={turnCount}
            attachBusy={attachBusy}
            fileInputRef={fileInputRef}
            onPickFiles={(files) => void onPickFiles(files)}
          />

          {personaOpen ? (
            <AgentPersonaOverlay
              multiSelect={multiSelect}
              partyCards={partyCards}
              activeLensIds={activeLensIds}
              brainstormTopic={brainstormTopic}
              busy={busy}
              lensBusy={lensBusy}
              writerCards={writerCards}
              onClose={() => setPersonaOpen(false)}
              onToggleMulti={setMultiSelect}
              onTopicChange={setBrainstormTopic}
              onBrainstorm={() => void runBrainstormFlow()}
              onSelectCard={setDetailKey}
            />
          ) : null}

          {helpOpen ? (
            <AgentHelpOverlay
              prefs={harnessPrefs}
              onPrefsChange={(next) => setHarnessPrefsState(setHarnessPrefs(next))}
              onClose={() => setHelpOpen(false)}
            />
          ) : null}

          {detailCard ? (
            <div
              className={styles.archiveBackdrop}
              role="presentation"
              onClick={() => setDetailKey(null)}
            >
              <div
                className={styles.archive}
                role="dialog"
                aria-modal="true"
                aria-label={`${detailCard.name} 档案`}
                onClick={(e) => e.stopPropagation()}
              >
                <WriterPortrait lensId={detailCard.id} size="lg" selected />
                <div className={styles.archiveBody}>
                  <p className={styles.archiveIdx}>档案</p>
                  <p className={styles.archiveRole}>{detailCard.role}</p>
                  <h3 className={styles.archiveName}>{detailCard.name}</h3>
                  <p className={styles.archiveBlurb}>{detailCard.blurb}</p>
                  <div className={styles.archiveActions}>
                    <button
                      type="button"
                      className={styles.helpClose}
                      onClick={() => setDetailKey(null)}
                    >
                      关闭
                    </button>
                    <button
                      type="button"
                      className={styles.brainstormBtn}
                      disabled={lensBusy}
                      onClick={() => {
                        void onWriterCardClick(detailCard.id);
                        setDetailKey(null);
                        if (!multiSelect) setPersonaOpen(false);
                      }}
                    >
                      {multiSelect
                        ? activeLensIds.includes(detailCard.id as string)
                          ? "移出队伍"
                          : "加入队伍"
                        : detailCard.id === null ||
                            (activeLensIds.length === 1 &&
                              activeLensIds[0] === detailCard.id)
                          ? "设为默认编辑"
                          : "设为对话对象"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {reviseModeOpen ? (
            <ChapterReviseModePicker
              defaultMode={
                getChapterRevisePrefs(projectId, chapterId).mode || "human_warmth"
              }
              busy={busy}
              onCancel={() => {
                setReviseModeOpen(false);
                revisePendingArgs.current = null;
              }}
              onPick={(mode) => {
                const args = revisePendingArgs.current;
                revisePendingArgs.current = null;
                setReviseModeOpen(false);
                void runChapterReviseFlow(args?.note, {
                  mode,
                  skipModePicker: true,
                });
              }}
            />
          ) : null}

          {reviseReviewOpen && pendingRevise ? (
            <ChapterReviseReview
              key={`${pendingRevise.chapterId}-${pendingRevise.revisedText.length}`}
              chapterTitle={pendingRevise.chapterTitle}
              originalText={pendingRevise.originalText}
              revisedText={pendingRevise.revisedText}
              diagnosisMd={pendingRevise.diagnosisMd}
              busy={busy}
              onCancel={() => setReviseReviewOpen(false)}
              onApply={(merged, meta) => {
                if (meta.keptOriginal > meta.keptRevised) {
                  setChapterRevisePrefs(projectId, pendingRevise.chapterId, {
                    preferKeepOriginal: true,
                    notes: ["用户常保留原文段落，下回少改大段旁白"],
                  });
                }
                void applyChapterRevise(merged);
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
