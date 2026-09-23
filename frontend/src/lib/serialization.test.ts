import { describe, expect, it } from "vitest";
import type { WritingActivityDay } from "../api/projects";
import type { SceneChapter } from "../types/vn";
import {
  dayKey,
  paceEstimate,
  publishState,
  serializationStats,
  streakInfo,
  updateCalendar,
} from "./serialization";

/** 造一天的写作记录（净增 = added - removed） */
function day(date: string, added: number, removed = 0): WritingActivityDay {
  return { date, added, removed, net: added - removed, edits: 1 };
}

function chapter(id: string, prose: string, publishedAt?: string): SceneChapter {
  return { id, title: `第 ${id} 章`, blocks: [], prose, publishedAt };
}

// 固定"今天"，否则测试会随运行日期漂移
const NOW = new Date("2026-03-10T21:00:00");

const dateOf = (offset: number): string => {
  const d = new Date(NOW.getTime());
  d.setDate(d.getDate() + offset);
  return dayKey(d);
};

describe("dayKey / todayKey", () => {
  it("用本地时区，不用 UTC（晚上写的东西不会算到明天）", () => {
    const late = new Date("2026-03-10T23:30:00");
    expect(dayKey(late)).toBe("2026-03-10");
  });

  it("补零", () => {
    expect(dayKey(new Date("2026-01-05T08:00:00"))).toBe("2026-01-05");
  });
});

describe("streakInfo 连续更新", () => {
  it("今天写了：从今天往回数", () => {
    const info = streakInfo(
      [day(dateOf(0), 800), day(dateOf(-1), 500), day(dateOf(-2), 300)],
      NOW
    );
    expect(info.current).toBe(3);
    expect(info.wroteToday).toBe(true);
    expect(info.lastWriteDate).toBe(dateOf(0));
  });

  it("今天还没写但昨天写了 → 连续不归零（早上打开工具不该看到「连续 0 天」）", () => {
    const info = streakInfo([day(dateOf(-1), 500), day(dateOf(-2), 300)], NOW);
    expect(info.current).toBe(2);
    expect(info.wroteToday).toBe(false);
  });

  it("昨天也没写 → 连续为 0", () => {
    expect(streakInfo([day(dateOf(-2), 500)], NOW).current).toBe(0);
  });

  it("净增为 0 或负数不算「写了」（删字不算更新）", () => {
    expect(streakInfo([day(dateOf(0), 500, 500)], NOW).current).toBe(0);
    expect(streakInfo([day(dateOf(0), 100, 400)], NOW).wroteToday).toBe(false);
  });

  it("最长连续取历史里最长的那一段（中间断开要重新数）", () => {
    const info = streakInfo(
      [
        day(dateOf(-10), 100),
        day(dateOf(-9), 100),
        day(dateOf(-8), 100),
        day(dateOf(-7), 100),
        // 断开一天
        day(dateOf(-5), 100),
        day(dateOf(-4), 100),
      ],
      NOW
    );
    expect(info.longest).toBe(4);
    expect(info.current).toBe(0);
    expect(info.totalDays).toBe(6);
  });

  it("没有任何记录：全 0 且不抛异常", () => {
    const info = streakInfo([], NOW);
    expect(info).toEqual({
      current: 0,
      longest: 0,
      lastWriteDate: "",
      wroteToday: false,
      totalDays: 0,
    });
  });

  it("日期乱序也能算对", () => {
    const info = streakInfo(
      [day(dateOf(-2), 100), day(dateOf(0), 100), day(dateOf(-1), 100)],
      NOW
    );
    expect(info.current).toBe(3);
    expect(info.lastWriteDate).toBe(dateOf(0));
  });
});

describe("updateCalendar 更新日历", () => {
  it("按周分列，最后一列是本週、今天落在它对应的星期几那一格", () => {
    const cols = updateCalendar([], 4, NOW); // 2026-03-10 是周二
    expect(cols).toHaveLength(4);
    expect(cols[0]).toHaveLength(7);
    const todayIndex = (NOW.getDay() + 6) % 7; // 周二 → 1
    expect(cols[3][todayIndex].today).toBe(true);
    // 同一格里只有今天这一格是 today
    expect(cols.flat().filter((c) => c.today)).toHaveLength(1);
  });

  it("每一列都是周一到周日", () => {
    const cols = updateCalendar([], 2, NOW);
    for (const col of cols) {
      col.forEach((cell, i) => {
        const d = new Date(`${cell.date}T00:00:00`);
        expect((d.getDay() + 6) % 7, `${cell.date} 应该是第 ${i} 天`).toBe(i);
      });
    }
  });

  it("有净增的日期给色阶，删字的日期有记录但色阶为 0", () => {
    const cols = updateCalendar(
      [day(dateOf(0), 1000), day(dateOf(-1), 250, 500)],
      4,
      NOW
    );
    const flat = cols.flat();
    const today = flat.find((c) => c.today)!;
    const yesterday = flat.find((c) => c.date === dateOf(-1))!;
    expect(today.level).toBe(4);
    expect(today.net).toBe(1000);
    expect(yesterday.hasRecord).toBe(true);
    expect(yesterday.level).toBe(0);
    expect(yesterday.net).toBe(-250);
  });

  it("没有记录的日期 hasRecord=false、net=0", () => {
    const today = updateCalendar([], 4, NOW).flat().find((c) => c.today)!;
    expect(today.hasRecord).toBe(false);
    expect(today.net).toBe(0);
  });

  it("未来日期被标记出来（画格子要留白）", () => {
    const flat = updateCalendar([], 4, NOW).flat();
    const future = flat.filter((c) => c.future);
    expect(future.length).toBeGreaterThan(0);
    expect(future.every((c) => c.date > dayKey(NOW))).toBe(true);
  });

  it("最多 4 级色阶，且按当期最大值归一", () => {
    const flat = updateCalendar(
      [day(dateOf(0), 400), day(dateOf(-1), 200), day(dateOf(-2), 100)],
      2,
      NOW
    ).flat();
    for (const cell of flat) {
      expect(cell.level).toBeGreaterThanOrEqual(0);
      expect(cell.level).toBeLessThanOrEqual(4);
    }
    expect(flat.find((c) => c.net === 400)!.level).toBe(4);
  });
});

describe("publishState 与 serializationStats", () => {
  it("有发布时间 = 已发布；写了没发 = 存稿；没写 = 空章", () => {
    expect(publishState(chapter("1", "写了两句。", "2026-03-01T00:00:00Z"))).toBe("published");
    expect(publishState(chapter("2", "写了两句。"))).toBe("draft");
    expect(publishState(chapter("3", ""))).toBe("empty");
  });

  it("只有结构标记（没正文）算空章，不算存稿", () => {
    const onlyLabel: SceneChapter = {
      id: "x",
      title: "空",
      blocks: [{ type: "label", id: "start", name: "start" }],
      prose: "",
    };
    expect(publishState(onlyLabel)).toBe("empty");
  });

  it("统计已发布/存稿/空章与各自字数", () => {
    const stats = serializationStats([
      chapter("1", "一二三。", "2026-03-01T00:00:00Z"),
      chapter("2", "四五六。"),
      chapter("3", ""),
    ]);
    expect(stats.total).toBe(3);
    expect(stats.published).toBe(1);
    expect(stats.drafts).toBe(1);
    expect(stats.empty).toBe(1);
    expect(stats.publishedWords).toBe(3); // 「一二三。」按汉字逐字算是 3 字
    expect(stats.draftWords).toBe(3);
  });

  it("下一章待发布 = 第一个存稿章", () => {
    const stats = serializationStats([
      chapter("1", "已发。", "2026-03-01T00:00:00Z"),
      chapter("2", "存稿一。"),
      chapter("3", "存稿二。"),
    ]);
    expect(stats.nextToPublish?.id).toBe("2");
  });

  it("全部发完 / 空工程时 nextToPublish 为 null", () => {
    expect(serializationStats([chapter("1", "已发。", "2026-03-01T00:00:00Z")]).nextToPublish).toBeNull();
    expect(serializationStats([]).nextToPublish).toBeNull();
    expect(serializationStats([]).total).toBe(0);
  });

  it("脚本块工程也数得上（没有 prose 时数 blocks）", () => {
    const scripted: SceneChapter = {
      id: "s",
      title: "脚本章",
      blocks: [
        { type: "narration", text: "雨停了。" },
        { type: "dialogue", characterId: "a", text: "走吧。" },
      ],
    };
    expect(countOf(scripted)).toBeGreaterThan(0);
    expect(publishState(scripted)).toBe("draft");
  });
});

function countOf(ch: SceneChapter): number {
  return serializationStats([ch]).draftWords;
}

describe("paceEstimate 节奏估算", () => {
  it("样本足够（≥3 个有产出的天）时给出日均与天数", () => {
    const est = paceEstimate(
      [day(dateOf(-1), 600), day(dateOf(-2), 900), day(dateOf(-3), 300)],
      1200
    );
    expect(est).toEqual({ perDay: 600, days: 2 });
  });

  it("样本不足时返回 null（编一个数字比不给更糟）", () => {
    expect(paceEstimate([day(dateOf(-1), 600), day(dateOf(-2), 300)], 1200)).toBeNull();
    expect(paceEstimate([], 1200)).toBeNull();
  });

  it("目标已达成（剩余 0）时不给估算", () => {
    expect(
      paceEstimate([day(dateOf(-1), 600), day(dateOf(-2), 600), day(dateOf(-3), 600)], 0)
    ).toBeNull();
  });

  it("删字的记录不参与日均（净增≤0 的天不算产出）", () => {
    const est = paceEstimate(
      [
        day(dateOf(-1), 600),
        day(dateOf(-2), 600),
        day(dateOf(-3), 600),
        // 这一天的净增是 -300，不算"有产出"
        day(dateOf(-4), 500, 800),
      ],
      600
    );
    expect(est?.perDay).toBe(600);
    expect(est?.days).toBe(1);
  });
});
