/** Client-side helpers for analysis fact-bus (mirrors backend weak sync rules). */

const WEAK_LINK_LABELS = new Set(["同场", "设定共现", "粘贴共现"]);

export function shouldWeakSyncLabel(label: string): boolean {
  return !WEAK_LINK_LABELS.has((label || "").trim());
}

export function appendRelationshipClause(
  rel: string | undefined,
  clause: string
): string {
  const cur = (rel || "").trim();
  if (clause && cur.includes(clause)) return cur;
  return cur ? `${cur}；${clause}` : clause;
}

export function weakSyncCharacters<
  T extends { id: string; displayName: string; relationships?: string },
>(characters: T[], fromId: string, toId: string, label: string): T[] {
  if (!shouldWeakSyncLabel(label)) return characters;
  const a = characters.find((c) => c.id === fromId);
  const b = characters.find((c) => c.id === toId);
  if (!a || !b) return characters;
  const clauseAb = `与${b.displayName}：${label}`;
  const clauseBa = `与${a.displayName}：${label}`;
  return characters.map((c) => {
    if (c.id === a.id) {
      return {
        ...c,
        relationships: appendRelationshipClause(c.relationships, clauseAb),
      };
    }
    if (c.id === b.id) {
      return {
        ...c,
        relationships: appendRelationshipClause(c.relationships, clauseBa),
      };
    }
    return c;
  });
}
