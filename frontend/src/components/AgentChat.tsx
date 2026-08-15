import { useCallback, useEffect, useRef, useState } from "react";
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
  type AgentConversationSummary,
  type HarnessLintResult,
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
import type { AgentAction, AgentChatMessage, AgentTaskKind, AgentTraceEvent, VnProject } from "../types/vn";
import { AgentMessageBody } from "./AgentMarkdown";
import { ChapterReviseModePicker } from "./ChapterReviseModePicker";
import { ChapterReviseReview } from "./ChapterReviseReview";
import { useConfirm } from "./ConfirmDialog";
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

const HELP_MD = `### 责编能帮你做什么

用平常话说需求即可。**轻小说 / 视觉小说写法底盘**（可演对白、钩子、去说明书）由「通用文学编辑」在每次对话里自动生效。

### 推荐写作流程

1. **直接聊**：说清场次或卡点。  
2. **（可选）换作家眼光**：点顶部 **⇄**，选一位作家 skill 卡（可开多选做头脑风暴）。  
3. **文风体检**（可选）：扫问题不改文。  
4. **定稿**：过门禁并更新写作账本。

### 怎么说话

用平常话说即可，例如「根据附件更新设定」「帮我改这一章更有人味」「整理关系进待审」。需要改章时直接说，会出现模式选择与对照挑选弹窗。

### 卡壳时的替代

「跑流水线：……」适合没思路或要整场戏——**不是**日常必经步骤。

### 强头脑风暴

1. 点 **⇄** → 打开「多选」→ 选 2～3 位作家  
2. 填写议题，点「开始头脑风暴」，或直接说「头脑风暴：下一场怎么拆」  
3. 程序会让每位作家**各自独立调用一次模型**（互相看不见），再由责编综合分歧与三步行动  

这与「一次对话里塞多个视角」不同，是真正的分视角圆桌。

### 作家卡从哪来

内置若干公开技法蒸馏包（女娲五层格式）。也可用 [女娲.skill](https://github.com/alchaincyf/nuwa-skill) 离线蒸馏作家 → 导入工程（见仓库 \`backend/vendor/NUWA_LENS_WORKFLOW.md\`）。

冲突时：**风格硬规则 > 通用编辑 > 所选作家视角**。`;

const WELCOME_MARKER = "轻小说 / 视觉小说的写法底盘会自动带上";

const DEFAULT_WRITER = {
  id: null as string | null,
  name: "通用文学编辑",
  role: "默认 · LN/VN 责编",
  blurb:
    "日常对话自动用的编辑底盘：可演对白、信息残缺、场钩子、类型热度。写轻小说/视觉小说时无需切换作家。",
};

const WRITER_CARD_META: Record<
  string,
  { role: string; blurb: string; sort: number }
> = {
  "author-murakami": {
    role: "文学 / 氛围小说",
    blurb: "适合：疏离日常、都市孤独。擅长：留白、重复变奏、克制比喻。",
    sort: 10,
  },
  "author-higashino": {
    role: "悬疑 / 社会派",
    blurb: "适合：本格与社会派谜题。擅长：公平伏笔、误导动机、因果收束。",
    sort: 20,
  },
  "author-watari": {
    role: "轻小说 · 学园恋爱",
    blurb: "适合：别扭青春恋爱。擅长：心理防线、自欺、越界触发与毒舌距离感。",
    sort: 30,
  },
  "author-nishio": {
    role: "轻小说 · 对白密集",
    blurb: "适合：靠嘴推进的故事。擅长：口癖声纹、抬杠逻辑、定义权争夺。",
    sort: 40,
  },
  "author-kamachi": {
    role: "轻小说 · 动作信息战",
    blurb: "适合：异能/战斗快节奏。擅长：信息差、倒计时、短章甩钩。",
    sort: 50,
  },
  "author-nasu": {
    role: "视觉小说 · 规则概念",
    blurb: "适合：异能、神话、规则对决。擅长：设定可演、代价与例外、概念冲突。",
    sort: 60,
  },
  "author-maeda": {
    role: "视觉小说 · 泣きゲー",
    blurb: "适合：催泪向恋爱/亲情。擅长：长蓄力、一句决堤、静场余韵。",
    sort: 70,
  },
  "author-maruto": {
    role: "视觉小说 · 恋爱细腻",
    blurb: "适合：成人向拉扯恋爱。擅长：试探与撤回、对白缝隙、二人私密语法。",
    sort: 80,
  },
  "author-urobuchi": {
    role: "视觉小说 / 剧本 · 致郁思想剧",
    blurb: "适合：黑暗理想主义、悲剧。擅长：信念对撞、残酷有逻辑、改写立场的反转。",
    sort: 90,
  },
  "author-romeo": {
    role: "视觉小说 · 恋爱喜剧",
    blurb: "适合：聪明互怼恋爱、轻元梗。擅长：喜剧落回真心、闹中取静的告白节奏。",
    sort: 100,
  },
  "author-hayashi": {
    role: "视觉小说 · 温情学园",
    blurb: "适合：治愈学园日常、轻百合气息。擅长：相处厚度、缓坡感动、群像温度。",
    sort: 110,
  },
  "author-looseboy": {
    role: "视觉小说 · 现代恋爱",
    blurb: "适合：职场/成年女主恋爱。擅长：女主主体性、治愈兑账、亲密戏推进人物。",
    sort: 120,
  },
  "author-niijima": {
    role: "视觉小说 · 夏日群像",
    blurb: "适合：夏日青春、轻悬念群像。擅长：场所氛围、伏笔回收、谜题服务情感。",
    sort: 130,
  },
  "author-urushibara": {
    role: "视觉小说 · 实验哲学",
    blurb: "适合：前卫、猎奇思辨、互文实验。擅长：形式即主题、认知恐怖、多线命题。",
    sort: 140,
  },
  "author-kai": {
    role: "视觉小说 · 戏剧悬疑",
    blurb: "适合：成人情感剧、罪与秘密。擅长：慢收紧线索、关系被真相改写、克制对白。",
    sort: 150,
  },
};

function describeActions(actions: AgentAction[]): string {
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

function defaultWelcome(): AgentChatMessage[] {
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
function normalizeMessages(msgs: AgentChatMessage[]): AgentChatMessage[] {
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

function formatLintBlock(data: HarnessLintResult): string {
  const head = `${data.pass ? "无硬错误" : "存在硬错误"} · error ${data.errorCount} / warn ${data.warnCount} / info ${data.infoCount}`;
  if (!data.issues?.length) return `${head}\n未发现明显 AI 腔 / 社交问题。`;
  const lines = data.issues
    .slice(0, 24)
    .map((iss) => `- [${iss.severity}] ${iss.code}：${iss.message}`);
  return [head, ...lines].join("\n");
}

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
  const [conversations, setConversations] = useState<AgentConversationSummary[]>(
    []
  );
  const [conversationId, setConversationId] = useState<string | null>(null);
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
        opts?.clearChapterId ||
        pendingReviseRef.current?.chapterId ||
        chapterId;
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

  // Writing toolbar / short command: reopen对照 for a saved draft
  useEffect(() => {
    function onOpen(e: Event) {
      const detail = (e as CustomEvent<{ projectId?: string; chapterId?: string }>)
        .detail || {};
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
    }) => {
      setConversationId(conv.id);
      persistActiveId(projectId, conv.id);
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
      const prevById = Object.fromEntries(
        prev.map((c) => [c.id, c.title || "新对话"])
      );
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
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title } : c))
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
      await refreshList().catch(() => undefined);
    }
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

  async function sendText(text: string, task?: AgentTaskKind) {
    const trimmed = text.trim();
    const pendingAttach = attachments;
    if ((!trimmed && pendingAttach.length === 0) || busy || !conversationId)
      return;

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
      const draft =
        pendingRevise ||
        getChapterReviseDraft(projectId, chapterId);
      if (draft) {
        setPendingReviseState(draft);
        setReviseReviewOpen(true);
        const userMsg: AgentChatMessage = { role: "user", content: userVisible };
        const assistantMsg: AgentChatMessage = {
          role: "assistant",
          content: "已打开对照面板，逐段选「改稿」或「原文」即可。刷新后也可从写作区「改稿对照」再进。",
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
    setBusy(true);
    try {
      const snapshot = prepareProject ? prepareProject() : project;
      const apiMessages = nextMessages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-20);

      const streamEvents: AgentTraceEvent[] = [];
      setLiveStream({ events: [], text: "" });
      const res = await runAgentStream(projectId, {
        messages: apiMessages,
        chapter_id: chapterId,
        selection: selection || undefined,
        task,
        conversation_id: conversationId,
        apply_actions: true,
        // 与 UI 选中同步；勿仅依赖 DB（避免 PUT 未完成时本轮漏注入）
        lens_ids: activeLensIds,
        attachments: pendingAttach.map((a) => ({
          filename: a.filename,
          text: a.text,
          id: a.id,
        })),
      }, (evt) => {
        if (evt.type === "thought") {
          setLiveStream((p) => ({ events: p?.events ?? [], text: evt.text ?? "" }));
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
      });

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
      const taskName = meta?.task ? TASK_LABEL[meta.task] ?? meta.task : "";
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
      const lensShort = Array.isArray(meta?.lensIds) && meta.lensIds.length
        ? `视角×${meta.lensIds.length}`
        : "";
      setLastContext(
        [taskName, resultBit, craftShort, reviewShort, lensShort]
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
      const finalMessages = [...nextMessages, assistantMsg];
      setMessages(finalMessages);

      await putAgentConversation(projectId, conversationId, {
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
      const msg = e instanceof Error ? e.message : "请求失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${msg}` },
      ]);
    } finally {
      setBusy(false);
      setLiveStream(null);
    }
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
      const activeNames = (data.active || [])
        .map((p) => `**${p.name}** (\`${p.id}\`)`)
        .join("、") || "（将使用默认写作导师）";
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
      let next = on
        ? activeLensIds.filter((x) => x !== id)
        : [...activeLensIds, id];
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
      const finalMessages = [
        ...nextMessages,
        { role: "assistant" as const, content },
      ];
      setMessages(finalMessages);
      setLastContext(
        `头脑风暴完成 · ${data.okCount}/${data.authorCount} 视角`
      );
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
      const finalMessages = [
        ...nextMessages,
        { role: "assistant" as const, content },
      ];
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

  function formatPipelineResult(data: PipelineRunResult): string {
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

  async function runPipelineFlow(instruction: string) {
    if (busy || !conversationId) return;
    const userLine =
      instruction.trim() ||
      "请按风格 Skill 与项目硬锚，续写下一场可上演戏。";
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
      const kicked = await pipelineRun(projectId, {
        instruction: userLine,
        draft: (draft || "").trim() || undefined,
        selection: selection || undefined,
        chapter_id: chapterId,
        apply_to_chapter: true,
        max_revise_rounds: prefs.maxReviseRounds ?? 2,
        voice_check: prefs.voiceCheck !== false,
        voice_hard: Boolean(prefs.voiceHard),
        async_mode: true,
      });
      let data: PipelineRunResult;
      if ("jobId" in kicked && kicked.jobId) {
        setThinking("流水线已后台启动，正在等待各阶段…");
        const job = await waitProjectJob(projectId, kicked.jobId, {
          onTick: (j) => {
            const pct = Math.round((j.progress ?? 0) * 100);
            setThinking(
              `流水线 ${j.stage || "运行中"} · ${pct}%${
                j.message ? ` — ${j.message}` : ""
              }`
            );
          },
        });
        if (job.status === "error") {
          throw new Error(job.error || job.message || "流水线任务失败");
        }
        data = (job.result ?? {}) as unknown as PipelineRunResult;
      } else {
        data = kicked as PipelineRunResult;
      }
      const content = formatPipelineResult(data);
      const finalMessages = [
        ...nextMessages,
        { role: "assistant" as const, content },
      ];
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
        data.enrichMeta?.enrich
          ? "账本 · LLM 充实已更新"
          : "账本 · 章节摘要已更新"
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
    const paste = pending.map((a) => a.text).filter(Boolean).join("\n\n");
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
    const resolvedMode: ReviseMode =
      opts?.mode || prefs.mode || "human_warmth";
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
            typeof res.chapterTitle === "string"
              ? res.chapterTitle
              : ch?.title,
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

  const writerCards = [
    DEFAULT_WRITER,
    ...[...lensCatalog]
      .sort((a, b) => (WRITER_CARD_META[a.id]?.sort ?? 99) - (WRITER_CARD_META[b.id]?.sort ?? 99))
      .map((p) => ({
        id: p.id as string | null,
        name: p.name,
        role: WRITER_CARD_META[p.id]?.role || "作家 · 思维包",
        blurb:
          WRITER_CARD_META[p.id]?.blurb ||
          "公开技法启发向参谋视角（非本人，禁止仿写原文）。",
      })),
  ];

  const detailCard =
    writerCards.find((c) => (c.id ?? "__default__") === detailKey) || null;

  const partyCards = activeLensIds
    .map((id) => writerCards.find((c) => c.id === id))
    .filter(Boolean) as typeof writerCards;

  const showEmptyStage =
    !loadingConv && messages.length <= 1 && !busy && !input.trim();
  const turnCount = messages.filter((m) => m.role === "user").length;

  return (
    <div
      className={`${compact ? styles.shellCompact : styles.shell} ${styles.gameShell}`}
      style={hidden ? { display: "none" } : undefined}
      aria-hidden={hidden || undefined}
    >
      <div className={styles.stage} ref={splitRef}>
        {dossierOpen ? (
          <button
            type="button"
            className={styles.dossierScrim}
            aria-label="关闭卷宗"
            onClick={() => setDossierOpen(false)}
          />
        ) : null}

        <aside
          className={`${styles.sidebar} ${dossierOpen ? styles.sidebarOpen : ""}`}
          style={{ width: sidebarW }}
          id="agent-dossier"
        >
          <div className={styles.sideStamp} aria-hidden>
            <span>卷</span>
            <em>DOSSIER</em>
          </div>
          <div className={styles.sideHead}>
            <span className={styles.sideTitle}>卷宗</span>
            <div className={styles.sideHeadActions}>
              <button
                type="button"
                className={styles.sideNew}
                disabled={busy || loadingConv}
                onClick={() => void handleNewConversation()}
                title="新建对话"
              >
                新建
              </button>
              <button
                type="button"
                className={styles.sideClose}
                onClick={() => setDossierOpen(false)}
              >
                收起
              </button>
            </div>
          </div>
          <div className={styles.convList} role="listbox" aria-label="对话列表">
            {conversations.map((c, idx) => {
              const active = c.id === conversationId;
              const num = String(idx + 1).padStart(2, "0");
              return (
                <div
                  key={c.id}
                  role="option"
                  aria-selected={active}
                  className={
                    active
                      ? `${styles.convItem} ${styles.convItemActive}`
                      : styles.convItem
                  }
                  onClick={() => {
                    if (!active) void switchConversation(c.id);
                    setDossierOpen(false);
                  }}
                >
                  <span className={styles.convIdx} aria-hidden>
                    {num}
                  </span>
                  <input
                    className={styles.convTitleInput}
                    value={titleDrafts[c.id] ?? c.title ?? "新对话"}
                    disabled={busy || loadingConv}
                    ref={(el) => {
                      titleInputRefs.current[c.id] = el;
                    }}
                    onClick={(e) => e.stopPropagation()}
                    onFocus={() => {
                      if (!active) void switchConversation(c.id);
                    }}
                    onChange={(e) => {
                      const v = e.target.value;
                      setTitleDrafts((prev) => ({ ...prev, [c.id]: v }));
                      scheduleRename(c.id, v);
                    }}
                    onBlur={(e) => {
                      const t = renameTimer.current[c.id];
                      if (t) window.clearTimeout(t);
                      void commitRename(c.id, e.target.value);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        (e.target as HTMLInputElement).blur();
                      }
                      e.stopPropagation();
                    }}
                    aria-label="对话名称"
                  />
                  <button
                    type="button"
                    className={styles.convDel}
                    disabled={busy || loadingConv}
                    title="删除对话"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleDeleteConversation(c.id);
                    }}
                  >
                    ×
                  </button>
                </div>
              );
            })}
            {!loadingConv && conversations.length === 0 ? (
              <p className={styles.sideEmpty}>暂无对话</p>
            ) : null}
          </div>
          {dossierOpen ? (
            <div
              className={styles.dossierResize}
              role="separator"
              aria-orientation="vertical"
              aria-label="拖动调整卷宗宽度"
              aria-valuenow={sidebarW}
              onPointerDown={(e) => {
                e.preventDefault();
                resizing.current = true;
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";
                try {
                  (e.currentTarget as HTMLElement).setPointerCapture(
                    e.pointerId
                  );
                } catch {
                  /* ignore */
                }
              }}
            />
          ) : null}
        </aside>

        <div className={styles.main}>
          <div className={styles.cornerBar}>
            <button
              type="button"
              className={styles.dossierTab}
              aria-expanded={dossierOpen}
              aria-controls="agent-dossier"
              title="打开卷宗"
              onClick={() => {
                setPersonaOpen(false);
                setHelpOpen(false);
                setDossierOpen((v) => !v);
              }}
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
                onClick={() => {
                  setDossierOpen(false);
                  setHelpOpen(false);
                  setPersonaOpen((v) => !v);
                }}
              >
                ⇄
              </button>
              <button
                type="button"
                className={styles.hudBtn}
                aria-expanded={helpOpen}
                aria-label="功能说明与推荐流程"
                title="功能说明与推荐流程"
                onClick={() => {
                  setDossierOpen(false);
                  setPersonaOpen(false);
                  setHelpOpen((v) => !v);
                }}
              >
                !
              </button>
            </div>
          </div>

          <div
            className={styles.messages}
            ref={scroller}
            onWheel={(e) => e.stopPropagation()}
          >
            {showEmptyStage ? (
              <div className={styles.emptyStage}>
                <div className={styles.emptyMark} aria-hidden>
                  <span className={styles.emptySlash} />
                  <span className={styles.emptyShard} />
                </div>
                <p className={styles.emptyHint}>
                  点 ⇄ 选参谋，或直接开写
                </p>
              </div>
            ) : null}
            {messages.map((m, i) => {
              const reviseAction =
                m.role === "assistant" &&
                m.action?.type === "open_revise_review"
                  ? m.action
                  : null;
              const reviseDraftAlive = reviseAction
                ? Boolean(
                    getChapterReviseDraft(projectId, reviseAction.chapterId)
                  )
                : false;
              return (
              <div
                key={`${i}-${m.role}`}
                className={m.role === "user" ? styles.user : styles.bot}
              >
                <div className={styles.msgHead}>
                  {m.role === "assistant" ? (
                    <WriterPortrait
                      lensId={activeLensIds[0] || null}
                      size="xs"
                    />
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
                      onClick={() => {
                        const draft = getChapterReviseDraft(
                          projectId,
                          reviseAction.chapterId
                        );
                        if (!draft) {
                          setError("改稿预览已写入或已丢弃，可再说「帮我改这一章」。");
                          return;
                        }
                        setPendingReviseState(draft);
                        setReviseReviewOpen(true);
                        setError("");
                      }}
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
            {busy && liveStream && (liveStream.events.length > 0 || liveStream.text) && (
              <div className={styles.liveStream}>
                {liveStream.events.length > 0 && (
                  <AgentTracePanel events={liveStream.events} />
                )}
                {liveStream.text && <p className={styles.liveText}>{liveStream.text}</p>}
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

          {attachments.length > 0 ? (
            <>
              <ul className={styles.attachList} aria-label="待发送附件">
                {attachments.map((a, i) => (
                  <li key={`${a.filename}-${i}`}>
                    <span title={a.warning || undefined}>
                      {a.filename}
                      <em>{a.chars ?? a.text.length} 字</em>
                    </span>
                    <button
                      type="button"
                      disabled={busy || attachBusy}
                      onClick={() =>
                        setAttachments((prev) => prev.filter((_, j) => j !== i))
                      }
                    >
                      移除
                    </button>
                  </li>
                ))}
              </ul>
              <div className={styles.attachActions}>
                <button
                  type="button"
                  className={styles.attachActionBtn}
                  disabled={busy || attachBusy || !conversationId}
                  title="捷径：等价于说「根据附件更新设定」"
                  onClick={() => void ingestSettingsFromAttachments()}
                >
                  写入设定页
                </button>
                <button
                  type="button"
                  className={styles.attachActionBtn}
                  disabled={busy || attachBusy || !conversationId}
                  title="捷径：等价于说「整理关系进待审」"
                  onClick={() => void runFactsScanFlow("请根据附件整理关系与时间线")}
                >
                  整理关系/时间线
                </button>
              </div>
            </>
          ) : null}

          <div className={styles.composer}>
            <textarea
              rows={compact ? 2 : 3}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="用平常话说：改这一章、再润、别动某某、整理关系…"
              disabled={busy || loadingConv || !conversationId}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className={styles.sendCluster}>
              <span className={styles.turnBadge} title="本对话用户发言次数">
                回合 {turnCount}
              </span>
              <input
                ref={fileInputRef}
                type="file"
                className={styles.fileInput}
                accept=".txt,.md,.markdown,.json,.csv,.docx,.rpy,text/plain,text/markdown,application/json"
                multiple
                disabled={busy || attachBusy || loadingConv || !conversationId}
                onChange={(e) => void onPickFiles(e.target.files)}
              />
              <button
                type="button"
                className={styles.attachBtn}
                disabled={busy || attachBusy || loadingConv || !conversationId}
                title="上传参考资料（txt / md / docx / json / csv / rpy）"
                onClick={() => fileInputRef.current?.click()}
              >
                {attachBusy ? "…" : "附件"}
              </button>
              <button
                type="button"
                className={styles.sendBtn}
                disabled={
                  busy ||
                  loadingConv ||
                  !conversationId ||
                  (!input.trim() && attachments.length === 0)
                }
                onClick={() => void send()}
              >
                {busy ? "…" : "发送"}
              </button>
            </div>
          </div>

          {personaOpen ? (
            <div className={styles.stageOverlay} role="dialog" aria-modal="true">
              <header className={styles.overlayHead}>
                <div>
                  <p className={styles.overlayIdx}>PARTY</p>
                  <h3 className={styles.overlayTitle}>参谋档案</h3>
                </div>
                <button
                  type="button"
                  className={styles.hudBtn}
                  onClick={() => setPersonaOpen(false)}
                >
                  关闭
                </button>
              </header>
              <p className={styles.personaPanelLead}>
                点开档案选用作家参谋。默认是通用文学编辑；多选可组队头脑风暴。
              </p>
              <label className={styles.multiToggle}>
                <input
                  type="checkbox"
                  checked={multiSelect}
                  onChange={(e) => setMultiSelect(e.target.checked)}
                />
                多选（组队头脑风暴）
              </label>
              {multiSelect || activeLensIds.length >= 2 ? (
                <div className={styles.partyStage}>
                  <div className={styles.partySeats}>
                    <div className={styles.partySeat}>
                      <WriterPortrait lensId={null} size="sm" />
                      <span className={styles.partySeatName}>责编主持</span>
                    </div>
                    {partyCards.map((c) => (
                      <div key={c.id as string} className={styles.partySeat}>
                        <WriterPortrait lensId={c.id} size="sm" selected />
                        <span className={styles.partySeatName}>{c.name}</span>
                      </div>
                    ))}
                    {Array.from({
                      length: Math.max(0, 2 - partyCards.length),
                    }).map((_, i) => (
                      <div
                        key={`empty-${i}`}
                        className={`${styles.partySeat} ${styles.partySeatEmpty}`}
                      >
                        <span className={styles.partyEmptyMark}>?</span>
                        <span className={styles.partySeatName}>空席</span>
                      </div>
                    ))}
                  </div>
                  <div className={styles.brainstormBox}>
                    <input
                      className={styles.brainstormInput}
                      value={brainstormTopic}
                      onChange={(e) => setBrainstormTopic(e.target.value)}
                      placeholder="议题（可空）：例如「下一场如何升温」"
                      disabled={busy || lensBusy}
                    />
                    <button
                      type="button"
                      className={styles.brainstormBtn}
                      disabled={busy || lensBusy || activeLensIds.length < 2}
                      onClick={() => void runBrainstormFlow()}
                    >
                      开始头脑风暴
                    </button>
                  </div>
                </div>
              ) : null}
              <div className={styles.personaGrid}>
                {writerCards.map((card) => {
                  const key = card.id ?? "__default__";
                  const isDefault = card.id === null;
                  const selected = isDefault
                    ? activeLensIds.length === 0
                    : activeLensIds.includes(card.id as string);
                  return (
                    <button
                      key={key}
                      type="button"
                      className={
                        selected
                          ? `${styles.personaCard} ${styles.personaCardOn}`
                          : styles.personaCard
                      }
                      disabled={lensBusy}
                      onClick={() => setDetailKey(key)}
                    >
                      <WriterPortrait
                        lensId={card.id}
                        size="sm"
                        selected={selected}
                      />
                      <span className={styles.personaCardRole}>{card.role}</span>
                      <strong className={styles.personaCardName}>
                        {card.name}
                      </strong>
                      {selected ? (
                        <span className={styles.personaCardCheck}>
                          {multiSelect ? "入队" : "对话中"}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {helpOpen ? (
            <div className={styles.stageOverlay} role="dialog" aria-modal="true">
              <header className={styles.overlayHead}>
                <div>
                  <p className={styles.overlayIdx}>HELP</p>
                  <h3 className={styles.overlayTitle}>功能说明</h3>
                </div>
                <button
                  type="button"
                  className={styles.hudBtn}
                  onClick={() => setHelpOpen(false)}
                >
                  关闭
                </button>
              </header>
              <div className={styles.harnessPrefs}>
                <p className={styles.harnessPrefsTitle}>Harness 定稿纪律</p>
                <label className={styles.harnessToggle}>
                  <input
                    type="checkbox"
                    checked={Boolean(harnessPrefs.voiceHard)}
                    onChange={(e) => {
                      const next = setHarnessPrefs({
                        voiceHard: e.target.checked,
                      });
                      setHarnessPrefsState(next);
                    }}
                  />
                  <span>
                    声线硬门禁
                    <small>破人设（high）直接挡定稿 / 入库</small>
                  </span>
                </label>
                <label className={styles.harnessToggle}>
                  <input
                    type="checkbox"
                    checked={harnessPrefs.voiceCheck !== false}
                    onChange={(e) => {
                      const next = setHarnessPrefs({
                        voiceCheck: e.target.checked,
                      });
                      setHarnessPrefsState(next);
                    }}
                  />
                  <span>
                    终检声线
                    <small>流水线末轮 / 定稿跑角色声线检查</small>
                  </span>
                </label>
                <label className={styles.harnessToggle}>
                  <span className={styles.harnessRounds}>
                    修正轮次
                    <select
                      value={harnessPrefs.maxReviseRounds ?? 2}
                      onChange={(e) => {
                        const next = setHarnessPrefs({
                          maxReviseRounds: Number(e.target.value),
                        });
                        setHarnessPrefsState(next);
                      }}
                    >
                      {[0, 1, 2, 3, 4, 5].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </span>
                </label>
              </div>
              <AgentMessageBody content={HELP_MD} mode="markdown" />
            </div>
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
