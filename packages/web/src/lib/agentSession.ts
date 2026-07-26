import type { AgentChatMessage, VnProject } from "@vnss/core";
import { compressChatHistory } from "@vnss/core";

const CHAT_PREFIX = "vnss-agent-chat-v1:";
const UNDO_PREFIX = "vnss-agent-undo-v1:";
const MEMORY_PREFIX = "vnss-agent-memory-v1:";

const DEFAULT_WELCOME: AgentChatMessage = {
  role: "assistant",
  content:
    "我是这部作品的驻场责编。快捷按钮是专业化任务（续写 / 写一场戏 / 查矛盾…），会按当前章 + 相关设定检索上下文。\n对话会保存在本机，最小化或刷新后仍可接续。Agent 写入工程前会自动记一版，可用「撤回编辑」回滚。",
};

export function defaultAgentWelcome(): AgentChatMessage[] {
  return [{ ...DEFAULT_WELCOME }];
}

export function loadAgentChat(projectId: string): AgentChatMessage[] {
  if (typeof window === "undefined" || !projectId) {
    return defaultAgentWelcome();
  }
  try {
    const raw = localStorage.getItem(CHAT_PREFIX + projectId);
    if (!raw) return defaultAgentWelcome();
    const parsed = JSON.parse(raw) as AgentChatMessage[];
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return defaultAgentWelcome();
    }
    return parsed
      .filter(
        (m) =>
          m &&
          (m.role === "user" || m.role === "assistant") &&
          typeof m.content === "string"
      )
      .slice(-120);
  } catch {
    return defaultAgentWelcome();
  }
}

export function saveAgentChat(
  projectId: string,
  messages: AgentChatMessage[]
): void {
  if (typeof window === "undefined" || !projectId) return;
  try {
    localStorage.setItem(
      CHAT_PREFIX + projectId,
      JSON.stringify(messages.slice(-120))
    );
  } catch {
    /* quota */
  }
}

export function clearAgentChat(projectId: string): void {
  if (typeof window === "undefined" || !projectId) return;
  try {
    localStorage.removeItem(CHAT_PREFIX + projectId);
    localStorage.removeItem(MEMORY_PREFIX + projectId);
  } catch {
    /* ignore */
  }
}

export function loadChatPriorMemory(projectId: string): string {
  if (typeof window === "undefined" || !projectId) return "";
  try {
    return localStorage.getItem(MEMORY_PREFIX + projectId) || "";
  } catch {
    return "";
  }
}

export function saveChatPriorMemory(projectId: string, memory: string): void {
  if (typeof window === "undefined" || !projectId) return;
  try {
    if (!memory.trim()) {
      localStorage.removeItem(MEMORY_PREFIX + projectId);
      return;
    }
    localStorage.setItem(MEMORY_PREFIX + projectId, memory.slice(0, 4000));
  } catch {
    /* ignore */
  }
}

/** Build memory + recent messages for Agent API */
export function prepareAgentChatPayload(
  projectId: string,
  messages: AgentChatMessage[]
): { chatMemory: string; apiMessages: AgentChatMessage[] } {
  const prior = loadChatPriorMemory(projectId);
  const bundle = compressChatHistory(messages, {
    keepRecent: 16,
    summarizeAfter: 22,
    priorMemory: prior,
  });
  if (bundle.summarizedCount > 0 && bundle.memoryBlock) {
    // Persist a shortened rolling memory for next time
    const compact = bundle.memoryBlock.slice(0, 2500);
    saveChatPriorMemory(projectId, compact);
  }
  return {
    chatMemory: bundle.memoryBlock,
    apiMessages: bundle.recentMessages,
  };
}

/** Slim project for undo stack — drop nested snapshot payloads to save quota */
function slimForUndo(project: VnProject): VnProject {
  return {
    ...project,
    snapshots: (project.snapshots ?? []).map((s) => ({
      ...s,
      payload: "",
    })),
  };
}

export type AgentUndoEntry = {
  at: string;
  label: string;
  payload: string;
};

export function loadAgentUndo(projectId: string): AgentUndoEntry[] {
  if (typeof window === "undefined" || !projectId) return [];
  try {
    const raw = localStorage.getItem(UNDO_PREFIX + projectId);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as AgentUndoEntry[];
    return Array.isArray(parsed) ? parsed.slice(0, 20) : [];
  } catch {
    return [];
  }
}

function saveAgentUndo(projectId: string, stack: AgentUndoEntry[]): void {
  if (typeof window === "undefined" || !projectId) return;
  try {
    localStorage.setItem(
      UNDO_PREFIX + projectId,
      JSON.stringify(stack.slice(0, 20))
    );
  } catch {
    /* quota — drop older */
    try {
      localStorage.setItem(
        UNDO_PREFIX + projectId,
        JSON.stringify(stack.slice(0, 5))
      );
    } catch {
      /* ignore */
    }
  }
}

export function pushAgentUndo(
  projectId: string,
  project: VnProject,
  label: string
): AgentUndoEntry[] {
  const entry: AgentUndoEntry = {
    at: new Date().toISOString(),
    label,
    payload: JSON.stringify(slimForUndo(project)),
  };
  const next = [entry, ...loadAgentUndo(projectId)].slice(0, 20);
  saveAgentUndo(projectId, next);
  return next;
}

export function popAgentUndo(
  projectId: string
): { entry: AgentUndoEntry; rest: AgentUndoEntry[] } | null {
  const stack = loadAgentUndo(projectId);
  if (stack.length === 0) return null;
  const [entry, ...rest] = stack;
  saveAgentUndo(projectId, rest);
  return { entry, rest };
}

export function agentUndoCount(projectId: string): number {
  return loadAgentUndo(projectId).length;
}
