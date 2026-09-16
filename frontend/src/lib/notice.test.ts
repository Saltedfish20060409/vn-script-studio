import { describe, expect, it } from "vitest";
import {
  announcementBadge,
  formatNoticeDate,
  resolveAnnouncements,
  type NoticePayload,
} from "./notice";

const A = (version: number, title = `更新 v${version}`) => ({
  version,
  title,
  updatedAt: "2026-09-16",
  sections: [{ heading: "标题", body: "正文" }],
});

describe("resolveAnnouncements", () => {
  it("新版后端：按版本倒序排列", () => {
    const payload: NoticePayload = { announcements: [A(5, "欢迎使用"), A(6), A(4)] };
    const list = resolveAnnouncements(payload);
    expect(list.map((a) => a.version)).toEqual([6, 5, 4]);
  });

  it("旧后端（只有顶层字段）也能渲染成一条", () => {
    const list = resolveAnnouncements({
      version: 5,
      title: "欢迎使用 VN Script Studio 🎬",
      updatedAt: "2026-09-07",
      sections: [{ heading: "欢迎", body: "你好" }],
    });
    expect(list).toHaveLength(1);
    expect(list[0].version).toBe(5);
    expect(list[0].sections[0].body).toBe("你好");
  });

  it("空内容 / 坏数据不会变成空白条目", () => {
    expect(resolveAnnouncements(null)).toEqual([]);
    expect(resolveAnnouncements({})).toEqual([]);
    expect(
      resolveAnnouncements({ announcements: [{ version: 0, title: "x", updatedAt: "", sections: [] }] })
    ).toEqual([]);
    expect(
      resolveAnnouncements({
        announcements: [
          A(6),
          { version: 7, title: "没内容的", updatedAt: "", sections: [] },
        ],
      }).map((a) => a.version)
    ).toEqual([6]);
  });

  it("不改动入参数组顺序（就地排序会污染调用方）", () => {
    const raw = [A(5), A(6)];
    resolveAnnouncements({ announcements: raw });
    expect(raw.map((a) => a.version)).toEqual([5, 6]);
  });
});

describe("announcementBadge / formatNoticeDate", () => {
  it("最新一版带「最新」标记，更新日志和欢迎公告用不同前缀", () => {
    expect(announcementBadge(A(6), true)).toBe("更新 v6 · 最新");
    expect(announcementBadge(A(6), false)).toBe("更新 v6");
    expect(announcementBadge(A(5, "欢迎使用 VN Script Studio 🎬"), false)).toBe("v5");
  });

  it("日期异常时兜底不显示 undefined", () => {
    expect(formatNoticeDate("2026-09-16")).toBe("2026-09-16");
    expect(formatNoticeDate("2026-09-16T12:00:00Z")).toBe("2026-09-16");
    expect(formatNoticeDate("")).toBe("—");
  });
});
