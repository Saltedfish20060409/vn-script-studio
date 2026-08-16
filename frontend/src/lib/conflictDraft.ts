/** Stash local project drafts when save hits 409 conflict. */

import type { VnProject } from "../types/vn";

const KEY = "vnss-save-conflict-drafts-v1";

type Store = Record<
  string,
  {
    project: VnProject;
    savedAt: number;
    reason?: string;
  }
>;

function readStore(): Store {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const data = JSON.parse(raw) as Store;
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

function writeStore(store: Store): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    /* quota — ignore */
  }
}

export function stashConflictDraft(project: VnProject, reason = "save_409"): void {
  const store = readStore();
  store[project.id] = {
    project,
    savedAt: Date.now(),
    reason,
  };
  writeStore(store);
}

export function getConflictDraft(projectId: string): VnProject | null {
  const row = readStore()[projectId];
  return row?.project ?? null;
}

export function clearConflictDraft(projectId: string): void {
  const store = readStore();
  if (!store[projectId]) return;
  delete store[projectId];
  writeStore(store);
}

export function downloadProjectJson(project: VnProject, filename?: string): void {
  const blob = new Blob([JSON.stringify(project, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || `${project.title || "project"}-local-draft.json`;
  a.click();
  URL.revokeObjectURL(url);
}
