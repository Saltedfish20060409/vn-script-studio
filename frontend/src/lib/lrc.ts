/**
 * LRC 歌词解析 — 极简实现。
 * 支持 `[mm:ss.xx]` / `[mm:ss]` 时间戳行、元标签（[ti:] [ar:] [al:]）、
 * 以及多时间戳一行（`[00:12.00][00:45.00]歌词`）。
 */

export interface LrcLine {
  /** 秒 */
  time: number;
  text: string;
}

export interface LrcMeta {
  title?: string;
  artist?: string;
  album?: string;
}

export interface LrcResult {
  lines: LrcLine[];
  meta: LrcMeta;
}

const TIME_RE = /\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
const META_RE = /^\[(ti|ar|al|by|offset):(.*)\]$/i;

function toSeconds(m: string, s: string, frac?: string): number {
  const sec = parseInt(m, 10) * 60 + parseInt(s, 10);
  if (!frac) return sec;
  // 1~3 位小数
  const pad = frac.padEnd(3, "0");
  return sec + parseInt(pad, 10) / 1000;
}

export function parseLrc(raw: string): LrcResult {
  const lines: LrcLine[] = [];
  const meta: LrcMeta = {};
  const sources = (raw || "").split(/\r?\n/);
  for (const src of sources) {
    const line = src.trim();
    if (!line) continue;
    const metaMatch = line.match(META_RE);
    if (metaMatch) {
      const key = metaMatch[1].toLowerCase();
      const val = metaMatch[2].trim();
      if (key === "ti") meta.title = val;
      else if (key === "ar") meta.artist = val;
      else if (key === "al") meta.album = val;
      continue;
    }
    const stamps: number[] = [];
    let last = 0;
    TIME_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = TIME_RE.exec(line)) !== null) {
      stamps.push(toSeconds(m[1], m[2], m[3]));
      last = m.index + m[0].length;
    }
    if (!stamps.length) continue;
    const text = line.slice(last).trim();
    if (!text) continue;
    for (const t of stamps) {
      lines.push({ time: t, text });
    }
  }
  lines.sort((a, b) => a.time - b.time);
  return { lines, meta };
}

/** 当前播放时间对应的歌词行索引（-1 = 还没到第一句）。 */
export function activeLrcIndex(lines: LrcLine[], currentTime: number): number {
  let idx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].time <= currentTime) idx = i;
    else break;
  }
  return idx;
}
