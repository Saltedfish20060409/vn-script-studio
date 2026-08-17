import { apiFetch } from "./http";

// ---------------------------------------------------------------------------
// Collaboration — project members, chapter locks, live events
// ---------------------------------------------------------------------------

export interface MemberInfo {
  userId: string;
  username: string;
  role: "owner" | "editor" | "viewer";
  joinedAt?: string;
}

export function listProjectMembers(
  projectId: string
): Promise<{ owner: MemberInfo; members: MemberInfo[] }> {
  return apiFetch(`/projects/${projectId}/members`);
}

export function addProjectMember(
  projectId: string,
  username: string,
  role: "editor" | "viewer"
): Promise<MemberInfo> {
  return apiFetch(`/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify({ username, role }),
  });
}

export function changeMemberRole(
  projectId: string,
  userId: string,
  role: "editor" | "viewer"
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${projectId}/members/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeProjectMember(
  projectId: string,
  userId: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${projectId}/members/${userId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Invite links
// ---------------------------------------------------------------------------

export interface InviteInfo {
  token: string;
  role: "editor" | "viewer";
  expiresAt: string;
}

export function createProjectInvite(
  projectId: string,
  role: "editor" | "viewer"
): Promise<InviteInfo> {
  return apiFetch(`/projects/${projectId}/invites`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
}

export function listProjectInvites(
  projectId: string
): Promise<{ invites: InviteInfo[] }> {
  return apiFetch(`/projects/${projectId}/invites`);
}

export function revokeProjectInvite(
  projectId: string,
  token: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${projectId}/invites/${token}`, {
    method: "DELETE",
  });
}

export function acceptProjectInvite(
  token: string
): Promise<{
  projectId: string;
  alreadyMember: boolean;
  role: "editor" | "viewer" | null;
}> {
  return apiFetch(`/projects/invites/accept`, {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export interface ChapterLockInfo {
  chapterId: string;
  userId: string;
  username: string;
  expiresAt: string;
}

export function getProjectLocks(
  projectId: string
): Promise<{ locks: ChapterLockInfo[] }> {
  return apiFetch(`/projects/${projectId}/locks`);
}

export function lockChapter(
  projectId: string,
  chapterId: string
): Promise<{ chapterId: string; userId: string; expiresAt: string }> {
  return apiFetch(`/projects/${projectId}/locks/${chapterId}`, {
    method: "POST",
  });
}

export function unlockChapter(
  projectId: string,
  chapterId: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${projectId}/locks/${chapterId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Comments (collaboration stage C)
// ---------------------------------------------------------------------------

export interface ProjectComment {
  id: string;
  projectId: string;
  chapterId: string;
  /** Empty for chapter-level; else block:<id> or a text range. */
  anchor: string;
  /** Empty for top-level comments; else the parent comment id (2 levels). */
  parentId: string;
  userId: string;
  username: string;
  text: string;
  resolved: boolean;
  createdAt: string;
  updatedAt: string;
}

export function listProjectComments(
  projectId: string,
  chapterId?: string
): Promise<{ comments: ProjectComment[] }> {
  const q = chapterId ? `?chapter_id=${encodeURIComponent(chapterId)}` : "";
  return apiFetch(`/projects/${projectId}/comments${q}`);
}

export function addProjectComment(
  projectId: string,
  body: { chapter_id: string; text: string; anchor?: string; parent_id?: string }
): Promise<ProjectComment> {
  return apiFetch(`/projects/${projectId}/comments`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateProjectComment(
  projectId: string,
  commentId: string,
  patch: { text?: string; resolved?: boolean }
): Promise<ProjectComment> {
  return apiFetch(`/projects/${projectId}/comments/${commentId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteProjectComment(
  projectId: string,
  commentId: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${projectId}/comments/${commentId}`, {
    method: "DELETE",
  });
}

export type CollabEvent =
  | { type: "member"; kind: "added" | "removed" | "role_changed"; userId?: string; username?: string; role?: string }
  | { type: "lock"; kind: "acquired" | "released"; chapterId?: string; userId?: string; username?: string }
  | { type: "comment"; kind: "added" | "updated" | "deleted"; id?: string; chapterId?: string; userId?: string; username?: string; text?: string; resolved?: boolean };

/**
 * Subscribe to project collaboration events via SSE.
 * Returns an unsubscribe function.
 */
export function subscribeProjectEvents(
  projectId: string,
  onEvent: (evt: CollabEvent) => void
): () => void {
  let closed = false;
  let controller: AbortController | null = null;
  let retryTimer: number | null = null;
  let retryDelay = 1000;

  async function connect() {
    if (closed) return;
    const token = localStorage.getItem("vnss-token") || "";
    controller = new AbortController();
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/events`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            onEvent(JSON.parse(payload) as CollabEvent);
          } catch {
            /* skip malformed */
          }
        }
      }
      // Healthy disconnect (server closed) → reset backoff.
      retryDelay = 1000;
    } catch {
      /* connection closed (expected on unmount/abort) */
    }
    if (!closed) {
      // Exponential backoff with a cap; the timer handle is kept so
      // unsubscribe can cancel a scheduled reconnect before it fires.
      retryTimer = window.setTimeout(() => void connect(), retryDelay);
      retryDelay = Math.min(retryDelay * 2, 15000);
    }
  }

  void connect();
  return () => {
    closed = true;
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
    controller?.abort();
  };
}
