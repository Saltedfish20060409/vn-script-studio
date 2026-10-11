/** 试玩器当前变量 → Writing Turn 的 assumed_flags（本机、按工程）。 */

const key = (projectId: string) => `vnss-assumed-flags-v1:${projectId}`;

export function saveAssumedFlags(
  projectId: string,
  flags: Record<string, unknown>
): void {
  const id = (projectId || "").trim();
  if (!id) return;
  try {
    const clean: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(flags || {})) {
      if (!k) continue;
      // 只传可 JSON 的标量；嵌套对象丢掉以免污染条件求值
      if (
        v === null ||
        typeof v === "string" ||
        typeof v === "number" ||
        typeof v === "boolean"
      ) {
        clean[k] = v;
      }
    }
    localStorage.setItem(key(id), JSON.stringify(clean));
  } catch {
    /* ignore quota */
  }
}

export function loadAssumedFlags(
  projectId: string
): Record<string, unknown> | undefined {
  const id = (projectId || "").trim();
  if (!id) return undefined;
  try {
    const raw = localStorage.getItem(key(id));
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return undefined;
    }
    return parsed as Record<string, unknown>;
  } catch {
    return undefined;
  }
}

export function clearAssumedFlags(projectId: string): void {
  const id = (projectId || "").trim();
  if (!id) return;
  try {
    localStorage.removeItem(key(id));
  } catch {
    /* ignore */
  }
}
