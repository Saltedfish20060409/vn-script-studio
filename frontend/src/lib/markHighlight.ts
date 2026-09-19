/**
 * 把「标记区间」叠加到编辑器镜像的行内 token 上，用于在正文里高亮被标记的段落。
 *
 * 编辑器是 textarea + 同步滚动的 <pre> 镜像（字形由镜像显示）：往镜像里插
 * highlight 不能改变字形度量，所以这里只产出分段，样式层只用 background /
 * underline / color（与既有 `.place` 同一套做法）。
 */

/** 与 mapOccurrences 的 ScriptToken 对齐（text = 普通文字，place = 地图地点词） */
export type BaseToken = { value: string; type: "text" | "place" };

export type MarkRange = {
  id: string;
  /** 绝对偏移（相对整篇正文） */
  from: number;
  to: number;
  active?: boolean;
};

export type Segment = {
  text: string;
  /** plain | place（地点词）| mark（被标记的正文） */
  kind: "plain" | "place" | "mark";
  markId?: string;
  active?: boolean;
};

function coveringMark(marks: MarkRange[], absFrom: number, absTo: number): MarkRange | null {
  for (const mark of marks) {
    if (mark.from < absTo && absFrom < mark.to) return mark;
  }
  return null;
}

/**
 * 单行的分段结果。`lineStart` 是这一行首字符在整篇正文里的绝对偏移。
 * 标记区间优先于地点词高亮（同一段既被标记又是地点词时，按标记显示）。
 */
export function lineSegments(
  tokens: BaseToken[],
  lineStart: number,
  marks: MarkRange[]
): Segment[] {
  if (marks.length === 0) {
    return tokens.map((t) => ({ text: t.value, kind: t.type === "place" ? "place" : "plain" }));
  }
  const out: Segment[] = [];
  let cursor = lineStart;
  for (const token of tokens) {
    const tokenStart = cursor;
    const tokenEnd = cursor + token.value.length;
    cursor = tokenEnd;
    if (!token.value) continue;

    const mark = coveringMark(marks, tokenStart, tokenEnd);
    if (!mark) {
      out.push({ text: token.value, kind: token.type === "place" ? "place" : "plain" });
      continue;
    }
    // token 与标记区间求交，切成若干子段（标记内 / 标记外）
    let pos = tokenStart;
    while (pos < tokenEnd) {
      const inMark = pos >= mark.from && pos < mark.to;
      let end: number;
      if (inMark) end = Math.min(tokenEnd, mark.to);
      else if (mark.from > pos && mark.from < tokenEnd) end = mark.from;
      else end = tokenEnd;
      out.push({
        text: token.value.slice(pos - tokenStart, end - tokenStart),
        kind: inMark ? "mark" : token.type === "place" ? "place" : "plain",
        ...(inMark ? { markId: mark.id, active: Boolean(mark.active) } : {}),
      });
      pos = end;
    }
  }
  return out;
}

/** 每行的起始绝对偏移，供 lineSegments 使用。 */
export function lineStarts(text: string): number[] {
  const starts: number[] = [];
  let offset = 0;
  for (const line of text.replace(/\r\n/g, "\n").split("\n")) {
    starts.push(offset);
    offset += line.length + 1;
  }
  return starts;
}

/** 某个绝对偏移在第几行（0 基）。 */
export function lineIndexOf(text: string, offset: number): number {
  const safe = Math.max(0, Math.min(offset, text.length));
  return text.slice(0, safe).split("\n").length - 1;
}
