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
  putProjectLenses,
  runBrainstorm,
  listAgentConversations,
  putAgentConversation,
  renameAgentConversation,
  runAgent,
  type AgentConversationSummary,
  type HarnessLintResult,
  type LensPackMeta,
  type PipelineRunResult,
} from "../api/client";
import type { AgentAction, AgentChatMessage, AgentTaskKind, VnProject } from "../types/vn";
import { AgentMessageBody } from "./AgentMarkdown";
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
};

const HELP_MD = `### 责编能帮你做什么

用平常话说需求即可。**轻小说 / 视觉小说写法底盘**（可演对白、钩子、去说明书）由「通用文学编辑」在每次对话里自动生效。

### 推荐写作流程

1. **直接聊**：说清场次或卡点。  
2. **（可选）换作家眼光**：点顶部 **⇄**，选一位作家 skill 卡（可开多选做头脑风暴）。  
3. **文风体检**（可选）：扫问题不改文。  
4. **定稿**：过门禁并更新写作账本。

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
  const [busy, setBusy] = useState(false);
  const [loadingConv, setLoadingConv] = useState(true);
  const [error, setError] = useState("");
  const [lastContext, setLastContext] = useState<string>("");
  const [undoCount, setUndoCount] = useState(0);
  const [thinking, setThinking] = useState("编辑正在检索设定 / 读当前章…");
  const [helpOpen, setHelpOpen] = useState(false);
  const [personaOpen, setPersonaOpen] = useState(false);
  const [multiSelect, setMultiSelect] = useState(false);
  const [brainstormTopic, setBrainstormTopic] = useState("");
  const [lensCatalog, setLensCatalog] = useState<LensPackMeta[]>([]);
  const [activeLensIds, setActiveLensIds] = useState<string[]>([]);
  const [lensBusy, setLensBusy] = useState(false);
  const [sidebarW, setSidebarW] = useState(() => {
    try {
      const n = Number(localStorage.getItem("vnss-agent-sidebar-w"));
      if (Number.isFinite(n) && n >= 140 && n <= 420) return n;
    } catch {
      /* ignore */
    }
    return 176;
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
    if (
      !window.confirm(
        "删除当前对话？消息记录将从服务器移除，不会改动剧本内容。"
      )
    ) {
      return;
    }
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
    if (!trimmed || busy || !conversationId) return;

    // Natural-language shortcuts into pipeline / gate (still one Agent)
    if (
      /^(跑|运行)?\s*(完整)?流水线/.test(trimmed) ||
      trimmed.startsWith("【流水线】") ||
      /请.*(规划|计划).*(写|生成|续写)/.test(trimmed)
    ) {
      const intent = trimmed.replace(/^【流水线】/, "").replace(/^(跑|运行)?\s*(完整)?流水线[：:\s]*/, "");
      await runPipelineFlow(intent || trimmed);
      return;
    }
    if (/^(文风)?体检$|^风格检查/.test(trimmed)) {
      await runStyleLint();
      return;
    }
    if (/^定稿(入库)?$/.test(trimmed)) {
      await runQualityFinalize();
      return;
    }
    if (/^(头脑风暴|圆桌|多视角)[：:\s]/.test(trimmed) || trimmed === "头脑风暴") {
      const topic = trimmed
        .replace(/^(头脑风暴|圆桌|多视角)[：:\s]*/, "")
        .trim();
      await runBrainstormFlow(topic);
      return;
    }
    if (/^(列出|查看)?写作导师|^导师列表$|^当前导师$/.test(trimmed)) {
      await runListMentors();
      return;
    }

    setError("");
    setThinking("编辑正在检索设定 / 读当前章…");
    const nextMessages: AgentChatMessage[] = [
      ...messages,
      { role: "user", content: trimmed },
    ];
    setMessages(nextMessages);
    setBusy(true);
    try {
      const snapshot = prepareProject ? prepareProject() : project;
      const apiMessages = nextMessages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-20);

      const res = await runAgent(projectId, {
        messages: apiMessages,
        chapter_id: chapterId,
        selection: selection || undefined,
        task,
        conversation_id: conversationId,
        apply_actions: true,
        // 与 UI 选中同步；勿仅依赖 DB（避免 PUT 未完成时本轮漏注入）
        lens_ids: activeLensIds,
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
    const topic = (topicOverride ?? brainstormTopic).trim();
    if (!topic) {
      setError("请先填写头脑风暴议题（想解决的问题）");
      setPersonaOpen(true);
      setMultiSelect(true);
      return;
    }
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
    parts.push(
      "\n_稿件尚未自动写入工程。满意后可在脚本区粘贴，或点「定稿入库」通过门禁后写入账本。_"
    );
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
      const data = await pipelineRun(projectId, {
        instruction: userLine,
        draft: (draft || "").trim() || undefined,
        selection: selection || undefined,
        chapter_id: chapterId,
      });
      const content = formatPipelineResult(data);
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
      setLastContext(
        data.gate?.pass
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
      const data = await pipelineGate(projectId, {
        draft: (draft || "").trim() || undefined,
        chapter_id: chapterId,
        finalize: true,
        update_ledger: true,
      });
      const ok = data.gate?.pass;
      const content = ok
        ? `### 定稿入库\n\n${data.gate?.message || "已通过质量门禁"}\n\n章节事实摘要已写入写作账本，供后续生成作硬锚。`
        : `### 定稿被门禁拦截\n\n${data.gate?.message || "未通过"}\n\n${(
            data.check?.issues || []
          )
            .filter((i) => i.severity === "error")
            .slice(0, 12)
            .map((i) => `- ${i.code}：${i.message}`)
            .join("\n")}`;
      setMessages((prev) => [...prev, { role: "assistant", content }]);
      if (ok && data.project) {
        onProjectChange(data.project);
      }
      setLastContext(ok ? "定稿 · 门禁通过 · 账本已更新" : "定稿 · 门禁拦截");
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
      const data = await pipelineLedgerDigest(projectId, chapterId);
      onProjectChange(data.project);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `### 章节锚点已入库\n\n已将当前章的事实摘要 / 出场状态 / 章末钩子写入写作账本。\n\n${(
            data.agentBlock || ""
          ).slice(0, 1200)}`,
        },
      ]);
      setLastContext("账本 · 章节摘要已更新");
    } catch (e) {
      setError(e instanceof Error ? e.message : "账本更新失败");
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

  return (
    <div
      className={compact ? styles.shellCompact : styles.shell}
      style={hidden ? { display: "none" } : undefined}
      aria-hidden={hidden || undefined}
    >
      <div className={styles.split} ref={splitRef}>
        <aside className={styles.sidebar} style={{ width: sidebarW }}>
          <div className={styles.sideHead}>
            <span className={styles.sideTitle}>对话</span>
            <button
              type="button"
              className={styles.sideNew}
              disabled={busy || loadingConv}
              onClick={() => void handleNewConversation()}
              title="新建对话"
            >
              新建
            </button>
          </div>
          <div className={styles.convList} role="listbox" aria-label="对话列表">
            {conversations.map((c) => {
              const active = c.id === conversationId;
              return (
                <div
                  key={c.id}
                  role="option"
                  aria-selected={active}
                  className={
                    active ? `${styles.convItem} ${styles.convItemActive}` : styles.convItem
                  }
                  onClick={() => {
                    if (!active) void switchConversation(c.id);
                  }}
                >
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
        </aside>

        <div
          className={styles.splitter}
          role="separator"
          aria-orientation="vertical"
          aria-label="拖动调整对话列表宽度"
          aria-valuenow={sidebarW}
          onPointerDown={(e) => {
            e.preventDefault();
            resizing.current = true;
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
            try {
              (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            } catch {
              /* ignore */
            }
          }}
        />

        <div className={styles.main}>
          <div className={styles.mainHead}>
            <div className={styles.mainHeadLeft}>
              <span className={styles.mainHeadTitle}>对话中</span>
              <span className={styles.personaBadge} title="当前对话对象">
                {personaLabel}
              </span>
            </div>
            <div className={styles.mainHeadActions}>
              <button
                type="button"
                className={styles.personaBtn}
                aria-expanded={personaOpen}
                aria-label="切换作家 / 写手"
                title="切换作家 / 写手"
                onClick={() => {
                  setHelpOpen(false);
                  setPersonaOpen((v) => !v);
                }}
              >
                ⇄
              </button>
              <button
                type="button"
                className={styles.helpBtn}
                aria-expanded={helpOpen}
                aria-label="功能说明与推荐流程"
                title="功能说明与推荐流程"
                onClick={() => {
                  setPersonaOpen(false);
                  setHelpOpen((v) => !v);
                }}
              >
                !
              </button>
            </div>
          </div>
          {personaOpen ? (
            <div className={styles.personaPanel}>
              <div className={styles.personaPanelTop}>
                <p className={styles.personaPanelLead}>
                  选择对话对象。默认是通用文学编辑（LN/VN 底盘自动开）。其他卡片是**作家思维 skill**（可多选头脑风暴）。
                </p>
                <label className={styles.multiToggle}>
                  <input
                    type="checkbox"
                    checked={multiSelect}
                    onChange={(e) => setMultiSelect(e.target.checked)}
                  />
                  多选（强头脑风暴）
                </label>
                {multiSelect || activeLensIds.length >= 2 ? (
                  <div className={styles.brainstormBox}>
                    <input
                      className={styles.brainstormInput}
                      value={brainstormTopic}
                      onChange={(e) => setBrainstormTopic(e.target.value)}
                      placeholder="议题：例如「男主与雪菜下一场如何升温又不掉距离感」"
                      disabled={busy || lensBusy}
                    />
                    <button
                      type="button"
                      className={styles.brainstormBtn}
                      disabled={
                        busy ||
                        lensBusy ||
                        activeLensIds.length < 2 ||
                        !brainstormTopic.trim()
                      }
                      onClick={() => void runBrainstormFlow()}
                      title={
                        activeLensIds.length < 2
                          ? "请至少选 2 位作家"
                          : "各位作家独立发言后由责编综合"
                      }
                    >
                      开始头脑风暴
                    </button>
                  </div>
                ) : null}
              </div>
              <div className={styles.personaGrid}>
                {writerCards.map((card) => {
                  const isDefault = card.id === null;
                  const selected = isDefault
                    ? activeLensIds.length === 0
                    : activeLensIds.includes(card.id as string);
                  return (
                    <button
                      key={card.id ?? "__default__"}
                      type="button"
                      className={
                        selected
                          ? `${styles.personaCard} ${styles.personaCardOn}`
                          : styles.personaCard
                      }
                      disabled={lensBusy}
                      onClick={() => void onWriterCardClick(card.id)}
                    >
                      <span className={styles.personaCardRole}>{card.role}</span>
                      <strong className={styles.personaCardName}>{card.name}</strong>
                      <span className={styles.personaCardBlurb}>{card.blurb}</span>
                      {selected ? (
                        <span className={styles.personaCardCheck}>已选</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                className={styles.helpClose}
                onClick={() => setPersonaOpen(false)}
              >
                收起
              </button>
            </div>
          ) : null}
          {helpOpen ? (
            <div className={styles.helpPanel}>
              <AgentMessageBody content={HELP_MD} mode="markdown" />
              <button
                type="button"
                className={styles.helpClose}
                onClick={() => setHelpOpen(false)}
              >
                收起说明
              </button>
            </div>
          ) : null}
          {lastContext ? (
            <p
              className={styles.ctxMeta}
              title="本轮 Agent 结果摘要"
            >
              {lastContext}
            </p>
          ) : null}
          {selection ? (
            <p className={styles.selHint}>已带入选区 {selection.length} 字</p>
          ) : (
            <p className={styles.selHint}>
              {loadingConv
                ? "正在加载对话…"
                : "用平常话说需求即可。点 ⇄ 换参谋，点 ! 看说明。"}
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
                  {m.role === "user" ? "你" : activeLensIds.length ? "参谋" : "编辑"}
                </span>
                <AgentMessageBody
                  content={m.content}
                  mode={m.role === "user" ? "plain" : "markdown"}
                />
              </div>
            ))}
            {busy && <p className={styles.thinking}>{thinking}</p>}
          </div>
          {error && <p className={styles.error}>{error}</p>}
          <div className={styles.composer}>
            <textarea
              rows={compact ? 2 : 3}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="例如：续写天台那场，雪菜先开口…"
              disabled={busy || loadingConv || !conversationId}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button
              type="button"
              className={styles.sendBtn}
              disabled={busy || loadingConv || !conversationId || !input.trim()}
              onClick={() => void send()}
            >
              {busy ? "…" : "发送"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
