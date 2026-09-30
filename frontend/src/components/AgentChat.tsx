import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import {
  AGENT_SECTIONS,
  loadExcludedSections,
  saveExcludedSections,
  toggleSection,
} from "../lib/agentSections";
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
  startBrainstormJob,
  type BrainstormResult,
  listAgentConversations,
  putAgentConversation,
  renameAgentConversation,
  runAgentStream,
  uploadAgentAttachment,
  ingestAttachmentSettings,
  applyAgentActions,
  agentWriteStream,
  chapterRevise,
  chapterReviseApply,
  factsScan,
  fetchPreQuestions,
  type AgentAttachment,
  type AgentConversationOut,
  type AgentConversationSummary,
  type LensPackMeta,
  type PipelineRunResult,
} from "../api/client";
import { inferAgentIntent } from "../lib/agentIntent";
import { attachmentLines, flowUserMessage } from "../lib/agentFlowMessage";
import {
  planForFactsScan,
  planForFinalize,
  planForLedgerDigest,
  planForPipeline,
  planForSettingsIngest,
} from "../lib/agentPlan";
import { compactRunInfo, readRunInfoOpen, writeRunInfoOpen } from "../lib/agentRunInfo";
import {
  getChapterRevisePrefs,
  prefsToNoteSuffix,
  resolveReviseMode,
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
  AgentAction,
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
  planActionLines,
} from "../lib/agentFormat";
import { copyForProject } from "../lib/genreCopy";
import { contextUsage, type ContextUsage } from "../lib/contextUsage";
import {
  budgetNotice,
  includedSummary,
  retrieveAllMessage,
  type BudgetNotice,
} from "../lib/contextBudget";
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
  /**
   * 写后闸失败段 → 在正文建「标记批改」（不自动跑模型）。
   * 由 StudioApp 接 marks 状态；返回成功建了几条。
   */
  onCreateMarksFromHints?: (
    hints: Array<{
      quote?: string;
      reason?: string;
      instruction?: string;
      code?: string;
    }>
  ) => number;
  compact?: boolean;
  /** Hidden when float is minimized — keep mounted so state survives */
  hidden?: boolean;
};

/**
 * 待确认的写入方案（"先给方案、确认后才写"那道闸）。
 *
 * 为什么要有它：除了改稿（早就是"先出对照、确认才写"），其余会动工程的流程以前都是
 * 说一句就写——模型一给动作就落库，作者只在事后看到「已写入工程」。作者踩到的坑是
 * 关键词被误判成命令（带附件聊到"设定"就被送去写入设定页），而一旦写下去只能靠撤回。
 * 现在这几类流程先摆方案：**方案里列的是这次会动到什么**，点了确认才真的调后端写。
 */
type PendingPlanKind =
  | "chat_actions"
  | "settings_ingest"
  | "facts_scan"
  | "pipeline"
  | "finalize"
  | "ledger";

type PendingPlan = {
  kind: PendingPlanKind;
  title: string;
  lines: string[];
  /** 提醒：确认前不会改动工程 */
  note?: string;
  confirmLabel: string;
  /** chat_actions：后端回的那批动作；pipeline / facts_scan：沿用作者原话 */
  actions?: AgentAction[];
  instruction?: string;
  /** 确认写入要落到哪个对话的撤回栈里 */
  conversationId?: string;
};

/**
 * 方案卡片上回显作者原话。
 *
 * 为什么要它：出方案时那条消息还没进对话记录（写入发生在确认之后，那时流程会自己补一条
 * 【写入设定页】之类的指令），作者会觉得"我刚说的话去哪了"。长消息要截断，
 * 否则一段分析会把卡片撑成一屏。
 */
function quoteAsk(text: string, limit = 40): string {
  const t = (text || "").replace(/\s+/g, " ").trim();
  if (!t) return "你的要求：（只有附件，没有额外说明）";
  return t.length > limit ? `你的要求：${t.slice(0, limit)}…` : `你的要求：${t}`;
}

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

/**
 * 起手句：新对话里"一次都不用打字"就能开口。
 *
 * 为什么是这四句：新手真正卡住的是"不知道该让它干什么"，而不是不会打字。
 * 这四句覆盖了最常见的四种意图（续写 / 改稿 / 挑毛病 / 整理设定）；
 * 点了只填进输入框，不直接发送——省打字，但不替作者花模型调用。
 */
const STARTERS = [
  "接着写一小段可上演的内容",
  "帮我润色这一章",
  "这章有什么问题？",
  "按附件整理设定条目",
];

export function AgentChat({
  project,
  chapterId,
  selection,
  draft = "",
  prepareProject,
  onProjectChange,
  onChapterFocus,
  onCreateMarksFromHints,
  compact,
  hidden,
}: Props) {
  const projectId = project.id;
  // Agent 的"写入动作"文案里，append_script / replace_script 要跟着作品体裁叫名字
  // （剧本 / 正文）。体裁只能从 project 读，所以在组件里取一次；无需 useMemo——
  // copyForProject 内部只是查表，返回的是模块级常量对象，不会造成额外渲染。
  const copy = copyForProject(project);
  const [conversations, setConversations] = useState<AgentConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // 上次运行检查点摘要（run_state）：status=interrupted/error 时显示"继续上次"
  const [runState, setRunState] = useState<NonNullable<
    AgentConversationOut["run_state"]
  > | null>(null);
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
  /** 待确认的写入方案：非空时输入框上方出现方案卡片，确认后才真的写（见 confirmPendingPlan）。 */
  const [pendingPlan, setPendingPlan] = useState<PendingPlan | null>(null);
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
  /** 「选个方向」时先把待改的说明记在这里，等作者在面板里选完再真正开跑。 */
  const revisePendingArgs = useRef<{
    note?: string;
    mode?: ReviseMode;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [loadingConv, setLoadingConv] = useState(true);
  /** 「动笔前先问几句」：问题卡片 + 作者的回答（可跳过） */
  const [preQuestions, setPreQuestions] = useState<string[] | null>(null);
  const [preQuestionsSource, setPreQuestionsSource] = useState<"llm" | "template">(
    "llm"
  );
  const [preAnswers, setPreAnswers] = useState<Record<number, string>>({});
  const preQBusy = useRef(false);
  /** 提问时那句话（回答完/跳过都用它作为写作指令） */
  const pendingGoalRef = useRef("");

  async function openPreQuestions() {
    const goal = input.trim();
    if (!goal || preQBusy.current) return;
    preQBusy.current = true;
    setError("");
    try {
      const res = await fetchPreQuestions(projectId, {
        goal,
        chapter_id: chapterId,
      });
      pendingGoalRef.current = goal;
      setPreQuestions(res.questions?.length ? res.questions : null);
      setPreQuestionsSource(res.source === "template" ? "template" : "llm");
      setPreAnswers({});
    } catch (e) {
      // 问问题这一步失败不该拦住写作：退回直接写
      setError(
        e instanceof Error
          ? `先问几句没成功（${e.message}），已直接开始写`
          : "先问几句没成功，已直接开始写"
      );
      void sendText(goal);
    } finally {
      preQBusy.current = false;
    }
  }

  async function confirmPreQuestions() {
    const goal = pendingGoalRef.current;
    const qs = preQuestions ?? [];
    const pairs = qs
      .map((q, i) => ({ q, a: (preAnswers[i] ?? "").trim() }))
      .filter((p) => p.a);
    setPreQuestions(null);
    if (!pairs.length) {
      void sendText(goal);
      return;
    }
    // 答案作为硬约束并入指令——和文枢把答案写进场景简报是同一个意思
    const composed = [
      goal,
      "",
      "【先回答的几点，按这个写】",
      ...pairs.map((p) => `- ${p.q} → ${p.a}`),
    ].join("\n");
    void sendText(composed);
  }

  /** 还没有任何用户发言 → 给起手句（最省打字的一种"建议提示词"） */
  const showStarters =
    !busy && input.trim() === "" && !messages.some((m) => m.role === "user");
  const [error, setError] = useState("");
  const [lastContext, setLastContext] = useState<string>("");
  /** 同一份元信息的折叠态摘要（见 lib/agentRunInfo.ts）——默认收起，落盘记住 */
  const [lastContextCompact, setLastContextCompact] = useState<string>("");
  const [runInfoOpen, setRunInfoOpen] = useState<boolean>(() => readRunInfoOpen());
  const [gateMarkHints, setGateMarkHints] = useState<
    Array<{ quote?: string; reason?: string; instruction?: string; code?: string }>
  >([]);
  /** 「资料」开关：这次不交给 AI 的资料块（只影响本机会话；后端会忽略未知 key） */
  const [excluded, setExcluded] = useState<string[]>(() => loadExcludedSections());
  const [sectionsOpen, setSectionsOpen] = useState(false);
  /** 「证明它记得」：本次实际依据的资料与摘录 */
  const [evidence, setEvidence] = useState<Array<{ label: string; preview: string }>>(
    []
  );
  /** 本次上下文用量（读了多少 / 上限 / 有没有被裁）——见 lib/contextUsage.ts */
  const [contextInfo, setContextInfo] = useState<ContextUsage>({
    text: "",
    truncated: false,
    nearLimit: false,
    hint: "",
  });
  /** 「这次没装下什么、怎么取回来」——见 lib/contextBudget.ts */
  const [budgetInfo, setBudgetInfo] = useState<BudgetNotice>({
    missing: [],
    byDesign: [],
    hasMissing: false,
    hasRetrievable: false,
  });
  /** 本次用的是谁的钱：own / shared（免费档） */
  const [credentialsMode, setCredentialsMode] = useState("");

  // 资料开关落盘：这是"我怎么用界面"的偏好，不是作品数据
  useEffect(() => {
    saveExcludedSections(excluded);
  }, [excluded]);
  /** 「本次运行」详情是不是展开的（默认收起，落盘记住——见 lib/agentRunInfo.ts） */
  const toggleRunInfo = useCallback(() => setRunInfoOpen((v) => !v), []);
  useEffect(() => {
    writeRunInfoOpen(runInfoOpen);
  }, [runInfoOpen]);
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
    // 换了剧本就连"待发送的附件"一起清掉：那是上一个剧本排队要喂进来的素材，
    // 留着会被当成新剧本的资料发出去（剧本之间不该串味）。
    setAttachments([]);

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
      body: `消息记录将从服务器移除，不会改动${copy.work}内容。`,
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
        content: `已撤回「${popped.label}」，文稿已恢复到这次 AI 改动之前。`,
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
    setGateMarkHints([]);
    // 防御：**90 秒一个字节都没收到**（连服务端 20s 一次的 `: keepalive` 都没有）
    // 才判定连接出了问题，否则 busy 永远为 true，界面卡死在"正在检索设定"。
    //
    // 判据必须是"收到任何数据"，不能是"收到业务事件"：慢思考模型在 reasoning
    // 阶段只发心跳、不发业务事件，用后者会在模型正常思考时把连接掐掉，还弹出
    // "请检查模型配置"——把"模型慢"误报成"配置错"。心跳会复位这个计时器。
    let idleTimer: number | undefined;
    try {
      const snapshot = prepareProject ? prepareProject() : project;
      const streamEvents: AgentTraceEvent[] = [];
      setLiveStream({ events: [], text: "" });
      streamAbortRef.current?.abort();
      const controller = new AbortController();
      streamAbortRef.current = controller;
      const armIdleWatchdog = () => {
        if (idleTimer !== undefined) window.clearTimeout(idleTimer);
        idleTimer = window.setTimeout(() => {
          if (controller.signal.aborted) return;
          controller.abort();
          setBusy(false);
          setThinking("");
          setError(
            "连接已 90 秒没有任何数据（连心跳都没有）：请检查网络与后端进程是否正常，然后重试。"
          );
        }, 90_000);
      };
      armIdleWatchdog();
      const res = await runAgentStream(
        projectId,
        {
          messages: opts.apiMessages,
          chapter_id: chapterId,
          selection: selection || undefined,
          task: opts.task,
          conversation_id: convId,
          // 方案阶段：**只让后端回动作、不要落库**。有动作就在输入框上方摆出方案，
          // 作者点确认才调 /agent/apply-actions 写入（见 applyConfirmedActions）。
          // 以前这里是 true——模型一给动作就立刻写进工程，作者只在事后看到「已写入工程」。
          apply_actions: false,
          resume: opts.resume || undefined,
          // 与 UI 选中同步；勿仅依赖 DB（避免 PUT 未完成时本轮漏注入）
          lens_ids: activeLensIds,
          // 作者按需摘掉的资料块（空数组 = 不带这个字段也没关系）
          exclude_sections: excluded.length ? excluded : undefined,
          attachments: opts.resume
            ? undefined
            : pendingAttach.map((a) => ({
                filename: a.filename,
                text: a.text,
                id: a.id,
              })),
        },
        (evt) => {
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
        controller.signal,
        // 心跳也复位看门狗：模型在思考 ≠ 连接断了
        armIdleWatchdog
      );

      const actions = res.actions ?? [];
      // 方案阶段不落库：后端这次一定回 applied=false（除非它自己改了，那也要按动作处理）。
      const applied = res.applied && !!res.project;
      const hasProposal = !applied && actions.length > 0;

      if (applied && res.project) {
        undoStack.current = [
          ...undoStack.current,
          { label: describeActions(actions, copy), project: snapshot },
        ].slice(-20);
        setUndoCount(undoStack.current.length);
        onProjectChange(res.project);
      }
      if (hasProposal) {
        // 模型想改工程 → 摆方案，不写。写入只发生在作者点「确认写入」时。
        setPendingPlan({
          kind: "chat_actions",
          title: `写入工程 · 待确认（${actions.length} 项）`,
          // 带正文的动作把正文开头也摆出来：不然点确认等于盲签（见 planActionLines）
          lines: planActionLines(actions, copy),
          note: "确认前不会改动工程；确认后才写入，且可用「撤回编辑」回滚。",
          confirmLabel: "确认写入",
          actions,
          conversationId: convId,
        });
        setLastContext(`待确认方案 · 写入工程（${actions.length} 项）`);
      }

      const meta = res.context_meta;
      const taskName = meta?.task ? (TASK_LABEL[meta.task] ?? meta.task) : "";
      const resultBit = applied
        ? "已写入工程"
        : hasProposal
          ? "待确认写入"
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
      const gateShort =
        meta?.writeGate && meta.writeGate.passed === false
          ? meta.writeGate.markHints?.length
            ? "写后闸⚠可标记改"
            : "写后闸⚠"
          : meta?.writeGate &&
              ((meta.writeGate.warnings?.length ?? 0) > 0 ||
                (meta.writeGate.markHints?.length ?? 0) > 0)
            ? meta.writeGate.markHints?.length
              ? "写后闸⚠可标记改"
              : "写后闸⚠"
            : meta?.writeGate?.passed
              ? "写后闸过"
              : "";
      const prefetchShort =
        typeof meta?.retrievePrefetch?.callCount === "number" &&
        meta.retrievePrefetch.callCount > 0
          ? `预取×${meta.retrievePrefetch.callCount}`
          : "";
      const lensShort =
        Array.isArray(meta?.lensIds) && meta.lensIds.length
          ? `视角×${meta.lensIds.length}`
          : "";
      // 透明性：本次注入了哪些上下文。
      // 用后端给的结构化清单（`budgetReport.includedSections`），不再用正则去猜
      // `included` 里的中文串——那种写法每加一个资料块都得同步改正则，漏了就不显示。
      const refShort = includedSummary(meta?.budgetReport);
      const usage = contextUsage(meta);
      const evidenceRows = Array.isArray(meta?.includedDetails)
        ? meta.includedDetails
            .filter((d) => d && (d.label || d.preview))
            .map((d) => ({
              label: String(d.label ?? ""),
              preview: String(d.preview ?? ""),
            }))
        : [];
      setLastContext(
        [
          taskName,
          resultBit,
          craftShort,
          reviewShort,
          gateShort,
          prefetchShort,
          lensShort,
          refShort,
        ]
          .filter(Boolean)
          .join(" · ")
      );
      // 同一份信息的折叠态：只留"改变了这次行为"的短标签，清单类压成项数。
      // 告警（被裁 / 写后闸未过 / 主动摘掉资料）在折叠态也出现——它们要作者当场看见。
      setLastContextCompact(
        compactRunInfo({
          taskName,
          resultBit,
          craftShort,
          reviewShort,
          gateShort,
          prefetchShort,
          lensShort,
          refCount: meta?.budgetReport?.includedSections?.length ?? 0,
          contextText: usage.text,
          contextTruncated: usage.truncated,
          contextNearLimit: usage.nearLimit,
          evidenceCount: evidenceRows.length,
          excludedCount: excluded.length,
        })
      );
      // 「证明它记得」：把这次真正读到的资料摆出来（可展开看摘录）
      // 用的是谁的钱：免费档下提示"长任务建议配 Key"（长任务最吃模型能力，也最容易撞限流）
      setCredentialsMode(
        typeof meta?.credentialsMode === "string" ? meta.credentialsMode : ""
      );
      setEvidence(evidenceRows);
      // 这次它读了多少、够不够、有没有被裁（作者据此判断"是不是它没看到前情"）
      setContextInfo(usage);
      setBudgetInfo(budgetNotice(meta?.budgetReport));

      const warnings = res.warnings ?? [];
      const noteUndo = applied
        ? `可用「撤回编辑」回滚（当前对话内 ${undoStack.current.length} 步）`
        : "";
      // AI 提议的设定条目/关系/时间线不会直接落地：明确告诉作者去哪儿点确认，
      // 否则作者会以为"它说整理好了"其实什么都没进设定库。
      const proposed = actions.some((a) => String(a.op || "").startsWith("propose_"));
      const markHints = Array.isArray(meta?.writeGate?.markHints)
        ? meta.writeGate.markHints.filter((h) => h && h.quote)
        : [];
      setGateMarkHints(markHints);
      const markFoot =
        markHints.length > 0
          ? `写后闸失败段可用「标记批改」只改这些（不必整章回炉）：\n${markHints
              .slice(0, 3)
              .map(
                (h, i) =>
                  `${i + 1}. 「${String(h.quote).slice(0, 48)}」— ${h.reason || h.instruction || ""}`
              )
              .join("\n")}`
          : "";
      const foot = [
        applied ? `已落地：${describeActions(actions, copy)}` : "",
        hasProposal
          ? `方案（未写入）：${describeActions(actions, copy)}\n` +
            "确认前工程没有改动——点输入框上方方案卡片的「确认写入」才落地，不想要就点「放弃」。"
          : "",
        proposed
          ? "上面的「提议」都放进了「项目 → 结构分析 → 待审列表」，你逐条勾选接受后才会写进工程（AI 不会直接改设定库）"
          : "",
        warnings.length ? `未执行：${warnings.join("；")}` : "",
        markFoot,
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
      // 「新增了章节 → 焦点跳过去」放在确认写入那一步做（applyConfirmedActions）：
      // 方案阶段工程还没变，这时候跳聚焦会跳到一个还不存在的章节上。
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
      if (idleTimer !== undefined) window.clearTimeout(idleTimer);
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

  /** 当前章标题（方案卡片上要写清"动的是哪一章"）。 */
  function currentChapterTitle(): string | undefined {
    return (project.chapters || []).find((c) => c.id === chapterId)?.title;
  }

  /**
   * 「写入设定页」的**唯一入口**：自然语言意图与附件区那个捷径按钮都走它。
   *
   * 为什么按钮也要过闸（线上实测）：附件区那个按钮以前点了就直接写。作者附上
   * 「第一章_改写稿.docx」，手一滑点到它，正文就被当成资料写进了世界观/背景/大纲/主题/备忘
   * 与角色卡——数据库里那次会话是"开场白 + 一条【写入设定页】"，没有任何人打过这句话。
   * 当时判断"点击本身就是确认"，但按钮就贴在输入框上方，误触的代价却是一次真实写入。
   * 现在按钮与说话一样：先出方案，点了确认才写。
   */
  function proposeSettingsIngest(ask?: string) {
    const attached = attachments;
    if (!attached.length) {
      setError("要写入设定请先附上资料文件，再说一次即可");
      return;
    }
    const preview = planForSettingsIngest(
      attached.map((a) => ({ filename: a.filename, chars: a.chars ?? a.text.length }))
    );
    proposePlan({
      kind: "settings_ingest",
      ...preview,
      lines: [quoteAsk(ask || "点「写入设定页」捷径"), ...preview.lines],
      confirmLabel: "确认写入设定页",
      // 作者的这句话要跟着方案走：确认后由 ingestSettingsFromAttachments 记进对话记录
      instruction: ask,
    });
  }

  /** 「整理关系/时间线」的唯一入口：同样先出方案（这条也会改工程：候选进待审列表）。 */
  function proposeFactsScan(note?: string) {
    const preview = planForFactsScan(
      attachments.map((a) => ({
        filename: a.filename,
        chars: a.chars ?? a.text.length,
      })),
      {
        chapterTitle: currentChapterTitle(),
        full: /全文|整本|全扫|full/i.test(note || ""),
      }
    );
    proposePlan({
      kind: "facts_scan",
      ...preview,
      lines: [quoteAsk(note || "点「整理关系/时间线」捷径"), ...preview.lines],
      confirmLabel: "确认开始扫描",
      instruction: note,
    });
  }

  /**
   * 摆出方案，等作者点确认。
   *
   * 这一步**什么都不写**：不动工程、也不发写请求。方案卡片挂在输入框上方，
   * 作者点「确认」才落到对应流程（见 confirmPendingPlan）。这是"先给方案再确认才写"的闸。
   */
  function proposePlan(plan: PendingPlan) {
    setError("");
    setPendingPlan(plan);
    setLastContext(`待确认方案 · ${plan.title.replace(" · 待确认", "")}`);
  }

  /** 确认方案：按类别跑原来那条流程——写入只发生在这一步。 */
  async function confirmPendingPlan() {
    const plan = pendingPlan;
    if (!plan || busy) return;
    setPendingPlan(null);
    switch (plan.kind) {
      case "chat_actions":
        await applyConfirmedActions(plan);
        return;
      case "settings_ingest":
        await ingestSettingsFromAttachments(plan.instruction);
        return;
      case "facts_scan":
        await runFactsScanFlow(plan.instruction);
        return;
      case "pipeline":
        await runPipelineFlow(plan.instruction || "");
        return;
      case "finalize":
        await runQualityFinalize(plan.instruction);
        return;
      case "ledger":
        await runLedgerDigest(plan.instruction);
        return;
    }
  }

  /** 放弃方案：一个字都不写，并把"工程没有改动"说清楚。 */
  function cancelPendingPlan() {
    const plan = pendingPlan;
    if (!plan) return;
    setPendingPlan(null);
    const content = `好，这次不写。「${plan.title.replace(" · 待确认", "")}」的方案已丢弃，工程没有做任何改动。`;
    const next = [
      ...messagesRef.current,
      { role: "assistant" as const, content },
    ].slice(-120);
    setMessages(next);
    messagesRef.current = next;
    setLastContext("方案已放弃 · 工程未改动");
    if (conversationId) {
      void putAgentConversation(projectId, conversationId, { messages: next }).catch(
        () => undefined
      );
    }
  }

  /** 确认落库：把方案里的动作发给 /agent/apply-actions（与后端同一条写入路径）。 */
  async function applyConfirmedActions(plan: PendingPlan) {
    const actions = plan.actions || [];
    const convId = plan.conversationId || conversationId;
    if (!actions.length || !convId) return;
    const snapshot = prepareProject ? prepareProject() : project;
    setBusy(true);
    setError("");
    setThinking("正在按方案写入工程…");
    try {
      const res = await applyAgentActions(projectId, {
        actions,
        chapter_id: chapterId,
        conversation_id: convId,
      });
      undoStack.current = [
        ...undoStack.current,
        { label: describeActions(actions, copy), project: snapshot },
      ].slice(-20);
      setUndoCount(undoStack.current.length);
      if (res.project) onProjectChange(res.project);
      const done = (res.applied || []).join("；") || describeActions(actions, copy);
      const skipped = (res.skipped || []).length
        ? `\n未执行：${res.skipped.join("；")}`
        : "";
      const content =
        `${res.message}\n\n已落地：${done}${skipped}` +
        `\n可用「撤回编辑」回滚（当前对话内 ${undoStack.current.length} 步）`;
      const next = [
        ...messagesRef.current,
        { role: "assistant" as const, content },
      ].slice(-120);
      setMessages(next);
      messagesRef.current = next;
      await putAgentConversation(projectId, convId, {
        messages: next,
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
      if (actions.some((a) => a.op === "add_chapter") && res.project) {
        const last = res.project.chapters[res.project.chapters.length - 1];
        if (last) onChapterFocus?.(last.id);
      }
      setLastContext(`方案已确认 · ${done}`);
    } catch (e) {
      // 写入失败不要把方案弄丢：作者可以再点一次确认，或点放弃
      setError(e instanceof Error ? e.message : "写入失败");
      setPendingPlan(plan);
    } finally {
      setBusy(false);
      setThinking("");
    }
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
    const chapterTitle = currentChapterTitle();

    if (intent.kind === "pipeline") {
      // 自动写作会烧好几轮模型、还会写本章：先说清"跑什么、动哪一章"，确认后才开跑
      const prefs = getHarnessPrefs();
      proposePlan({
        kind: "pipeline",
        ...planForPipeline(intent.note || trimmed, {
          chapterTitle,
          maxReviseRounds: prefs.maxReviseRounds ?? 2,
          voiceCheck: prefs.voiceCheck !== false,
        }),
        confirmLabel: "确认开跑",
        instruction: intent.note || trimmed,
      });
      return;
    }
    if (intent.kind === "write_to_script") {
      await runWriteChannel(userVisible);
      return;
    }
    if (intent.kind === "chapter_lock_name") {
      const name = intent.lockName || "";
      if (name && chapterId) {
        setChapterRevisePrefs(projectId, chapterId, { lockedNames: [name] });
        const userMsg: AgentChatMessage = { role: "user", content: userVisible };
        const assistantMsg: AgentChatMessage = {
          role: "assistant",
          content: `好，本章会尽量别动「${name}」。下次改稿会带上这条偏好。`,
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
      });
      return;
    }
    if (intent.kind === "revise_pick") {
      // 显式要求"选个方向"：这是打开方向面板的唯一入口（平时改章不再弹窗）
      revisePendingArgs.current = { note: intent.note || trimmed };
      setReviseModeOpen(true);
      return;
    }
    if (intent.kind === "chapter_revise") {
      // 只传识别出的方向：要不要用固定方向由 resolveReviseMode 一处决定
      await runChapterReviseFlow(intent.note || trimmed, { mode: intent.mode });
      return;
    }
    if (intent.kind === "settings_ingest") {
      if (!pendingAttach.length) {
        setError("要写入设定请先附上资料文件，再说一次即可");
        return;
      }
      proposeSettingsIngest(userVisible);
      return;
    }
    if (intent.kind === "facts_scan") {
      proposeFactsScan(intent.note || trimmed);
      return;
    }
    if (intent.kind === "style_lint") {
      // 只读：体检不改稿，不需要过闸
      await runStyleLint(userVisible);
      return;
    }
    if (intent.kind === "finalize") {
      proposePlan({
        kind: "finalize",
        ...planForFinalize({ chapterTitle }),
        confirmLabel: "确认定稿",
        instruction: userVisible,
      });
      return;
    }
    if (intent.kind === "ledger_digest") {
      proposePlan({
        kind: "ledger",
        ...planForLedgerDigest({ chapterTitle }),
        confirmLabel: "确认更新账本",
        instruction: userVisible,
      });
      return;
    }
    if (intent.kind === "brainstorm") {
      await runBrainstormFlow(intent.note || "");
      return;
    }
    if (intent.kind === "list_mentors") {
      await runListMentors(userVisible);
      return;
    }

    let outbound = userVisible;
    const runTask = task;
    if (intent.kind === "critique_only") {
      outbound = `${userVisible}\n\n（本轮只做文字审稿，不要直接改动正文：把完整意见写进回复；除非用户明确说「写入」，否则不要修改章节内容。）`;
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
      task: runTask,
      attachments: pendingAttach,
    });
  }

  /**
   * 写作通道：走 writer 条件流式产出正文**草稿**，拿到后打开既有的对照面板。
   *
   * 为什么不再让聊天那条路写正文（线上实测）：聊天是审阅条件（JSON 协议 + 工具 + 规则块），
   * 同一模型、同一份设计书下会退化成"把设计书抄成骨架"（1141 字，选项留成占位符、
   * 把作者的注释当旁白），而 writer 条件的成稿是 2124 字。且写作不需要 JSON，
   * 思考档（deepseek-flash-think）因此不再被 JSON 模式排除在外。
   *
   * 闸没有变：这条通道**一个字都不写工程**，草稿进对照面板，作者确认后才 apply
   * （可撤回），不想要就丢弃。
   */
  async function runWriteChannel(instruction: string) {
    if (busy || !conversationId) return;
    const ask = instruction.trim() || "请按设定与已有内容写一段可上演的正文";
    const withUser = [
      ...messagesRef.current,
      {
        role: "user" as const,
        content: flowUserMessage("【写正文】走写作条件产出草稿（未写入）。", ask),
      },
    ].slice(-120);
    setMessages(withUser);
    messagesRef.current = withUser;
    setError("");
    setBusy(true);
    setThinking("正在按写作条件写…");
    setLastContext("写作通道 · 生成草稿（未写入）");
    let live = "";
    try {
      streamAbortRef.current?.abort();
      const controller = new AbortController();
      streamAbortRef.current = controller;
      const done = await agentWriteStream(
        projectId,
        {
          instruction: ask,
          chapter_id: chapterId,
          selection: selection || undefined,
          conversation_id: conversationId,
        },
        (evt) => {
          if (evt.type === "token") {
            live += evt.delta;
            setThinking(`正在按写作条件写…（${live.length} 字）`);
          }
        },
        controller.signal,
        () => undefined
      );
      const draft = (done.content || "").trim();
      if (!draft) {
        throw new Error("写作通道没有返回正文，请重试");
      }
      const targetId = done.chapterId || chapterId;
      setPendingRevise({
        chapterId: targetId,
        revisedText: draft,
        originalText: (done.sourceText || "").trim(),
        chapterTitle: done.chapterTitle,
        savedAt: Date.now(),
      });
      setReviseReviewOpen(true);
      const next = [
        ...messagesRef.current,
        {
          role: "assistant" as const,
          content:
            `草稿写好了（${draft.length} 字，模型 ${done.model || "未知"}），**还没有写进正文**。` +
            "已打开左右对照：逐段挑「改稿 / 原文」，满意再点「写入」；不想要就点「放弃」，正文保持原样。",
        },
      ].slice(-120);
      setMessages(next);
      messagesRef.current = next;
      setLastContext("写作通道 · 草稿待确认");
      await putAgentConversation(projectId, conversationId, {
        messages: next,
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
      void refreshList();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "写作通道失败";
      if (
        msg === "请求已取消" ||
        streamAbortRef.current?.signal.aborted ||
        (e instanceof Error && e.name === "AbortError")
      ) {
        return;
      }
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

  async function runListMentors(ask?: string) {
    if (busy || !conversationId) return;
    setError("");
    setThinking("读取写作导师配置…");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      {
        role: "user",
        content: flowUserMessage("【写作导师】请列出当前启用的写作导师。", ask),
      },
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
        `这是**一份完整的轻小说 / 视觉小说文学编辑方法论**（可演对白、钩子、类型热度），无需切换角色。\n` +
        `你作品里定的硬规则优先于导师建议；导师只提供写法判断。`;
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
        setLastContext("思维透镜 · 未启用（通用文学编辑底盘）");
      } else {
        const names = (res.active || []).map((p) => p.name).join("、");
        // 说清"是谁在回答、借了谁的视角"：回答本身始终来自责编，
        // 透镜只是参考视角（旧文案写「对话对象 · 村上春树…」会让人以为在跟作家本人对话）。
        setLastContext(`思维透镜 · ${names || next.join(",")}（责编借其视角，非扮演）`);
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
      setError(
        "头脑风暴需要至少 2 位作家参加。已为你打开选人面板：请勾选 2 位以上，再开始头脑风暴。"
      );
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
      // 作业化：头脑风暴是两轮串行的模型调用，同步等待会把预算逼到 10 分钟级。
      // 这里只发起，进度与结果走作业通道（与自动写作同一套）。
      const started = await startBrainstormJob(projectId, {
        question: topic,
        lens_ids: activeLensIds,
        chapter_id: chapterId,
        selection: selection || undefined,
        draft: (draft || "").trim() || undefined,
      });
      if (!started.jobId) throw new Error("头脑风暴启动失败");
      const job = await waitProjectJob(projectId, started.jobId, {
        onTick: (j) => {
          const pct = Math.round((j.progress ?? 0) * 100);
          setThinking(
            `头脑风暴进行中（${j.stage || "处理中"}）· ${pct}%${
              j.message ? ` — ${j.message}` : ""
            }`
          );
        },
      });
      if (job.status === "error") {
        throw new Error(job.error || job.message || "头脑风暴失败");
      }
      const data = (job.result ?? {}) as unknown as BrainstormResult;
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

  async function runStyleLint(ask?: string) {
    if (busy || !conversationId) return;
    const text = (draft || "").trim();
    if (!text) {
      setError("文风体检需要脚本区有正文");
      return;
    }
    setError("");
    setThinking("正在按你项目里定好的文风要求检查本章文字…");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      {
        role: "user",
        content: flowUserMessage("【文风体检】请检查当前章节草稿。", ask),
      },
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
      instruction.trim() || "（自动写作）请根据项目文风与已有设定，续写下一场戏。";
    setError("");
    setThinking("自动写作进行中：规划 → 起草 → 检查 → 修正…");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: `【自动写作】${userLine}` },
    ];
    setMessages(nextMessages);
    setBusy(true);
    setLastContext("自动写作 · 起草→检查→修正");
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
        setThinking("自动写作启动中…");
        streamAbortRef.current?.abort();
        controller = new AbortController();
        streamAbortRef.current = controller;
        job = await pipelineRunStream(
          projectId,
          body,
          (evt) => {
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
              setThinking(`阶段完成：${label}${ms}${extra}`);
            }
          },
          controller.signal
        );
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
          throw new Error("自动写作启动失败", { cause: e });
        }
        setThinking("自动写作已后台启动，正在等待各阶段完成…");
        job = await waitProjectJob(projectId, kicked.jobId, {
          onTick: (j) => {
            const pct = Math.round((j.progress ?? 0) * 100);
            setThinking(
              `自动写作进行中（${j.stage || "处理中"}）· ${pct}%${
                j.message ? ` — ${j.message}` : ""
              }`
            );
          },
        });
      }
      if (job.status === "error") {
        throw new Error(job.error || job.message || "自动写作失败");
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
          ? "自动写作完成 · 已写入本章"
          : data.gate?.pass
            ? "自动写作完成 · 已通过自动检查"
            : `自动写作完成，但自动检查发现 ${data.gate?.errorCount ?? "?"} 处问题，本次没有写入本章`
      );
    } catch (e) {
      if (
        (e instanceof Error && e.message === "请求已取消") ||
        streamAbortRef.current?.signal.aborted
      ) {
        return;
      }
      const msg = e instanceof Error ? e.message : "自动写作失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${msg}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function runQualityFinalize(ask?: string) {
    if (busy || !conversationId) return;
    setError("");
    setBusy(true);
    // 以前这条流程一条用户消息都不记（只记助手回复），作者那句"定稿"就没了。
    const withUser: AgentChatMessage[] = [
      ...messagesRef.current,
      {
        role: "user" as const,
        content: flowUserMessage(
          "【定稿】请跑一遍自动检查，通过后写入本章并记入账本。",
          ask
        ),
      },
    ].slice(-120);
    setMessages(withUser);
    messagesRef.current = withUser;
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
        ? `（AI 补充：事实 ${data.enrichMeta.factCount ?? 0} 条 / 状态 ${data.enrichMeta.stateCount ?? 0} 条 / 伏笔 ${data.enrichMeta.foreshadowCount ?? 0} 条）`
        : data.enrichMeta?.error
          ? `（AI 补充未成功，已用保守方式记录：${data.enrichMeta.error}）`
          : "";
      const content = ok
        ? `### 定稿完成\n\n${data.gate?.message || "已通过自动检查"}${enrichBit}\n\n已把本章新增的事实、出场状态和结尾悬念记入项目档案，供之后 AI 写作参考、尽量不前后矛盾。`
        : `### 定稿被拦下\n\n${data.gate?.message || "未通过自动检查"}\n\n${(
            data.check?.issues || []
          )
            .filter((i) => i.severity === "error")
            .slice(0, 12)
            .map((i) => `- ${i.code}：${i.message}`)
            .join("\n")}`;
      const finalMessages = [
        ...withUser,
        { role: "assistant" as const, content },
      ].slice(-120);
      setMessages(finalMessages);
      messagesRef.current = finalMessages;
      await putAgentConversation(projectId, conversationId, {
        messages: finalMessages,
        chat_memory: "",
        undo_stack: undoStack.current.slice(-20),
      }).catch(() => undefined);
      void refreshList();
      if (data.project) {
        onProjectChange(data.project);
      }
      setLastContext(
        ok
          ? "定稿完成 · 已通过自动检查 · 项目档案已更新"
          : "定稿未通过自动检查（已记入运行历史）"
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "定稿失败");
    } finally {
      setBusy(false);
    }
  }

  async function runLedgerDigest(ask?: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    // 同定稿：这条以前也只记助手回复，作者那句"更新账本"没进记录。
    const withUser: AgentChatMessage[] = [
      ...messagesRef.current,
      {
        role: "user" as const,
        content: flowUserMessage("【账本入库】请把本章要点记入项目账本。", ask),
      },
    ].slice(-120);
    setMessages(withUser);
    messagesRef.current = withUser;
    try {
      const data = await pipelineLedgerDigest(projectId, chapterId, {
        enrich: true,
      });
      onProjectChange(data.project);
      const enrichBit = data.enrichMeta?.enrich
        ? `（AI 补充：事实 ${data.enrichMeta.factCount ?? 0} 条 / 状态 ${data.enrichMeta.stateCount ?? 0} 条 / 伏笔 ${data.enrichMeta.foreshadowCount ?? 0} 条）`
        : data.enrichMeta?.error
          ? `（AI 补充未成功，已用保守方式记录：${data.enrichMeta.error}）`
          : "（保守摘要）";
      const content = `### 本章要点已记录${enrichBit}\n\n已把本章的新增事实、出场人物状态和结尾悬念存入项目档案，之后 AI 写作会参考这些记录，尽量不前后矛盾。\n\n${(
        data.agentBlock || ""
      ).slice(0, 1200)}`;
      const finalMessages = [
        ...withUser,
        { role: "assistant" as const, content },
      ].slice(-120);
      setMessages(finalMessages);
      messagesRef.current = finalMessages;
      if (conversationId) {
        await putAgentConversation(projectId, conversationId, {
          messages: finalMessages,
          chat_memory: "",
          undo_stack: undoStack.current.slice(-20),
        }).catch(() => undefined);
        void refreshList();
      }
      setLastContext(
        data.enrichMeta?.enrich
          ? "项目档案 · 已更新（含 AI 补充）"
          : "项目档案 · 章节要点已更新"
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

  async function ingestSettingsFromAttachments(ask?: string) {
    if (!attachments.length || !conversationId || busy) return;
    const pending = [...attachments];
    const snapshot = prepareProject ? prepareProject() : project;
    setError("");
    setBusy(true);
    setThinking("正在把附件结构化写入设定页…");
    setAttachments([]);
    // 作者原话必须排在前面：以前这条只记「【写入设定页】请根据附件更新故事设定与角色卡。」
    // 这一句系统套话，作者打的字全没了（线上排查就是被这一点挡住过）。
    const userMsg: AgentChatMessage = {
      role: "user",
      content: flowUserMessage(
        "【写入设定页】请根据附件更新故事设定与角色卡。",
        ask,
        attachmentLines(pending)
      ),
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
          { label: describeActions(res.actions || [], copy), project: snapshot },
        ].slice(-20);
        setUndoCount(undoStack.current.length);
        onProjectChange(res.project);
      }
      const foot = [
        res.wrote
          ? `已落地：${(res.applied || []).join("；") || describeActions(res.actions || [], copy)}`
          : "未写入工程",
        (res.skipped || []).length ? `未执行：${res.skipped.join("；")}` : "",
        res.wrote
          ? `可用「撤回编辑」回滚（当前对话内 ${undoStack.current.length} 步）· 请打开「视图 → 设定」查看`
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
      content: flowUserMessage(
        "【整理关系/时间线】请扫描事实，候选先进待审列表。",
        note,
        attachmentLines(pending)
      ),
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
          "已跑完事实扫描，候选先放进了「结构分析 → 待审列表」，需要你逐条确认后才会真正更新关系图和时间线——AI 不会直接改动。",
          s
            ? `摘要：新增候选 ${s.added}（关系 ${s.characterLinks} / 时间线 ${s.timelineEvents}）。`
            : "",
          n ? `当前待审列表约 ${n} 条。` : "本轮没有新的待审条目。",
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
    opts?: {
      /** 话里点过的方向，或作者在方向面板里点的那个。 */
      mode?: ReviseMode;
      /** 作者在方向面板里用自己的话写的改法（走「就照我说的改」）。 */
      customNote?: string;
    }
  ) {
    if (!conversationId || busy) return;
    const prefs = getChapterRevisePrefs(projectId, chapterId);
    // 不再弹窗拦人：话里点过方向就用那个，否则一律照作者的说明改（规则见 resolveReviseMode）。
    // 方向选择器改成**按需打开**——只有说「选个方向」才会进（见 revise_pick 分支）。
    const resolvedMode: ReviseMode = resolveReviseMode(opts?.mode);
    setChapterRevisePrefs(projectId, chapterId, { mode: resolvedMode });

    const pending = [...attachments];
    setError("");
    setBusy(true);
    setThinking("正在准备改稿预览…");
    setAttachments([]);
    const prefNote = prefsToNoteSuffix({ ...prefs, mode: resolvedMode });
    // 作者自己写的改法排在最前：提示词里「用户说明」是模型的**首要依据**，
    // 排在【本章偏好】之前，免得偏好里的旧话把他的新要求压下去
    const authorNote = opts?.customNote?.trim() || note?.trim() || "";
    const noteCombined = [authorNote, prefNote].filter(Boolean).join("\n");
    const userMsg: AgentChatMessage = {
      role: "user",
      content: pending.length
        ? `【改稿】${authorNote || "请改一版"}\n\n📎 ${pending
            .map((a) => `${a.filename}（${a.chars ?? a.text.length} 字）`)
            .join("、")}`
        : `【改稿】${authorNote || "请改当前章"}`,
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
        setThinking(
          "正在生成改稿预览（后台处理中，完成后会先给你对照挑选，不会直接改动正文）…"
        );
        const job = await waitProjectJob(projectId, kicked.jobId, {
          onTick: (j) => {
            const pct = Math.round((j.progress ?? 0) * 100);
            setThinking(
              `正在生成改稿预览…（已完成 ${pct}%）${j.message ? ` — ${j.message}` : ""}`
            );
          },
        });
        if (job.status === "error") {
          throw new Error(job.error || job.message || "改稿预览生成失败");
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
                  上次 AI 任务{runState.status === "interrupted" ? "中断" : "失败"}
                  {typeof runState.step === "number" &&
                  typeof runState.steps === "number"
                    ? `（已完成 ${runState.step}/${runState.steps} 步）`
                    : ""}
                  ——可以接着上次停下的地方继续，做过的部分不会重来。
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void resumeLastRun()}
                >
                  {busy ? "运行中…" : "继续上次任务"}
                </button>
              </div>
            )}
          <AgentMessagesList
            copy={copy}
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
            lastContextCompact={lastContextCompact}
            runInfoOpen={runInfoOpen}
            onToggleRunInfo={toggleRunInfo}
            error={error}
            undoCount={undoCount}
            scrollerRef={scroller}
            onOpenReviseReview={handleOpenReviseReview}
            onToggleDossier={handleToggleDossier}
            onTogglePersona={handleTogglePersona}
            onToggleHelp={handleToggleHelp}
            onUndo={() => void undoAgentEdit()}
            footer={
              /* 起手句与「先问几句」都挂在消息滚动区末尾，**不放输入框上方**：
                 底部固定区（⚙ 资料 / 输入框）的高度一变，它上方的弹出菜单就会被
                 顶到标题栏底下点不到（起手句那次已经踩过一遍）。
                 起手句点了只填不发，不替作者花模型调用。 */
              <>
                {gateMarkHints.length > 0 && onCreateMarksFromHints ? (
                  <div
                    className={styles.resumeBar}
                    role="status"
                    data-testid="gate-mark-hints"
                  >
                    <span>
                      写后闸标出 {gateMarkHints.length}{" "}
                      处可改失败段（只建标记，不自动改稿）
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      data-testid="gate-mark-one-click"
                      onClick={() => {
                        const n = onCreateMarksFromHints(gateMarkHints);
                        if (n > 0) setGateMarkHints([]);
                      }}
                    >
                      一键标记批改
                    </button>
                  </div>
                ) : null}
                {showStarters ? (
                  <div className={styles.starters} data-testid="agent-starters">
                    <span className={styles.startersHint}>想干什么？点一个：</span>
                    {STARTERS.map((s) => (
                      <button
                        key={s}
                        type="button"
                        className={styles.starterChip}
                        data-testid={`agent-starter-${STARTERS.indexOf(s)}`}
                        onClick={() => setInput(s)}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                ) : null}
                <div className={styles.preQRow}>
                  <button
                    type="button"
                    className={styles.preQBtn}
                    data-testid="agent-prequestions"
                    disabled={busy || !input.trim()}
                    title="先说清这一场的关键推进点、角色动机变化和收尾落点，再让它写"
                    onClick={() => void openPreQuestions()}
                  >
                    ❓ 先问几句
                  </button>
                  <span className={styles.preQHint}>
                    {input.trim()
                      ? "可选：先答 3 个小问题，写出来更贴你的意图"
                      : "先在上面写下你要写什么"}
                  </span>
                </div>
                {preQuestions ? (
                  <div
                    className={styles.preQCard}
                    data-testid="agent-prequestions-card"
                  >
                    <p className={styles.preQCardHead}>
                      先定这三件事（留空等于没答；不想答就点「跳过」）
                      {preQuestionsSource === "template"
                        ? "　·　模型不可用，这是通用问题"
                        : ""}
                    </p>
                    {preQuestions.map((q, i) => (
                      <label key={q} className={styles.preQItem}>
                        <span className={styles.preQText}>{q}</span>
                        <input
                          className={styles.preQInput}
                          data-testid={`agent-prequestions-input-${i}`}
                          value={preAnswers[i] ?? ""}
                          onChange={(e) =>
                            setPreAnswers((prev) => ({ ...prev, [i]: e.target.value }))
                          }
                          placeholder="一句话就行"
                        />
                      </label>
                    ))}
                    <div className={styles.preQActions}>
                      <button
                        type="button"
                        className={styles.preQPrimary}
                        data-testid="agent-prequestions-confirm"
                        disabled={busy}
                        onClick={() => void confirmPreQuestions()}
                      >
                        好了，按这些写
                      </button>
                      <button
                        type="button"
                        className={styles.preQGhost}
                        data-testid="agent-prequestions-skip"
                        disabled={busy}
                        onClick={() => {
                          setPreQuestions(null);
                          void sendText(pendingGoalRef.current);
                        }}
                      >
                        跳过，直接写
                      </button>
                    </div>
                  </div>
                ) : null}
              </>
            }
          />
          <AgentAttachList
            attachments={attachments}
            busy={busy}
            attachBusy={attachBusy}
            conversationId={conversationId}
            onRemove={(i) => setAttachments((prev) => prev.filter((_, j) => j !== i))}
            onIngest={() => proposeSettingsIngest()}
            onScan={() => proposeFactsScan("请根据附件整理关系与时间线")}
          />

          {/* 免费档提示：长任务（整章重写、长篇续写）最吃模型能力，也最容易撞限流 */}
          {credentialsMode === "shared" ? (
            <p className={styles.tierHint} data-testid="agent-tier-hint">
              当前用<b>站内免费档</b>（GLM-4-Flash · 每天有额度 · 人多会限流）。
              整章重写、长篇续写这类长任务建议到「设置 → 模型」填自己的 Key：站内支持
              GLM-5.3 / DeepSeek， 用量走你自己的账户。
            </p>
          ) : null}

          {/* 「证明它记得」：本次依据了什么，可展开看摘录——聊天永远给不了这个 */}
          {/* 上面那行「用量」先说清"读了多少、够不够、有没有被裁"：
              AI 没读到整章时会写出前后矛盾的东西，作者只会以为"它怎么忘了" */}
          {/* 这些文字是**凭据**不是每条都要读的话，所以默认收起（折叠态摘要见 statusLine 的
              「本次运行」按钮）：作者反馈过它们占满了对话区。但**告警一律不折**——
              被裁过 / 没装下的那些块照样直接可见，见下面 budgetInfo。 */}
          {runInfoOpen && contextInfo.text ? (
            <p
              className={
                contextInfo.truncated ? styles.contextWarn : styles.contextLine
              }
              data-testid="agent-context-usage"
              title={contextInfo.hint || undefined}
            >
              {contextInfo.text}
              {contextInfo.truncated ? " · 有资料没装下" : ""}
              {contextInfo.hint ? (
                <span className={styles.contextHint}>{contextInfo.hint}</span>
              ) : null}
            </p>
          ) : null}
          {/* 「这次没装下什么、怎么取回来」：每一行都能照着做，能取回的还给一个按钮 */}
          {budgetInfo.hasMissing ? (
            <details className={styles.missing} data-testid="agent-context-missing">
              <summary>
                没装下的 {budgetInfo.missing.length} 项（点开看怎么取回）
              </summary>
              <ul>
                {budgetInfo.missing.map((row, i) => (
                  <li key={`${row.label}-${i}`}>
                    <strong>{row.label}</strong>
                    {row.detail ? <em>{row.detail}</em> : null}
                    {row.action ? <span>{row.action}</span> : null}
                    {/* 一键取回：发出去的就是后端给的那句话（工具名只有后端一处真源） */}
                    {row.instruction ? (
                      <button
                        type="button"
                        className={styles.missingAction}
                        data-testid={`agent-context-retrieve-${i}`}
                        disabled={busy || !conversationId}
                        title={row.instruction}
                        onClick={() => void sendText(row.instruction!)}
                      >
                        让它取回这一块
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
              {budgetInfo.hasRetrievable ? (
                <button
                  type="button"
                  className={styles.missingAction}
                  data-testid="agent-context-retrieve-all"
                  disabled={busy || !conversationId}
                  onClick={() => void sendText(retrieveAllMessage(budgetInfo))}
                >
                  一次让它把没装下的都取回来
                </button>
              ) : null}
              {budgetInfo.byDesign.length > 0 ? (
                <p className={styles.missingNote}>
                  另有 {budgetInfo.byDesign.length} 项是**按任务省去**的（
                  {budgetInfo.byDesign.map((r) => r.label).join("、")}
                  ），这类资料对写正文没有 信息量，不是"没装下"。
                </p>
              ) : null}
            </details>
          ) : null}
          {runInfoOpen && evidence.length > 0 ? (
            <details className={styles.evidence} data-testid="agent-evidence">
              <summary>依据 {evidence.length} 项（点开看它读到的原文摘录）</summary>
              <ul>
                {evidence.map((item, i) => (
                  <li key={i}>
                    <strong>{item.label}</strong>
                    {item.preview ? <span>{item.preview}</span> : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {/* 资料开关：把"这次带哪些资料"交给作者，一眼可控（工具比裸聊差多半是因为塞太多） */}
          <div className={styles.sectionRow}>
            <button
              type="button"
              className={styles.sectionToggle}
              data-testid="agent-sections-toggle"
              onClick={() => setSectionsOpen((v) => !v)}
              title="按需决定这次要交给 AI 的资料（只影响本次会话，不改工程数据）"
            >
              ⚙ 资料
            </button>
            <span className={styles.sectionHint} data-testid="agent-sections-summary">
              {excluded.length > 0
                ? `本次不带 ${excluded.length} 项`
                : runInfoOpen
                  ? "AI 会参考你的设定与资料（点开可以少给它一些）"
                  : ""}
            </span>
            {sectionsOpen ? (
              <div className={styles.sectionMenu} data-testid="agent-sections-menu">
                <p className={styles.sectionNote}>
                  取消勾选 = 这次不交给它。塞太多无关资料反而会让它跑偏。
                </p>
                {AGENT_SECTIONS.map((s) => (
                  <label key={s.key} className={styles.sectionItem}>
                    <input
                      type="checkbox"
                      data-testid={`agent-section-${s.key}`}
                      checked={!excluded.includes(s.key)}
                      onChange={() => setExcluded((prev) => toggleSection(prev, s.key))}
                    />
                    <span>{s.label}</span>
                  </label>
                ))}
              </div>
            ) : null}
          </div>

          {/* 起手句与「先问几句」都渲染在消息滚动区末尾（见上面的 footer），
              这里不再放任何东西——底部固定区的高度必须保持稳定。 */}

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
                          : "设为本轮的参考视角"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {pendingPlan ? (
            <div className={styles.preQCard} data-testid="agent-plan-gate">
              <p className={styles.preQCardHead}>
                {pendingPlan.title}
                {"　"}确认前不会改动工程
              </p>
              <ul className={styles.planList}>
                {pendingPlan.lines.map((line, i) => (
                  <li key={`${i}-${line}`} className={styles.preQText}>
                    {line}
                  </li>
                ))}
              </ul>
              {pendingPlan.note ? (
                <p className={styles.planNote}>{pendingPlan.note}</p>
              ) : null}
              <div className={styles.preQActions}>
                <button
                  type="button"
                  className={styles.preQPrimary}
                  data-testid="agent-plan-confirm"
                  disabled={busy}
                  onClick={() => void confirmPendingPlan()}
                >
                  {pendingPlan.confirmLabel}
                </button>
                <button
                  type="button"
                  className={styles.preQGhost}
                  data-testid="agent-plan-cancel"
                  disabled={busy}
                  onClick={cancelPendingPlan}
                >
                  放弃，先不写
                </button>
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
              onPick={(mode, pickOpts) => {
                const args = revisePendingArgs.current;
                revisePendingArgs.current = null;
                setReviseModeOpen(false);
                void runChapterReviseFlow(args?.note, {
                  mode,
                  customNote: pickOpts?.customNote,
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
