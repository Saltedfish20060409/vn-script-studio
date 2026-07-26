/** Persist studio UI so refresh / re-login restores where you left off. */

export type StudioTab = "write" | "world" | "map" | "system" | "project";

export interface WorkspaceSnapshot {
  projectId: string;
  chapterId: string;
  tab: StudioTab;
  writeSub: "script" | "analysis";
  worldSub: "characters" | "bible";
  systemSub: "variables" | "sprites";
  projectSub: "library" | "export" | "history";
  sideOpen: boolean;
  agentSize: "mini" | "normal" | "large";
  updatedAt: number;
}

const KEY = "vnss-workspace-v1";
const LEGACY_PROJECT_KEY = "vnss-active-project-id";

const DEFAULTS: Omit<WorkspaceSnapshot, "projectId" | "chapterId" | "updatedAt"> = {
  tab: "write",
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
