/**
 * chapterReviseSegments 改稿段级对齐单元测试
 *
 * 覆盖 splitParagraphs 分段策略、normalizeForMatch 格式噪声清洗、
 * buildReviseSegments 的 equal/changed/added/removed 判定、
 * mergeReviseSegments 合并与 countRevisedKept 统计。
 */
import { describe, it, expect } from "vitest";
import {
  normalizeForMatch,
  splitParagraphs,
  buildReviseSegments,
  mergeReviseSegments,
  countRevisedKept,
} from "./chapterReviseSegments";

describe("normalizeForMatch：清洗格式噪声", () => {
  it("去掉 Ren'Py 指令行前缀 [label/scene/show...]", () => {
    expect(normalizeForMatch("[scene bg station] 她到了车站")).toBe(
      "她到了车站"
    );
  });

  it("去掉 旁白： 说话人前缀", () => {
    expect(normalizeForMatch("旁白：雨声渐大")).toBe("雨声渐大");
  });

  it("去掉 选项： 前缀", () => {
    expect(normalizeForMatch("选项：去车站")).toBe("去车站");
  });

  it("剥离中文引号与英文引号", () => {
    expect(normalizeForMatch("「林夏」：她推开门")).toBe("林夏：她推开门");
    expect(normalizeForMatch('lx "hi"')).toBe("lxhi");
  });

  it("归一化（括号）说话人提示与半角冒号", () => {
    expect(normalizeForMatch("林夏 (含泪)：没事")).toBe("林夏：没事");
    expect(normalizeForMatch("Eileen: hello")).toBe("Eileen：hello");
  });
});

describe("splitParagraphs：分段策略", () => {
  it("para 模式按空行分段", () => {
    expect(splitParagraphs("第一段。\n\n第二段。", "para")).toEqual([
      "第一段。",
      "第二段。",
    ]);
  });

  it("line 模式按行分段并去除空白行", () => {
    expect(splitParagraphs("A\n\nB\nC", "line")).toEqual(["A", "B", "C"]);
  });

  it("auto 模式对无空行的紧凑文本采用行分段", () => {
    expect(splitParagraphs("A\nB", "auto")).toEqual(["A", "B"]);
  });

  it("auto 模式对含 Ren'Py 指令的文本采用行分段", () => {
    const text = '[label start]\n林夏 "你好"';
    expect(splitParagraphs(text, "auto")).toEqual([
      "[label start]",
      '林夏 "你好"',
    ]);
  });

  it("空白输入返回空数组", () => {
    expect(splitParagraphs("", "para")).toEqual([]);
    expect(splitParagraphs("   \n  ", "auto")).toEqual([]);
  });

  it("分段时去除每段首尾空白", () => {
    expect(splitParagraphs("  第一段  \n\n  第二段  ", "para")).toEqual([
      "第一段",
      "第二段",
    ]);
  });
});

describe("buildReviseSegments：对齐与差异判定", () => {
  it("原文与改稿完全一致 → 全部 equal 且 useRevised=true", () => {
    const segs = buildReviseSegments("A\n\nB", "A\n\nB");
    expect(segs).toHaveLength(2);
    for (const s of segs) {
      expect(s.kind).toBe("equal");
      expect(s.useRevised).toBe(true);
    }
    expect(segs[0].original).toBe("A");
    expect(segs[1].original).toBe("B");
  });

  it("中文改写段落 → changed，未动段落保持 equal", () => {
    const segs = buildReviseSegments(
      "她推开门走进教室\n\n她们沉默",
      "她推开了门走进教室\n\n她们沉默"
    );
    expect(segs).toHaveLength(2);
    expect(segs[0]).toMatchObject({
      original: "她推开门走进教室",
      revised: "她推开了门走进教室",
      kind: "changed",
      useRevised: true,
    });
    expect(segs[1]).toMatchObject({
      original: "她们沉默",
      revised: "她们沉默",
      kind: "equal",
    });
  });

  it("改稿删除段落 → removed，useRevised=false 且 revised 为空", () => {
    const segs = buildReviseSegments("A\n\nB", "A");
    expect(segs).toHaveLength(2);
    expect(segs[1]).toMatchObject({
      original: "B",
      revised: "",
      kind: "removed",
      useRevised: false,
    });
  });

  it("改稿新增段落 → added，original 为空", () => {
    const segs = buildReviseSegments("A", "A\n\n新段落");
    expect(segs).toHaveLength(2);
    expect(segs[1]).toMatchObject({
      original: "",
      revised: "新段落",
      kind: "added",
      useRevised: true,
    });
  });

  it("Ren'Py 密集脚本走行分段并对齐", () => {
    const original = ['[label start]', '林夏 "你好"', "[scene bg park]"].join(
      "\n"
    );
    const revised = ['[label start]', '林夏 "你好！"', "[scene bg park]"].join(
      "\n"
    );
    const segs = buildReviseSegments(original, revised);
    expect(segs).toHaveLength(3);
    expect(segs[0].kind).toBe("equal");
    expect(segs[1].kind).toBe("changed");
    expect(segs[1].revised).toBe('林夏 "你好！"');
    expect(segs[2].kind).toBe("equal");
  });

  it("两侧均为空 → 单个空 equal 段", () => {
    const segs = buildReviseSegments("", "");
    expect(segs).toEqual([
      {
        id: "seg-0",
        original: "",
        revised: "",
        useRevised: true,
        kind: "equal",
      },
    ]);
  });

  it("段 id 按 0 递增", () => {
    const segs = buildReviseSegments("A\n\nB", "A\n\nB");
    expect(segs.map((s) => s.id)).toEqual(["seg-0", "seg-1"]);
  });
});

describe("mergeReviseSegments：按 useRevised 合并", () => {
  it("useRevised=true 取改稿，false 保留原文，空段被过滤", () => {
    const segs = [
      { id: "s0", original: "A", revised: "A1", useRevised: true, kind: "changed" as const },
      { id: "s1", original: "B", revised: "B1", useRevised: false, kind: "changed" as const },
      { id: "s2", original: "", revised: "", useRevised: true, kind: "equal" as const },
      { id: "s3", original: "", revised: "C", useRevised: true, kind: "added" as const },
    ];
    expect(mergeReviseSegments(segs)).toBe("A1\n\nB\n\nC");
  });

  it("removed 段默认保留原文，改 useRevised=true 后原文被移除", () => {
    const segs = buildReviseSegments("A\n\nB", "A");
    // 默认：removed 段 useRevised=false → 保留原文 B
    expect(mergeReviseSegments(segs)).toBe("A\n\nB");
    // 用户决定应用删除 → 输出只剩 A
    const applied = segs.map((s) => ({ ...s, useRevised: true }));
    expect(mergeReviseSegments(applied)).toBe("A");
  });

  it("合并结果对段落做 trim", () => {
    const segs = [
      { id: "s0", original: "  A  ", revised: "  A  ", useRevised: true, kind: "equal" as const },
    ];
    expect(mergeReviseSegments(segs)).toBe("A");
  });
});

describe("countRevisedKept：统计保留倾向", () => {
  it("equal 与双空段不计入，useRevised 决定计数", () => {
    const segs = [
      { id: "s0", original: "A", revised: "A", useRevised: true, kind: "equal" as const },
      { id: "s1", original: "B", revised: "B1", useRevised: true, kind: "changed" as const },
      { id: "s2", original: "C", revised: "", useRevised: false, kind: "removed" as const },
      { id: "s3", original: "", revised: "D", useRevised: true, kind: "added" as const },
      { id: "s4", original: "", revised: "", useRevised: true, kind: "equal" as const },
    ];
    expect(countRevisedKept(segs)).toEqual({ keptRevised: 2, keptOriginal: 1 });
  });

  it("全部 equal 时两项统计均为 0", () => {
    const segs = buildReviseSegments("A\n\nB", "A\n\nB");
    expect(countRevisedKept(segs)).toEqual({ keptRevised: 0, keptOriginal: 0 });
  });
});
