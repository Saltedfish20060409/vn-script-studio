import { describe, expect, it } from "vitest";
import {
  lineIndexOf,
  lineSegments,
  lineStarts,
  locateInNodes,
  type BaseToken,
  type MarkRange,
} from "./markHighlight";

const plain = (value: string): BaseToken => ({ value, type: "text" });
const place = (value: string): BaseToken => ({ value, type: "place" });

describe("lineStarts / lineIndexOf", () => {
  it("算得出每行起始偏移（含换行符）", () => {
    expect(lineStarts("ab\ncde\nf")).toEqual([0, 3, 7]);
  });

  it("CRLF 也当一行（偏移按规范化后的文本算）", () => {
    expect(lineStarts("ab\r\ncd")).toEqual([0, 3]);
  });

  it("偏移落在第几行", () => {
    const text = "ab\ncde\nf";
    expect(lineIndexOf(text, 0)).toBe(0);
    expect(lineIndexOf(text, 2)).toBe(0);
    expect(lineIndexOf(text, 3)).toBe(1);
    expect(lineIndexOf(text, 6)).toBe(1);
    expect(lineIndexOf(text, 7)).toBe(2);
    // 越界不炸
    expect(lineIndexOf(text, 999)).toBe(2);
    expect(lineIndexOf(text, -5)).toBe(0);
  });
});

describe("locateInNodes：偏移落在哪个文本节点", () => {
  it("按节点长度累加定位", () => {
    expect(locateInNodes([3, 2, 1], 0)).toEqual({ index: 0, local: 0 });
    expect(locateInNodes([3, 2, 1], 2)).toEqual({ index: 0, local: 2 });
    expect(locateInNodes([3, 2, 1], 3)).toEqual({ index: 1, local: 0 });
    expect(locateInNodes([3, 2, 1], 4)).toEqual({ index: 1, local: 1 });
    expect(locateInNodes([3, 2, 1], 5)).toEqual({ index: 2, local: 0 });
  });

  it("空节点被跳过", () => {
    expect(locateInNodes([0, 2, 0, 3], 2)).toEqual({ index: 3, local: 0 });
  });

  it("越过末尾 → 挂到最后一个节点之后（光标停在文末的情形）", () => {
    expect(locateInNodes([3, 2], 99)).toEqual({ index: 1, local: 2 });
  });

  it("负数偏移或没有节点 → null", () => {
    expect(locateInNodes([3, 2], -1)).toBeNull();
    expect(locateInNodes([], 0)).toBeNull();
  });
});

describe("lineSegments：没有标记时保持原样", () => {
  it("地点词仍然是 place", () => {
    const segs = lineSegments([plain("去"), place("码头"), plain("看看")], 0, []);
    expect(segs.map((s) => [s.text, s.kind])).toEqual([
      ["去", "plain"],
      ["码头", "place"],
      ["看看", "plain"],
    ]);
  });
});

describe("lineSegments：标记区间叠加", () => {
  it("token 完全落在标记里 → 整段变 mark", () => {
    const marks: MarkRange[] = [{ id: "m1", from: 1, to: 3 }];
    const segs = lineSegments([plain("去"), plain("码头")], 0, marks);
    expect(segs).toEqual([
      { text: "去", kind: "plain" },
      { text: "码头", kind: "mark", markId: "m1", active: false },
    ]);
  });

  it("标记只盖住 token 的一半 → 切成两段", () => {
    const marks: MarkRange[] = [{ id: "m1", from: 2, to: 5 }];
    const segs = lineSegments([plain("0123456")], 0, marks);
    expect(segs.map((s) => [s.text, s.kind])).toEqual([
      ["01", "plain"],
      ["234", "mark"],
      ["56", "plain"],
    ]);
  });

  it("标记跨多个 token → 每段分别标记", () => {
    const marks: MarkRange[] = [{ id: "m1", from: 0, to: 4 }];
    const segs = lineSegments([plain("ab"), place("cd"), plain("ef")], 0, marks);
    expect(segs.map((s) => [s.text, s.kind])).toEqual([
      ["ab", "mark"],
      ["cd", "mark"],
      ["ef", "plain"],
    ]);
  });

  it("行首偏移参与计算（第二行的标记只影响第二行）", () => {
    const marks: MarkRange[] = [{ id: "m1", from: 3, to: 5 }];
    const segs = lineSegments([plain("cde")], 3, marks);
    expect(segs.map((s) => [s.text, s.kind])).toEqual([
      ["cd", "mark"],
      ["e", "plain"],
    ]);
  });

  it("active 透传（当前正在核对的那一条要高亮得不一样）", () => {
    const marks: MarkRange[] = [{ id: "m1", from: 0, to: 2, active: true }];
    const segs = lineSegments([plain("abcd")], 0, marks);
    expect(segs[0]).toEqual({ text: "ab", kind: "mark", markId: "m1", active: true });
  });

  it("标记与地点词重叠时按标记显示（一个字形只能有一种样式）", () => {
    const marks: MarkRange[] = [{ id: "m1", from: 0, to: 2 }];
    const segs = lineSegments([place("码头")], 0, marks);
    expect(segs[0].kind).toBe("mark");
  });

  it("空 token 被跳过，不产生空段", () => {
    const segs = lineSegments([plain(""), plain("ab")], 0, [{ id: "m1", from: 0, to: 1 }]);
    expect(segs.every((s) => s.text.length > 0)).toBe(true);
    expect(segs.map((s) => s.text).join("")).toBe("ab");
  });

  it("拼接结果永远等于原文（不丢字、不重复）", () => {
    const tokens = [plain("雨落在站台上。"), plain("他慢慢抬起手。")];
    const marks: MarkRange[] = [
      { id: "m1", from: 2, to: 6 },
      { id: "m2", from: 8, to: 12 },
    ];
    const text = tokens.map((t) => t.value).join("");
    const segs = lineSegments(tokens, 0, marks);
    expect(segs.map((s) => s.text).join("")).toBe(text);
  });
});
