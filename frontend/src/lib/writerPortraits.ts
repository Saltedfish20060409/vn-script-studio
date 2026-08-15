/** Writer portrait art for Agent lens cards (not the studio mascot). */

export type WriterPortraitMeta = {
  /** File under /writers/ */
  file: string;
  /** Accent for fallback / frame */
  accent: string;
  /** Short cue used when generating / documenting the silhouette */
  cue: string;
};

/** Default LN/VN editor (not a named author, not the studio mascot). */
export const EDITOR_PORTRAIT: WriterPortraitMeta = {
  file: "editor.png",
  accent: "#002fa7",
  cue: "neutral desk editor silhouette, slate blue",
};

export const WRITER_PORTRAITS: Record<string, WriterPortraitMeta> = {
  "author-murakami": {
    file: "murakami.png",
    accent: "#3d5a6c",
    cue: "short hair, glasses, cool slate-teal silhouette",
  },
  "author-higashino": {
    file: "higashino.png",
    accent: "#1e293b",
    cue: "neat short hair, glasses, indigo-noir silhouette",
  },
  "author-watari": {
    file: "watari.png",
    accent: "#64748b",
    cue: "youthful short hair, cool grey-blue LN author silhouette",
  },
  "author-nishio": {
    file: "nishio.png",
    accent: "#7c3aed",
    cue: "sharp angular silhouette, violet dialogue-dense vibe",
  },
  "author-kamachi": {
    file: "kamachi.png",
    accent: "#0ea5e9",
    cue: "short hair, energetic cyan action-author silhouette",
  },
  "author-nasu": {
    file: "nasu.png",
    accent: "#6d28d9",
    cue: "hooded/obscured face, deep purple concept-mage silhouette",
  },
  "author-maeda": {
    file: "maeda.png",
    accent: "#be123c",
    cue: "soft short hair, crimson emotional VN silhouette",
  },
  "author-maruto": {
    file: "maruto.png",
    accent: "#db2777",
    cue: "gentle silhouette, rose romance VN tone",
  },
  "author-urobuchi": {
    file: "urobuchi.png",
    accent: "#450a0a",
    cue: "dark crimson-black severe silhouette",
  },
  "author-romeo": {
    file: "romeo.png",
    accent: "#ea580c",
    cue: "wry smile hint, warm orange comedy silhouette",
  },
  "author-hayashi": {
    file: "hayashi.png",
    accent: "#059669",
    cue: "soft warm hair, green school-healing silhouette",
  },
  "author-looseboy": {
    file: "looseboy.png",
    accent: "#0891b2",
    cue: "modern adult, teal contemporary silhouette",
  },
  "author-niijima": {
    file: "niijima.png",
    accent: "#ca8a04",
    cue: "summer-light hair tip, gold youth ensemble silhouette",
  },
  "author-urushibara": {
    file: "urushibara.png",
    accent: "#4c1d95",
    cue: "abstract angular, deep violet experimental silhouette",
  },
  "author-kai": {
    file: "kai.png",
    accent: "#334155",
    cue: "composed short hair, steel-grey drama silhouette",
  },
};

export function writerPortraitUrl(lensId: string | null | undefined): string {
  if (!lensId) return `/writers/${EDITOR_PORTRAIT.file}`;
  const meta = WRITER_PORTRAITS[lensId] || EDITOR_PORTRAIT;
  return `/writers/${meta.file}`;
}

export function writerPortraitAccent(lensId: string | null | undefined): string {
  if (!lensId) return EDITOR_PORTRAIT.accent;
  return WRITER_PORTRAITS[lensId]?.accent || EDITOR_PORTRAIT.accent;
}
