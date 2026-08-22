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
