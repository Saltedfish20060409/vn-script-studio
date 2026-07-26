import type { VnProject } from "@vnss/core";

const SHARE_KEY = "vnss-shares-v1";

export type SharePayload = {
  id: string;
  title: string;
  createdAt: string;
  /** Sanitized read-only project snapshot */
  project: VnProject;
};

function readMap(): Record<string, SharePayload> {
  try {
    const raw = localStorage.getItem(SHARE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, SharePayload>;
  } catch {
    return {};
  }
}

function writeMap(map: Record<string, SharePayload>) {
  localStorage.setItem(SHARE_KEY, JSON.stringify(map));
}

/** Strip script bodies for artist/VA read-only packs if desired — keep full for now */
export function publishShare(project: VnProject, shareId: string): SharePayload {
  const payload: SharePayload = {
    id: shareId,
    title: project.title,
    createdAt: new Date().toISOString(),
    project: {
      ...project,
      shareId,
    },
  };
  const map = readMap();
  map[shareId] = payload;
  writeMap(map);
  return payload;
}

export function loadShare(id: string): SharePayload | null {
  return readMap()[id] ?? null;
}

export function saveShareFromFile(payload: SharePayload) {
  const map = readMap();
  map[payload.id] = payload;
  writeMap(map);
}
