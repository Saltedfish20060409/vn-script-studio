/**
 * LRC 歌词解析。
 * 支持 `[mm:ss.xx]` / `[mm:ss]` 时间戳行、元标签（[ti:] [ar:] [al:] [offset:]）、
 * 以及多时间戳一行（`[00:12.00][00:45.00]歌词`）。
 * `[offset:±ms]` 会把整份歌词的时间轴平移（网易云歌词常见）。
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
  /** 原始偏移（毫秒，负=歌词提前）；已并入 lines.time */
  offsetMs?: number;
}

export interface LrcResult {
  lines: LrcLine[];
  meta: LrcMeta;
}

const TIME_RE = /\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
const META_RE = /^\[(ti|ar|al|by|offset):(.*)\]$/i;

/** 作词/作曲/编曲等「制作信息行」：很多 LRC 会给它们也打上时间戳
 *  （[00:00.00]作词：林夕），它们不是歌词，混入会让歌词行数比实际唱句
 *  多、滚动定位对不上正在唱的那句。整行很短且以制作角色开头 → 跳过。
 *  兼容变体：作词：X / 作词 : X / 作词:X / 词 : X / 演唱: X /
 *  纯音乐标注（前奏/间奏/尾奏/Music…）。 */
const CREDIT_RE =
  /^(作词|作曲|编曲|混音|录音|制作人|制作|和声|监制|出品|发行|演唱|原唱|翻唱|词|曲)\s*[:：]/;
const INSTRUMENTAL_RE =
  /^[（(]?(前奏|间奏|尾奏|纯音乐|music|instrumental|interlude|op|ed|歌词提供)[:：]?[）)]?[\s（(]?/i;

function isCreditLine(text: string): boolean {
  const t = text.trim();
  if (t.length > 30) return false;
  if (CREDIT_RE.test(t)) return true;
  // 「作词 林夕」「作曲 陈辉阳」——有些 LRC 连冒号都省了
  if (/^(作词|作曲|编曲|演唱|原唱|翻唱)\s+\S{1,10}$/.test(t)) return true;
  return INSTRUMENTAL_RE.test(t);
}

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
      else if (key === "offset") {
        const ms = parseInt(val, 10);
        if (Number.isFinite(ms)) meta.offsetMs = ms;
      }
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
    if (!text || isCreditLine(text)) continue;
    for (const t of stamps) {
      lines.push({ time: t, text });
    }
  }
  // 应用 [offset:]：负值=歌词整体提前（时间减），正值=延后
  const shift = (meta.offsetMs ?? 0) / 1000;
  if (shift !== 0) {
    for (const ln of lines) ln.time = Math.max(0, ln.time + shift);
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
