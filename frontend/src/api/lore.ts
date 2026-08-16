import { apiFetch } from "./http";
export interface LoreCard {
  id: string;
  projectId?: string | null;
  term: string;
  aliases: string[];
  kind: string;
  definition_short?: string;
  do?: string[];
  dont?: string[];
  vn_beats?: string[];
  source_title?: string;
  source_url?: string;
  raw_extract?: string;
  attribution?: string;
}

export interface LoreLookupResult {
  card?: LoreCard;
  source?: "seed" | "moegirl" | "moegirl+seed";
  hits?: Array<{ title: string; snippet?: string }>;
  attribution?: string;
}

export function loreMeta(
  id: string
): Promise<{
  attribution: string;
  licenseNote: string;
  moegirlEnabled: boolean;
  checklistKinds: string[];
}> {
  return apiFetch(`/projects/${id}/lore/meta`);
}

export function loreChecklist(
  id: string,
  kinds?: string
): Promise<{ cards: LoreCard[]; attribution: string }> {
  return apiFetch(
    `/projects/${id}/lore/checklist${kinds ? `?kinds=${encodeURIComponent(kinds)}` : ""}`
  );
}

export function loreListCards(id: string): Promise<{ cards: LoreCard[] }> {
  return apiFetch(`/projects/${id}/lore/cards`);
}

export function loreSearch(
  id: string,
  term: string
): Promise<{
  hits: Array<{ title: string; snippet?: string }>;
  moegirlEnabled: boolean;
  attribution?: string;
}> {
  return apiFetch(`/projects/${id}/lore/search`, {
    method: "POST",
    body: JSON.stringify({ term, prefer_live: true }),
  });
}

export function loreLookup(
  id: string,
  term: string,
  preferLive = true
): Promise<LoreLookupResult> {
  return apiFetch(`/projects/${id}/lore/lookup`, {
    method: "POST",
    body: JSON.stringify({ term, prefer_live: preferLive }),
  });
}

export function loreInspire(
  id: string,
  text: string,
  kinds?: string[],
  limit = 6
): Promise<{ cards: LoreCard[]; agentBlock?: string }> {
  return apiFetch(`/projects/${id}/lore/inspire`, {
    method: "POST",
    body: JSON.stringify({ text, kinds, limit }),
  });
}

export function loreSaveCard(
  id: string,
  card: Partial<LoreCard>
): Promise<{ card: LoreCard }> {
  const { id: _ignored, projectId: _p, ...body } = card;
  return apiFetch(`/projects/${id}/lore/cards`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function loreDeleteCard(id: string, cardId: string): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${id}/lore/cards/${cardId}`, {
    method: "DELETE",
  });
}
