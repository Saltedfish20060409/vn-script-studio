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

export type CollabEvent =
  | { type: "member"; kind: "added" | "removed" | "role_changed"; userId?: string; username?: string; role?: string }
  | { type: "lock"; kind: "acquired" | "released"; chapterId?: string; userId?: string; username?: string };

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

  async function connect() {
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
    } catch {
      /* connection closed (expected on unmount/abort) */
    }
    if (!closed) {
      // Reconnect after a short backoff (server keepalive gaps or transient drops).
      setTimeout(() => void connect(), 3000);
    }
  }

  void connect();
  return () => {
    closed = true;
    controller?.abort();
  };
}
