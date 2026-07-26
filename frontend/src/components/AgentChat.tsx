import { useCallback, useEffect, useRef, useState } from "react";
import {
  createAgentConversation,
  deleteAgentConversation,
  getAgentConversation,
  listAgentConversations,
  putAgentConversation,
  renameAgentConversation,
  runAgent,
  type AgentConversationSummary,
} from "../api/client";
import type { AgentAction, AgentChatMessage, AgentTaskKind, VnProject } from "../types/vn";
import { AgentMessageBody } from "./AgentMarkdown";
import styles from "./AgentChat.module.css";

type Props = {
  project: VnProject;
  chapterId: string;
  selection: string;
  prepareProject?: () => VnProject;
  onProjectChange: (project: VnProject) => void;
  onChapterFocus?: (chapterId: string) => void;
  compact?: boolean;
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
        "我是这部作品的驻场责编。快捷按钮是专业化任务（续写 / 写一场戏 / 查矛盾…），会按当前章 + 相关设定检索上下文。\n对话保存在服务器上，可新建多条对话；刷新或换设备仍可接续。Agent 写入工程前会记一版，可用「撤回编辑」回滚。",
    },
  ];
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
      if (Array.isArray(conv.messages) && conv.messages.length > 0) {
        setMessages(conv.messages);
      } else {
        setMessages(defaultWelcome());
      }
      undoStack.current = parseUndoStack(
        Array.isArray(conv.undo_stack) ? conv.undo_stack : []
      );
      setUndoCount(undoStack.current.length);
      setLastContext("");
      setError("");
      setInput("");
      sessionReady.current = true;
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
    setError("");
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
      setLastContext(
        [taskName, resultBit, craftShort, reviewShort].filter(Boolean).join(" · ")
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
          <div className={styles.quickRow}>
            {QUICK_ACTIONS.map((a) => (
              <button
                key={a.label}
                type="button"
                className={styles.quickBtn}
                disabled={busy || loadingConv || !conversationId}
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
          </div>
          {lastContext ? (
            <p
              className={styles.ctxMeta}
              title="只显示是否写入工程；详细工艺在设置里可调"
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
                : "对话保存在服务器；左侧可直接改名，拖动中缝可调宽度"}
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
                <AgentMessageBody
                  content={m.content}
                  mode={m.role === "user" ? "plain" : "markdown"}
                />
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
