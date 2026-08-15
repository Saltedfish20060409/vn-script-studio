/** Studio mascot (雾岛雪菜 stand-in) art by expression / mood.
 * Assets share one canvas (480×917, feet-aligned) so mood swaps don't jump.
 */
export type MascotMood =
  | "idle"
  | "think"
  | "cheer"
  | "angel"
  | "wince"
  | "angry"
  | "fluster"
  | "worry"
  | "puzzled"
  | "focus";

const ART_VER = "5";

const ART: Record<MascotMood, string> = {
  idle: `/mascot/idle.png?v=${ART_VER}`,
  think: `/mascot/think.png?v=${ART_VER}`,
  cheer: `/mascot/cheer.png?v=${ART_VER}`,
  angel: `/mascot/angel.png?v=${ART_VER}`,
  wince: `/mascot/wince.png?v=${ART_VER}`,
  angry: `/mascot/angry.png?v=${ART_VER}`,
  fluster: `/mascot/fluster.png?v=${ART_VER}`,
  worry: `/mascot/worry.png?v=${ART_VER}`,
  puzzled: `/mascot/puzzled.png?v=${ART_VER}`,
  /** Focus chrome: soft puzzled / attentive look */
  focus: `/mascot/puzzled.png?v=${ART_VER}`,
};
/** Filename → mood (for docs / tooling). */
export const MASCOT_FILENAME_MOOD: Record<string, MascotMood> = {
  "雾岛雪菜.png": "idle",
  "雾岛雪菜（思考）.png": "think",
  "雾岛雪菜（愉悦）.png": "cheer",
  "雾岛雪菜（小天使）.png": "angel",
  "雾岛雪菜（愠恼）.png": "wince",
  "雾岛雪菜（生气）.png": "angry",
  "雾岛雪菜（慌乱）.png": "fluster",
  "雾岛雪菜（担忧）.png": "worry",
  "雾岛雪菜（疑惑）.png": "puzzled",
};

export function mascotArtSrc(mood: MascotMood = "idle"): string {
  return ART[mood] || ART.idle;
}

export const MASCOT_MOODS: MascotMood[] = [
  "idle",
  "think",
  "cheer",
  "angel",
  "wince",
  "angry",
  "fluster",
  "worry",
  "puzzled",
  "focus",
];
