import { describe, expect, it } from "vitest";
import { activeLrcIndex, parseLrc } from "./lrc";

const SAMPLE = `[ti:测试歌曲]
[ar:测试歌手]
[00:01.00]第一句
[00:05.50]第二句
[00:08.00][00:20.00]重复句
[01:30]纯秒行`;

describe("parseLrc", () => {
  it("parses meta tags", () => {
    const r = parseLrc(SAMPLE);
    expect(r.meta.title).toBe("测试歌曲");
    expect(r.meta.artist).toBe("测试歌手");
  });

  it("parses timestamp lines and sorts", () => {
    const r = parseLrc(SAMPLE);
    expect(r.lines.length).toBe(5); // 多时间戳展开为多行
    expect(r.lines[0].time).toBeCloseTo(1, 3);
    expect(r.lines[0].text).toBe("第一句");
    expect(r.lines[1].time).toBeCloseTo(5.5, 3);
    expect(r.lines[2].time).toBeCloseTo(8, 3);
    expect(r.lines[3].time).toBeCloseTo(20, 3);
    expect(r.lines[4].time).toBe(90); // 1:30 → 90s
  });

  it("ignores lines without timestamps and metadata-only input", () => {
    const r = parseLrc("随便写的文字\n[ar:某人]\n");
    expect(r.lines).toEqual([]);
    expect(r.meta.artist).toBe("某人");
  });

  it("skips credit lines with timestamps (作词/作曲/编曲…)", () => {
    const r = parseLrc(
      "[00:00.00]作词：林夕\n" +
        "[00:00.00]作曲：泽野弘之\n" +
        "[00:00.00]编曲：泽野弘之\n" +
        "[00:05.00]第一句真正的歌词\n" +
        "[00:10.00]演唱：某人\n" +
        "[00:15.00]第二句真正的歌词"
    );
    expect(r.lines).toHaveLength(2);
    expect(r.lines[0].text).toBe("第一句真正的歌词");
    expect(r.lines[1].text).toBe("第二句真正的歌词");
  });

  it("skips credit variants: spaced colon / no colon / instrumental", () => {
    const r = parseLrc(
      "[00:00.00]作词 : 林夕\n" +
        "[00:00.00]作曲:泽野弘之\n" +
        "[00:00.00]编曲 泽野弘之\n" +
        "[00:00.00]演唱：某人\n" +
        "[00:00.00]（前奏）\n" +
        "[00:03.00]终于开始唱了\n" +
        "[00:06.00]OP\n" +
        "[00:09.00]间奏\n" +
        "[00:12.00]还在唱\n"
    );
    expect(r.lines.map((l) => l.text)).toEqual(["终于开始唱了", "还在唱"]);
  });

  it("keeps lyric lines that merely mention 词/曲 inside", () => {
    const r = parseLrc("[00:05.00]这首歌的歌词写得真好\n[00:10.00]作曲的人不懂我");
    expect(r.lines).toHaveLength(2);
  });

  it("empty input returns empty", () => {
    const r = parseLrc("");
    expect(r.lines).toEqual([]);
  });

  it("applies [offset:] meta shift to all lines", () => {
    // 负偏移 = 歌词提前 500ms
    const r = parseLrc("[offset:-500]\n[00:02.00]提前的歌词\n[00:10.00]后一句");
    expect(r.meta.offsetMs).toBe(-500);
    expect(r.lines[0].time).toBeCloseTo(1.5, 3);
    expect(r.lines[1].time).toBeCloseTo(9.5, 3);
    // 正偏移 = 延后
    const r2 = parseLrc("[offset:1000]\n[00:02.00]延后的歌词");
    expect(r2.lines[0].time).toBeCloseTo(3, 3);
  });
});

describe("activeLrcIndex", () => {
  const r = parseLrc(SAMPLE);
  it("returns -1 before first line", () => {
    expect(activeLrcIndex(r.lines, 0.5)).toBe(-1);
  });
  it("returns current line index", () => {
    expect(activeLrcIndex(r.lines, 3)).toBe(0);
    expect(activeLrcIndex(r.lines, 6)).toBe(1);
    expect(activeLrcIndex(r.lines, 25)).toBe(3);
    expect(activeLrcIndex(r.lines, 999)).toBe(4);
  });
});
