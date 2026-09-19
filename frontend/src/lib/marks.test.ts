import { describe, expect, it } from "vitest";
import {
  MAX_MARKS_PER_CHAPTER,
  applyMark,
  chapterKey,
  createMark,
  currentMarkRange,
  findMarkRange,
  isLocatable,
  loadMarks,
  markContext,
  markStats,
  pendingMarks,
  refreshMarks,
  revertMark,
  saveMarks,
  shortQuote,
  type Mark,
} from "./marks";

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

const TEXT = "雨落在站台上。他慢慢抬起手，举到眼前。那双手不是他的。";

/** 取 "他慢慢抬起手，举到眼前。" 这一段的选区 */
const FROM = TEXT.indexOf("他慢慢抬起手");
const TO = FROM + "他慢慢抬起手，举到眼前。".length;

function makeMark(overrides: Partial<Mark> = {}): Mark {
  const mark = createMark({ text: TEXT, from: FROM, to: TO, chapterId: "c1", now: 1000 });
  if (!mark) throw new Error("测试用标记创建失败");
  return { ...mark, ...overrides };
}

describe("markContext / createMark", () => {
  it("取两侧上下文（默认各 24 字），用于给模型和重新定位", () => {
    const ctx = markContext(TEXT, FROM, TO);
    expect(ctx.quote).toBe("他慢慢抬起手，举到眼前。");
    expect(ctx.prefix.endsWith("雨落在站台上。")).toBe(true);
    expect(ctx.suffix.startsWith("那双手不是他的。")).toBe(true);
  });

  it("选区在开头/结尾时不越界", () => {
    const head = markContext(TEXT, 0, 3);
    expect(head.prefix).toBe("");
    const tail = markContext(TEXT, TEXT.length - 3, TEXT.length);
    expect(tail.suffix).toBe("");
  });

  it("空选区（或只有空白）不生成标记", () => {
    expect(createMark({ text: TEXT, from: 3, to: 3, chapterId: "c1" })).toBeNull();
    expect(createMark({ text: "   ", from: 0, to: 3, chapterId: "c1" })).toBeNull();
  });

  it("标记默认是「改写」意图、待处理状态", () => {
    const mark = makeMark();
    expect(mark.intent).toBe("rewrite");
    expect(mark.status).toBe("pending");
    expect(mark.chapterId).toBe("c1");
  });
});

describe("findMarkRange：正文被编辑后重新定位", () => {
  it("正文没变时按原文定位", () => {
    const range = findMarkRange(TEXT, makeMark());
    expect(range).toEqual({ from: FROM, to: TO });
  });

  it("前面插入了文字（偏移漂移）仍然找得到", () => {
    const edited = `【新增的一行】${TEXT}`;
    const range = findMarkRange(edited, makeMark());
    expect(range).not.toBeNull();
    expect(edited.slice(range!.from, range!.to)).toBe("他慢慢抬起手，举到眼前。");
  });

  it("同一句出现两次时，用上下文定位到标记的那一处", () => {
    const mark = makeMark();
    const edited = `${TEXT}（后面又出现一次）雨落在站台上。他慢慢抬起手，举到眼前。`;
    const range = findMarkRange(edited, mark);
    expect(range).not.toBeNull();
    // 落在第一次出现的位置（标记时的那一处）
    expect(range!.from).toBe(FROM);
  });

  it("被标记的那段文字被改过 → 定位失败（返回 null，交给界面提示确认）", () => {
    const edited = TEXT.replace("他慢慢抬起手，举到眼前。", "他把手抬起来看了看。");
    expect(findMarkRange(edited, makeMark())).toBeNull();
    expect(isLocatable(edited, makeMark())).toBe(false);
  });
});

describe("applyMark / revertMark", () => {
  it("把改写结果写进正文，并返回改动区间", () => {
    const mark = makeMark({ replacement: "他把手举到眼前，停了半息。", status: "suggested" });
    const result = applyMark(TEXT, mark);
    expect(result).not.toBeNull();
    expect(result!.text).toBe(TEXT.replace("他慢慢抬起手，举到眼前。", "他把手举到眼前，停了半息。"));
    expect(result!.text.slice(result!.from, result!.to)).toBe("他把手举到眼前，停了半息。");
  });

  it("改写与原文相同时也不报错（changed 判定放在后端/界面）", () => {
    const mark = makeMark({ replacement: "他慢慢抬起手，举到眼前。" });
    const result = applyMark(TEXT, mark);
    expect(result!.text).toBe(TEXT);
  });

  it("定位失败时不改正文（返回 null）", () => {
    const edited = TEXT.replace("他慢慢抬起手，举到眼前。", "换了别的写法。");
    expect(applyMark(edited, makeMark({ replacement: "x" }))).toBeNull();
  });

  it("可以撤回：把改后的文字换回原文", () => {
    const mark = makeMark({ replacement: "他把手举到眼前，停了半息。" });
    const applied = applyMark(TEXT, mark)!;
    const reverted = revertMark(applied.text, mark);
    expect(reverted).not.toBeNull();
    expect(reverted!.text).toBe(TEXT);
  });
});

describe("refreshMarks：把定位不到的标成 stale，恢复后回到待处理", () => {
  it("正文改动导致失效 → stale；改回来 → 回到 pending", () => {
    const mark = makeMark();
    const broken = refreshMarks("完全不同的正文。", [mark]);
    expect(broken[0].status).toBe("stale");
    const restored = refreshMarks(TEXT, broken);
    expect(restored[0].status).toBe("pending");
  });

  it("已有结果的标记恢复后是 suggested（不用重新处理）", () => {
    const mark = makeMark({ replacement: "改后", status: "stale" });
    const restored = refreshMarks(TEXT, [mark]);
    expect(restored[0].status).toBe("suggested");
  });

  it("已接受/已拒绝的标记不受影响", () => {
    const accepted = makeMark({ status: "accepted" });
    expect(refreshMarks("完全不同的正文。", [accepted])[0].status).toBe("accepted");
  });

  it("没有变化时返回同一个数组（避免无意义重渲染）", () => {
    const marks = [makeMark()];
    expect(refreshMarks(TEXT, marks)).toBe(marks);
  });
});

describe("currentMarkRange：已接受的标记按改写稿定位", () => {
  it("刚接受完，原文已经不在正文里，但按改写稿仍能找到那一段", () => {
    const mark = makeMark({ replacement: "他把手举到眼前，停了半息。", status: "accepted" });
    const applied = applyMark(TEXT, mark)!;
    // 原文已被替换掉：按 quote 已经找不到（这就是"接受完卡片失去锚点"的成因）
    expect(findMarkRange(applied.text, mark)).toBeNull();
    const range = currentMarkRange(applied.text, mark);
    expect(range).not.toBeNull();
    expect(applied.text.slice(range!.from, range!.to)).toBe("他把手举到眼前，停了半息。");
  });

  it("未接受的标记仍然按原文定位", () => {
    const mark = makeMark({ replacement: "改后", status: "suggested" });
    expect(currentMarkRange(TEXT, mark)).toEqual({ from: FROM, to: TO });
  });

  it("接受后用户又改了那段 → 返回 null（不该硬改）", () => {
    const mark = makeMark({ replacement: "他把手举到眼前。", status: "accepted" });
    expect(currentMarkRange("完全换了内容。", mark)).toBeNull();
  });
});

describe("统计与展示辅助", () => {
  it("pendingMarks 只挑待处理/待决定的", () => {
    const marks = [
      makeMark({ status: "pending" }),
      makeMark({ status: "suggested" }),
      makeMark({ status: "accepted" }),
      makeMark({ status: "rejected" }),
      makeMark({ status: "stale" }),
    ];
    expect(pendingMarks(marks)).toHaveLength(2);
  });

  it("markStats 数得清", () => {
    const stats = markStats([
      makeMark({ status: "pending" }),
      makeMark({ status: "suggested" }),
      makeMark({ status: "accepted" }),
      makeMark({ status: "stale" }),
    ]);
    expect(stats).toEqual({ total: 4, pending: 2, accepted: 1, stale: 1 });
  });

  it("短引用压掉换行并截断", () => {
    expect(shortQuote("一\n二  三")).toBe("一 二 三");
    expect(shortQuote("字".repeat(40), 10)).toBe("字".repeat(10) + "…");
  });
});

describe("存储", () => {
  it("按 项目|章节 存取", () => {
    const store = fakeStorage();
    saveMarks("p1", "c1", [makeMark()], store);
    expect(loadMarks("p1", "c1", store)).toHaveLength(1);
    // 别的章节读不到
    expect(loadMarks("p1", "c2", store)).toEqual([]);
    expect(loadMarks("p2", "c1", store)).toEqual([]);
    const raw = JSON.parse(store.dump()["vnss-marks-v1"] ?? "{}");
    expect(Object.keys(raw)).toEqual([chapterKey("p1", "c1")]);
  });

  it("标记清空后不留空壳键", () => {
    const store = fakeStorage();
    saveMarks("p1", "c1", [makeMark()], store);
    saveMarks("p1", "c1", [], store);
    expect(loadMarks("p1", "c1", store)).toEqual([]);
  });

  it("坏 JSON / 坏条目不炸", () => {
    expect(loadMarks("p1", "c1", fakeStorage({ "vnss-marks-v1": "{不是 JSON" }))).toEqual([]);
    const partial = fakeStorage({
      "vnss-marks-v1": JSON.stringify({ "p1|c1": [{ id: "ok", quote: "x" }, { quote: 123 }, null] }),
    });
    const marks = loadMarks("p1", "c1", partial);
    expect(marks).toHaveLength(1);
    expect(marks[0].id).toBe("ok");
  });

  it("storage 不可用时安静返回空数组 / 不抛", () => {
    expect(loadMarks("p1", "c1", null)).toEqual([]);
    expect(() => saveMarks("p1", "c1", [makeMark()], null)).not.toThrow();
  });

  it("每条上限：超出时丢最旧的", () => {
    const store = fakeStorage();
    const marks = Array.from({ length: MAX_MARKS_PER_CHAPTER + 5 }, (_, i) => ({
      ...makeMark(),
      id: `mk-${i}`,
      createdAt: 1000 + i,
    }));
    saveMarks("p1", "c1", marks, store);
    const kept = loadMarks("p1", "c1", store);
    expect(kept).toHaveLength(MAX_MARKS_PER_CHAPTER);
    expect(kept[0].id).toBe("mk-5");
    expect(kept[kept.length - 1].id).toBe(`mk-${MAX_MARKS_PER_CHAPTER + 4}`);
  });
});
