/** Split / merge chapter revise drafts with content-aware alignment. */

export type ReviseSegment = {
  id: string;
  original: string;
  revised: string;
  /** true = use revised; false = keep original */
  useRevised: boolean;
  /** equal | changed | added | removed — for UI badges */
  kind: "equal" | "changed" | "added" | "removed";
};

function normalizeNewlines(text: string): string {
  return (text || "").replace(/\r\n/g, "\n").trim();
}

/** Strip format noise so Ren'Py-plain and prose revises can still match. */
export function normalizeForMatch(s: string): string {
  return (s || "")
    .replace(/\r\n/g, "\n")
    .replace(/^\s*\[(label|scene|show|hide|jump)[^\]]*\]\s*/i, "")
    .replace(/^\s*旁白\s*[：:]\s*/u, "")
    .replace(/^\s*选项\s*[：:]\s*/u, "")
    .replace(/^\s*([^：:\n]{1,20})\s*[（(][^）)\n]{0,40}[）)]\s*[：:]/u, "$1：")
    .replace(/[「」『』“”"']/g, "")
    .replace(/:/g, "：")
    .replace(/\s+/g, "")
    .trim();
}

function prefersLineUnits(text: string): boolean {
  const normalized = normalizeNewlines(text);
  if (!normalized) return false;
  const blankCount = (normalized.match(/\n\n+/g) || []).length;
  const lineCount = normalized.split("\n").filter((l) => l.trim()).length;
  // Ren'Py-plain / dense scripts: many short lines, few blank gaps
  if (/^\s*\[(label|scene|show)/m.test(normalized)) return true;
  return blankCount === 0 || (lineCount > 8 && blankCount < lineCount / 6);
}

/** Prefer blank-line paragraphs; fall back to line units for dense VN scripts. */
export function splitParagraphs(
  text: string,
  mode: "auto" | "para" | "line" = "auto"
): string[] {
  const normalized = normalizeNewlines(text);
  if (!normalized) return [];
  const useLine = mode === "line" || (mode === "auto" && prefersLineUnits(normalized));
  if (useLine) {
    return normalized
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return normalized
    .split(/\n{2,}/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function similarity(a: string, b: string): number {
  if (a === b) return 1;
  if (!a || !b) return 0;
  const na = normalizeForMatch(a);
  const nb = normalizeForMatch(b);
  if (!na || !nb) return 0;
  if (na === nb) return 0.99;

  // Speaker / head cue
  const headA = na.slice(0, Math.min(8, na.length));
  const headB = nb.slice(0, Math.min(8, nb.length));
  const prefixBoost = headA && headA === headB ? 0.18 : 0;

  const sa = new Set(na);
  const sb = new Set(nb);
  let inter = 0;
  for (const c of sa) if (sb.has(c)) inter += 1;
  const union = sa.size + sb.size - inter || 1;
  const jaccard = inter / union;

  // Bigram overlap — better for Chinese rewrites
  const grams = (s: string) => {
    const out = new Set<string>();
    for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2));
    if (s.length === 1) out.add(s);
    return out;
  };
  const ga = grams(na);
  const gb = grams(nb);
  let gInter = 0;
  for (const g of ga) if (gb.has(g)) gInter += 1;
  const gUnion = ga.size + gb.size - gInter || 1;
  const bigram = gInter / gUnion;

  const lenRatio = Math.min(na.length, nb.length) / Math.max(na.length, nb.length);
  return Math.min(1, jaccard * 0.25 + bigram * 0.45 + lenRatio * 0.12 + prefixBoost);
}

/** Anchor threshold for LCS "same unit". */
function isAnchor(a: string, b: string): boolean {
  return similarity(a, b) >= 0.55;
}

/** Pair threshold inside a delete/insert hunk. */
function isPairable(a: string, b: string): boolean {
  return similarity(a, b) >= 0.28;
}

type DiffOp =
  | { type: "equal"; a: string; b: string }
  | { type: "del"; a: string }
  | { type: "ins"; b: string };

/** LCS alignment with fuzzy line equality for rewritten paragraphs. */
function diffUnits(a: string[], b: string[]): DiffOp[] {
  const n = a.length;
  const m = b.length;
  const MAX = 400;
  if (n * m > MAX * MAX) {
    const ao = a.slice(0, MAX);
    const bo = b.slice(0, MAX);
    const ops = diffUnits(ao, bo);
    for (let i = MAX; i < n; i++) ops.push({ type: "del", a: a[i] });
    for (let j = MAX; j < m; j++) ops.push({ type: "ins", b: b[j] });
    return ops;
  }
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (isAnchor(a[i], b[j])) {
        dp[i][j] = dp[i + 1][j + 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }
  const ops: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (isAnchor(a[i], b[j])) {
      ops.push({ type: "equal", a: a[i], b: b[j] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: "del", a: a[i] });
      i += 1;
    } else {
      ops.push({ type: "ins", b: b[j] });
      j += 1;
    }
  }
  while (i < n) {
    ops.push({ type: "del", a: a[i] });
    i += 1;
  }
  while (j < m) {
    ops.push({ type: "ins", b: b[j] });
    j += 1;
  }
  return ops;
}

type PairOut = {
  original: string;
  revised: string;
  kind: ReviseSegment["kind"];
};

/**
 * Inside a delete/insert run, pair by best similarity (not by index),
 * so rewritten paragraphs sit beside their source lines.
 */
function pairHunk(dels: string[], ins: string[]): PairOut[] {
  if (!dels.length && !ins.length) return [];
  if (!dels.length) {
    return ins.map((revised) => ({
      original: "",
      revised,
      kind: "added" as const,
    }));
  }
  if (!ins.length) {
    return dels.map((original) => ({
      original,
      revised: "",
      kind: "removed" as const,
    }));
  }

  type Cand = { di: number; ii: number; score: number };
  const cands: Cand[] = [];
  for (let di = 0; di < dels.length; di++) {
    for (let ii = 0; ii < ins.length; ii++) {
      const score = similarity(dels[di], ins[ii]);
      if (score >= 0.28) cands.push({ di, ii, score });
    }
  }
  cands.sort((x, y) => y.score - x.score);

  const usedD = new Set<number>();
  const usedI = new Set<number>();
  const matched: Array<{ di: number; ii: number; score: number }> = [];
  for (const c of cands) {
    if (usedD.has(c.di) || usedI.has(c.ii)) continue;
    if (!isPairable(dels[c.di], ins[c.ii])) continue;
    usedD.add(c.di);
    usedI.add(c.ii);
    matched.push(c);
  }

  // Emit in reading order: walk original indices, splice unmatched inserts nearby
  const out: PairOut[] = [];
  const matchedByD = new Map(matched.map((m) => [m.di, m]));
  const unmatchedIns = ins
    .map((text, ii) => ({ text, ii }))
    .filter((x) => !usedI.has(x.ii));

  let insertCursor = 0;
  for (let di = 0; di < dels.length; di++) {
    // Flush inserts that belong before this original index (by matched ii order)
    const m = matchedByD.get(di);
    if (m) {
      while (
        insertCursor < unmatchedIns.length &&
        unmatchedIns[insertCursor].ii < m.ii
      ) {
        out.push({
          original: "",
          revised: unmatchedIns[insertCursor].text,
          kind: "added",
        });
        insertCursor += 1;
      }
      const score = m.score;
      out.push({
        original: dels[di],
        revised: ins[m.ii],
        kind: score >= 0.92 ? "equal" : "changed",
      });
    } else {
      out.push({ original: dels[di], revised: "", kind: "removed" });
    }
  }
  while (insertCursor < unmatchedIns.length) {
    out.push({
      original: "",
      revised: unmatchedIns[insertCursor].text,
      kind: "added",
    });
    insertCursor += 1;
  }
  return out;
}

/**
 * Coalesce adjacent delete+insert into similarity-paired before/after rows.
 */
function coalesceOps(ops: DiffOp[]): PairOut[] {
  const out: PairOut[] = [];
  let i = 0;
  while (i < ops.length) {
    const op = ops[i];
    if (op.type === "equal") {
      out.push({
        original: op.a,
        revised: op.b,
        kind: similarity(op.a, op.b) >= 0.92 ? "equal" : "changed",
      });
      i += 1;
      continue;
    }
    const dels: string[] = [];
    const ins: string[] = [];
    while (i < ops.length && (ops[i].type === "del" || ops[i].type === "ins")) {
      const cur = ops[i];
      if (cur.type === "del") dels.push(cur.a);
      else ins.push(cur.b);
      i += 1;
    }
    out.push(...pairHunk(dels, ins));
  }
  return out;
}

function chooseSplitMode(original: string, revised: string): "para" | "line" {
  if (prefersLineUnits(original) || prefersLineUnits(revised)) return "line";
  const oPara = splitParagraphs(original, "para").length;
  const rPara = splitParagraphs(revised, "para").length;
  const oLine = splitParagraphs(original, "line").length;
  const rLine = splitParagraphs(revised, "line").length;
  // Prefer the granularity where counts are closer (less drift).
  const paraRatio =
    Math.max(oPara, rPara, 1) / Math.min(Math.max(oPara, 1), Math.max(rPara, 1));
  const lineRatio =
    Math.max(oLine, rLine, 1) / Math.min(Math.max(oLine, 1), Math.max(rLine, 1));
  return lineRatio < paraRatio ? "line" : "para";
}

export function buildReviseSegments(
  original: string,
  revised: string
): ReviseSegment[] {
  const mode = chooseSplitMode(original, revised);
  const o = splitParagraphs(original, mode);
  const r = splitParagraphs(revised, mode);
  if (!o.length && !r.length) {
    return [
      {
        id: "seg-0",
        original: "",
        revised: "",
        useRevised: true,
        kind: "equal",
      },
    ];
  }
  const pairs = coalesceOps(diffUnits(o, r));
  return pairs.map((p, idx) => {
    const kind =
      p.kind === "equal" &&
      normalizeForMatch(p.original) === normalizeForMatch(p.revised)
        ? "equal"
        : p.kind === "equal"
          ? "changed"
          : p.kind;
    return {
      id: `seg-${idx}`,
      original: p.original,
      revised: p.revised || (kind === "removed" ? "" : p.original),
      useRevised:
        kind === "removed" ? false : kind === "equal" ? true : Boolean(p.revised),
      kind,
    };
  });
}

export function mergeReviseSegments(segments: ReviseSegment[]): string {
  return segments
    .map((s) => {
      if (s.useRevised) return (s.revised || "").trim();
      return (s.original || "").trim();
    })
    .filter(Boolean)
    .join("\n\n");
}

export function countRevisedKept(segments: ReviseSegment[]): {
  keptRevised: number;
  keptOriginal: number;
} {
  let keptRevised = 0;
  let keptOriginal = 0;
  for (const s of segments) {
    if (!s.original && !s.revised) continue;
    if (s.kind === "equal") continue;
    if (s.useRevised) keptRevised += 1;
    else keptOriginal += 1;
  }
  return { keptRevised, keptOriginal };
}
