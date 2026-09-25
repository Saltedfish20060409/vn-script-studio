/** Persist studio UI so refresh / re-login restores where you left off. */

import {
  legacyTabFromOverlay,
  overlayFromLegacyTab,
  projectSubFromOverlay,
  writeSubFromOverlay,
  type StudioOverlay,
} from "./studioOverlay";

export type StudioTab = "write" | "world" | "voice" | "map" | "system" | "project";

export type ProjectSub =
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

export interface WorkspaceSnapshot {
  projectId: string;
  chapterId: string;
  /**
   * 旧字段：Word 壳以 `overlay` 为准。仍写入以便旧客户端读；读入时若无 overlay 则从 tab 推导。
   */
  tab: StudioTab;
  /** 视图：稿纸工作台，或"像系统桌面"的启动器 */
  view: "studio" | "desktop";
  /**
   * Word 壳当前叠在稿纸上的面板。null = 纯稿纸。
   * 兼容：缺省时由 tab + projectSub / writeSub 推导。
   */
  overlay: StudioOverlay;
  writeSub: "script" | "analysis";
  worldSub: "characters" | "bible" | "lore" | "entries";
  systemSub: "variables" | "sprites";
  projectSub: ProjectSub;
  sideOpen: boolean;
  agentSize: "mini" | "normal" | "large";
  updatedAt: number;
}

const KEY = "vnss-workspace-v1";
const LEGACY_PROJECT_KEY = "vnss-active-project-id";

const DEFAULTS: Omit<WorkspaceSnapshot, "projectId" | "chapterId" | "updatedAt"> = {
  tab: "write",
  // 默认稿纸工作台：桌面视图是启动器，不替老用户改习惯
  view: "studio",
  overlay: null,
  writeSub: "script",
  worldSub: "characters",
  systemSub: "variables",
  projectSub: "library",
  sideOpen: true,
  agentSize: "normal",
};

function normalizeOverlay(
  raw: Partial<WorkspaceSnapshot>
): StudioOverlay {
  if ("overlay" in raw) {
    const o = raw.overlay;
    if (o === null) return null;
    if (o && typeof o === "object" && "type" in o) {
      if (o.type === "file" && o.page) return { type: "file", page: o.page };
      if (o.type === "view" && o.panel) return { type: "view", panel: o.panel };
      if (o.type === "analysis") return { type: "analysis" };
    }
  }
  // 旧快照：writeSub=analysis 优先于 tab=write
  if (raw.writeSub === "analysis" && (!raw.tab || raw.tab === "write")) {
    return { type: "analysis" };
  }
  return overlayFromLegacyTab(raw.tab, raw.projectSub);
}

export function loadWorkspace(): Partial<WorkspaceSnapshot> {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<WorkspaceSnapshot>;
      if (!parsed || typeof parsed !== "object") return {};
      const overlay = normalizeOverlay(parsed);
      return {
        ...parsed,
        overlay,
        tab: legacyTabFromOverlay(overlay),
        writeSub: writeSubFromOverlay(overlay),
        projectSub: projectSubFromOverlay(
          overlay,
          parsed.projectSub ?? DEFAULTS.projectSub
        ),
      };
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
    // overlay 优先；若只传了旧字段 tab，则从 tab 推导（兼容旧调用方）
    let mergedOverlay: StudioOverlay;
    if ("overlay" in patch) {
      mergedOverlay = patch.overlay as StudioOverlay;
    } else if ("tab" in patch && patch.tab) {
      mergedOverlay =
        patch.tab === "write" &&
        (patch.writeSub === "analysis" ||
          (!("writeSub" in patch) && prev.writeSub === "analysis"))
          ? { type: "analysis" }
          : overlayFromLegacyTab(
              patch.tab,
              patch.projectSub ?? prev.projectSub
            );
    } else if ("writeSub" in patch && patch.writeSub === "analysis") {
      mergedOverlay = { type: "analysis" };
    } else {
      mergedOverlay = normalizeOverlay({ ...prev, ...patch });
    }
    const next: WorkspaceSnapshot = {
      projectId: patch.projectId ?? prev.projectId ?? "",
      chapterId: patch.chapterId ?? prev.chapterId ?? "",
      overlay: mergedOverlay,
      tab: legacyTabFromOverlay(mergedOverlay),
      view: patch.view ?? prev.view ?? DEFAULTS.view,
      writeSub: writeSubFromOverlay(mergedOverlay),
      worldSub: patch.worldSub ?? prev.worldSub ?? DEFAULTS.worldSub,
      systemSub: patch.systemSub ?? prev.systemSub ?? DEFAULTS.systemSub,
      projectSub: projectSubFromOverlay(
        mergedOverlay,
        patch.projectSub ?? prev.projectSub ?? DEFAULTS.projectSub
      ),
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
