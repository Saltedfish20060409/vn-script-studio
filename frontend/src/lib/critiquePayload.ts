/**
 * P6：解析审稿 JSON（summary + issues），供 AgentChat 渲染。
 */
export type CritiqueIssue = {
  code: string;
  severity: string;
  quote?: string;
  reason: string;
  suggestion?: string;
};

export type CritiquePayload = {
  summary: string;
  issues: CritiqueIssue[];
};

export function parseCritiquePayload(raw: string): CritiquePayload | null {
  const text = (raw || "").trim();
  if (!text) return null;
  let data: unknown = null;
  try {
    const m = text.match(/\{[\s\S]*\}/);
    if (m) data = JSON.parse(m[0]);
  } catch {
    data = null;
  }
  if (!data || typeof data !== "object") return null;
  const obj = data as Record<string, unknown>;
  const issuesRaw = Array.isArray(obj.issues) ? obj.issues : [];
  const issues: CritiqueIssue[] = [];
  for (const item of issuesRaw.slice(0, 40)) {
    if (typeof item === "string" && item.trim()) {
      issues.push({ code: "note", severity: "warn", reason: item.trim() });
      continue;
    }
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const reason = String(row.reason || row.message || "").trim();
    if (!reason) continue;
    issues.push({
      code: String(row.code || "issue").slice(0, 40),
      severity: String(row.severity || "warn").slice(0, 16),
      quote: row.quote ? String(row.quote).slice(0, 200) : undefined,
      reason: reason.slice(0, 500),
      suggestion: row.suggestion
        ? String(row.suggestion).slice(0, 400)
        : undefined,
    });
  }
  if (!issues.length && !String(obj.summary || "").trim()) return null;
  return {
    summary: String(obj.summary || obj.note || "").trim().slice(0, 400),
    issues,
  };
}

export function critiqueIssuesToMarkHints(issues: CritiqueIssue[]) {
  return issues.map((i) => ({
    quote: i.quote,
    reason: i.reason,
    instruction: i.suggestion,
    code: i.code,
  }));
}
