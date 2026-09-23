/** Persist studio UI so refresh / re-login restores where you left off. */

export type StudioTab = "write" | "world" | "voice" | "map" | "system" | "project";

export interface WorkspaceSnapshot {
  projectId: string;
  chapterId: string;
  tab: StudioTab;
  /** 视图：三栏写作工作台，或"像系统桌面"的入口（可在系统设置里切） */
  view: "studio" | "desktop";
  writeSub: "script" | "analysis";
  worldSub: "characters" | "bible" | "lore" | "entries";
  systemSub: "variables" | "sprites";
  projectSub:
    | "library"
    | "ledger"
    | "stats"
    // 稿件体检（离线统计，不调模型）：标点/引号/人名/视角 + 注音/拟声/章末钩子
    | "audit"
    // 连载工作台：日更目标、连续天数、更新日历、存稿与发布状态
    | "serial"
    | "analysis"
    | "assets"
    | "localization"
    | "export"
    | "history"
    | "members";
  sideOpen: boolean;
  agentSize: "mini" | "normal" | "large";
  updatedAt: number;
}

const KEY = "vnss-workspace-v1";
const LEGACY_PROJECT_KEY = "vnss-active-project-id";

const DEFAULTS: Omit<WorkspaceSnapshot, "projectId" | "chapterId" | "updatedAt"> = {
  tab: "write",
  // 默认三栏工作台：桌面视图是"供选择"的第二形态，不替老用户改习惯
  view: "studio",
  writeSub: "script",
  worldSub: "characters",
  systemSub: "variables",
  projectSub: "library",
  sideOpen: true,
  agentSize: "normal",
};

export function loadWorkspace(): Partial<WorkspaceSnapshot> {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<WorkspaceSnapshot>;
      return parsed && typeof parsed === "object" ? parsed : {};
    }
  } catch {
    /* fall through */
  }
  try {
    const legacy = localStorage.getItem(LEGACY_PROJECT_KEY);
    if (legacy) return { projectId: legacy };
  } catch {
    /* ignore */
  }
  return {};
}

export function saveWorkspace(patch: Partial<WorkspaceSnapshot>) {
  try {
    const prev = loadWorkspace();
    const next: WorkspaceSnapshot = {
      projectId: patch.projectId ?? prev.projectId ?? "",
      chapterId: patch.chapterId ?? prev.chapterId ?? "",
      tab: (patch.tab ?? prev.tab ?? DEFAULTS.tab) as StudioTab,
      view: patch.view ?? prev.view ?? DEFAULTS.view,
      writeSub: patch.writeSub ?? prev.writeSub ?? DEFAULTS.writeSub,
      worldSub: patch.worldSub ?? prev.worldSub ?? DEFAULTS.worldSub,
      systemSub: patch.systemSub ?? prev.systemSub ?? DEFAULTS.systemSub,
      projectSub: patch.projectSub ?? prev.projectSub ?? DEFAULTS.projectSub,
      sideOpen:
        typeof patch.sideOpen === "boolean"
          ? patch.sideOpen
          : typeof prev.sideOpen === "boolean"
            ? prev.sideOpen
            : DEFAULTS.sideOpen,
      agentSize: patch.agentSize ?? prev.agentSize ?? DEFAULTS.agentSize,
      updatedAt: Date.now(),
    };
    localStorage.setItem(KEY, JSON.stringify(next));
    if (next.projectId) {
      localStorage.setItem(LEGACY_PROJECT_KEY, next.projectId);
    }
  } catch {
    /* ignore quota */
  }
}

export function workspaceDefaults() {
  return { ...DEFAULTS };
}
