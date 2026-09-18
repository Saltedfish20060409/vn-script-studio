import { describe, expect, it } from "vitest";
import {
  MAX_CARET_AGE_MS,
  MAX_CARET_ENTRIES,
  MIN_CARET_OFFSET,
  caretKey,
  loadCaretMap,
  putCaret,
  readCaret,
  rememberCaret,
  saveCaretMap,
} from "./caretMemory";

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

const NOW = new Date("2026-09-18T12:00:00Z").getTime();

describe("caretKey", () => {
  it("同一章的两份稿（剧本 / RPY）分开记", () => {
    expect(caretKey("p1", "c1", "prose")).not.toBe(caretKey("p1", "c1", "rpy"));
  });
});

describe("readCaret：什么时候该提示「上次停在这里」", () => {
  const key = caretKey("p1", "c1", "prose");

  it("刚记下的位置能读出来", () => {
    const map = putCaret({}, key, 120, NOW - 1000);
    expect(readCaret(map, key, { textLength: 500, now: NOW })).toBe(120);
  });

  it("过期（超过一个月）不再提示", () => {
    const map = putCaret({}, key, 120, NOW - MAX_CARET_AGE_MS - 1);
    expect(readCaret(map, key, { textLength: 500, now: NOW })).toBeNull();
  });

  it("停在开头几个字符不算停笔位置", () => {
    const map = putCaret({}, key, MIN_CARET_OFFSET - 1, NOW - 1000);
    expect(readCaret(map, key, { textLength: 500, now: NOW })).toBeNull();
  });

  it("正文变短、位置越界 → 不提示（别把光标塞到不存在的地方）", () => {
    const map = putCaret({}, key, 900, NOW - 1000);
    expect(readCaret(map, key, { textLength: 300, now: NOW })).toBeNull();
    // 正好在末尾是允许的
    expect(readCaret(map, key, { textLength: 900, now: NOW })).toBe(900);
  });

  it("坏的记录（NaN / 缺字段）当作没有", () => {
    const map = { [key]: { offset: Number.NaN, at: NOW } } as never;
    expect(readCaret(map, key, { textLength: 500, now: NOW })).toBeNull();
  });

  it("换了模式或换了章就没有记录", () => {
    const map = putCaret({}, key, 120, NOW - 1000);
    expect(readCaret(map, caretKey("p1", "c1", "rpy"), { textLength: 500, now: NOW })).toBeNull();
    expect(readCaret(map, caretKey("p1", "c2", "prose"), { textLength: 500, now: NOW })).toBeNull();
    expect(readCaret(map, caretKey("p2", "c1", "prose"), { textLength: 500, now: NOW })).toBeNull();
  });
});

describe("putCaret：有上限，超了丢最旧的", () => {
  it("条目数不超过上限，且保留最新的那些", () => {
    let map = {};
    for (let i = 0; i < MAX_CARET_ENTRIES + 10; i += 1) {
      map = putCaret(map, `k${i}`, 10 + i, NOW + i);
    }
    const keys = Object.keys(map);
    expect(keys).toHaveLength(MAX_CARET_ENTRIES);
    // 最新的那条一定还在，最早的已经被丢掉
    expect(keys).toContain(`k${MAX_CARET_ENTRIES + 9}`);
    expect(keys).not.toContain("k0");
  });

  it("偏移取整并夹到非负", () => {
    const map = putCaret({}, "k", -12.7, NOW);
    expect(map.k.offset).toBe(0);
  });
});

describe("localStorage 读写", () => {
  it("存了能读回来", () => {
    const store = fakeStorage();
    saveCaretMap(putCaret({}, "k", 42, NOW), store);
    expect(loadCaretMap(store).k).toEqual({ offset: 42, at: NOW });
  });

  it("坏 JSON / 坏条目不会炸，直接当空表", () => {
    expect(loadCaretMap(fakeStorage({ "vnss-caret-memory-v1": "{不是 JSON" }))).toEqual({});
    const partial = fakeStorage({
      "vnss-caret-memory-v1": JSON.stringify({ good: { offset: 1, at: 2 }, bad: { offset: "x" } }),
    });
    expect(Object.keys(loadCaretMap(partial))).toEqual(["good"]);
  });

  it("storage 不可用时安静地返回空表 / 不抛", () => {
    expect(loadCaretMap(null)).toEqual({});
    expect(() => saveCaretMap({}, null)).not.toThrow();
  });

  it("rememberCaret 一步到位：写到 localStorage 且能被 readCaret 读到", () => {
    const store = fakeStorage();
    // @ts-expect-error 测试里只关心 localStorage 这一条路径
    globalThis.window = { localStorage: store };
    rememberCaret("p1", "c1", "prose", 321);
    const map = loadCaretMap(store);
    expect(readCaret(map, caretKey("p1", "c1", "prose"), { textLength: 999 })).toBe(321);
  });
});
