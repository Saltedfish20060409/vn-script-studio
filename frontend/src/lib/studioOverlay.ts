/**
 * Word 壳：稿纸永远在中心，非写作面板走 overlay（文件 backstage / 视图抽屉 / 分析）。
 * 旧版 workspace 的 `tab` 字段在读入时映射到这里。
 */
import type { StudioTab, WorkspaceSnapshot } from "./workspacePersist";

export type ViewPanel = "world" | "voice" | "map" | "system";

export type ProjectSub = WorkspaceSnapshot["projectSub"];

export type StudioOverlay =
  | null
  | { type: "file"; page: ProjectSub }
  | { type: "view"; panel: ViewPanel }
  | { type: "analysis" };

export function overlayFromLegacyTab(
  tab: StudioTab | undefined,
  projectSub: ProjectSub | undefined
): StudioOverlay {
  if (!tab || tab === "write") return null;
  if (tab === "project") {
    return { type: "file", page: projectSub ?? "library" };
  }
  if (tab === "world" || tab === "voice" || tab === "map" || tab === "system") {
    return { type: "view", panel: tab };
  }
  return null;
}

/** 写回快照时仍填 tab，方便旧代码/调试；以 overlay 为准推导。 */
export function legacyTabFromOverlay(overlay: StudioOverlay): StudioTab {
  if (!overlay) return "write";
  if (overlay.type === "file") return "project";
  if (overlay.type === "analysis") return "write";
  return overlay.panel;
}

export function projectSubFromOverlay(
  overlay: StudioOverlay,
  fallback: ProjectSub
): ProjectSub {
  if (overlay?.type === "file") return overlay.page;
  return fallback;
}

export function writeSubFromOverlay(
  overlay: StudioOverlay
): "script" | "analysis" {
  return overlay?.type === "analysis" ? "analysis" : "script";
}

export function isDocumentQuiet(overlay: StudioOverlay): boolean {
  return overlay === null;
}
