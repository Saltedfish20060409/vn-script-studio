import { describe, expect, it } from "vitest";
import {
  BOOT_TOTAL_MS,
  DESKTOP_TIPS,
  buildDesktopIcons,
  formatClock,
  formatClockDate,
  formatRelativeTime,
  isDesktopViewport,
  markDesktopTipsSeen,
  shouldPlayBoot,
  shouldShowDesktop,
  shouldShowDesktopTips,
} from "./desktopView";

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

describe("shouldShowDesktop", () => {
  it("选了桌面视图且屏幕够宽才显示", () => {
    expect(shouldShowDesktop({ view: "desktop", width: 1440 })).toBe(true);
    expect(shouldShowDesktop({ view: "studio", width: 1440 })).toBe(false);
  });

  it("窄屏一律回工作台（触屏没有双击/右键，桌面比喻只会更难用）", () => {
    expect(shouldShowDesktop({ view: "desktop", width: 375 })).toBe(false);
    expect(shouldShowDesktop({ view: "desktop", width: 719 })).toBe(false);
    expect(isDesktopViewport(720)).toBe(true);
  });
});

describe("buildDesktopIcons", () => {
  const projects = [
    { id: "p1", title: "雨夜车站" },
    { id: "p2", title: "异界快递" },
    { id: "p3", title: "" },
  ];
  // 与 StudioApp 的 desktopApps 保持一致：只有「AI 责编」这类常用应用声明 onDesktop，
  // 剧本库 / 系统设置 / 帮助 / 公告都只在开始菜单里。
  const apps = [
    { id: "library", label: "剧本库", glyph: "🗂️" },
    { id: "agent", label: "AI 责编", glyph: "🧠", onDesktop: true },
    { id: "settings", label: "系统设置", glyph: "⚙️" },
    { id: "help", label: "帮助 / FAQ", glyph: "❓" },
    { id: "notice", label: "更新公告", glyph: "📢" },
  ];

  it("最近项目在前，标题为空时给个兜底名字", () => {
    const icons = buildDesktopIcons({ projects, apps });
    expect(icons.slice(0, 3).map((i) => i.label)).toEqual(["雨夜车站", "异界快递", "未命名剧本"]);
    expect(icons[0].id).toBe("project:p1");
    expect(icons[0].kind).toBe("project");
  });

  it("项目很多时只取前 N 个，并补一个「更多剧本」入口（不能有剧本没入口）", () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ id: `p${i}`, title: `T${i}` }));
    const icons = buildDesktopIcons({ projects: many, apps: [], maxProjects: 4 });
    expect(icons).toHaveLength(4 + 1 + 1); // 前 4 个 + 新建 + 更多剧本
    expect(icons[4].id).toBe("action:new");
    const more = icons[5];
    expect(more.id).toBe("action:more");
    expect(more.label).toContain("30");
  });

  it("剧本没超过上限时不出现「更多剧本」", () => {
    const labels = buildDesktopIcons({ projects, apps }).map((i) => i.id);
    expect(labels).not.toContain("action:more");
  });

  it("只有声明 onDesktop 的应用上桌面（剧本库/设置/帮助/公告都只在开始菜单）", () => {
    const labels = buildDesktopIcons({ projects, apps }).map((i) => i.label);
    expect(labels).not.toContain("剧本库");
    expect(labels).not.toContain("系统设置");
    expect(labels).not.toContain("帮助 / FAQ");
    expect(labels).not.toContain("更新公告");
    // 声明了 onDesktop 的应用才上桌面
    expect(labels).toContain("AI 责编");
  });

  it("新建剧本始终在桌面上", () => {
    const ids = buildDesktopIcons({ projects: [], apps: [] }).map((i) => i.id);
    expect(ids).toContain("action:new");
  });

  it("每个图标都有提示文案（任务栏要显示「双击某某」）", () => {
    for (const icon of buildDesktopIcons({ projects, apps })) {
      expect(icon.hint).toContain("双击");
    }
  });

  it("剧本图标带章数角标与「最后修改」提示（桌面要能一眼看出进度）", () => {
    const now = new Date("2026-09-17T12:00:00Z");
    const icons = buildDesktopIcons({
      projects: [
        { id: "p1", title: "雨夜车站", chapters: 12, updatedAt: "2026-09-17T09:00:00Z" },
        { id: "p2", title: "空本子", chapters: 0, updatedAt: "2026-09-10T09:00:00Z" },
        { id: "p3", title: "未知章数" },
      ],
      apps: [],
      now,
    });
    expect(icons[0].badge).toBe("12 章");
    expect(icons[1].badge).toBe("空");
    // 没有章数信息就不画角标（别误导成 0 章）
    expect(icons[2].badge).toBeUndefined();
    expect(icons[0].hint).toContain("共 12 章");
    expect(icons[0].hint).toContain("最后修改 3 小时前");
    expect(icons[0].hint).toContain("右键可重命名");
    expect(icons[1].hint).toContain("还没建章节");
  });
});

describe("formatRelativeTime", () => {
  const now = new Date("2026-09-17T12:00:00Z");

  it("分档：刚刚 / 分钟 / 小时 / 昨天 / 天 / 具体日期", () => {
    expect(formatRelativeTime("2026-09-17T11:59:30Z", now)).toBe("刚刚");
    expect(formatRelativeTime("2026-09-17T11:30:00Z", now)).toBe("30 分钟前");
    expect(formatRelativeTime("2026-09-17T08:00:00Z", now)).toBe("4 小时前");
    expect(formatRelativeTime("2026-09-16T11:00:00Z", now)).toBe("昨天");
    expect(formatRelativeTime("2026-09-14T11:00:00Z", now)).toBe("3 天前");
    expect(formatRelativeTime("2026-08-01T11:00:00Z", now)).toBe("2026/8/1");
  });

  it("时钟偏差导致的「未来时间」显示刚刚，不出现负数", () => {
    expect(formatRelativeTime("2026-09-17T12:05:00Z", now)).toBe("刚刚");
  });

  it("坏时间字符串返回空串（不显示 NaN 天前）", () => {
    expect(formatRelativeTime("不是时间", now)).toBe("");
  });
});

describe("时钟", () => {
  it("补零到 HH:MM", () => {
    expect(formatClock(new Date(2026, 8, 16, 9, 5))).toBe("09:05");
    expect(formatClock(new Date(2026, 8, 16, 23, 59))).toBe("23:59");
  });

  it("日期用本地时间，不出现 UTC 偏移错位", () => {
    expect(formatClockDate(new Date(2026, 8, 16, 0, 30))).toBe("2026/9/16");
  });
});

describe("shouldPlayBoot", () => {
  it("同一会话只放一次（登录页来回跳不该反复开机）", () => {
    const store = fakeStorage();
    expect(shouldPlayBoot({ storage: store })).toBe(true);
    expect(shouldPlayBoot({ storage: store })).toBe(false);
  });

  it("用户要求减少动效时直接跳过", () => {
    const store = fakeStorage();
    expect(shouldPlayBoot({ storage: store, reducedMotion: true })).toBe(false);
    expect(store.dump()).toEqual({});
  });

  it("storage 不可用（隐私模式）时仍然放一次，不报错", () => {
    expect(shouldPlayBoot({ storage: null })).toBe(true);
  });

  it("开机时长要短——比喻要像，但不能真让人等", () => {
    expect(BOOT_TOTAL_MS).toBeLessThanOrEqual(2000);
  });
});

describe("桌面小抄（一次性引导）", () => {
  it("没看过就显示，看过就不再显示", () => {
    const store = fakeStorage();
    expect(shouldShowDesktopTips({ storage: store })).toBe(true);
    markDesktopTipsSeen(store);
    expect(shouldShowDesktopTips({ storage: store })).toBe(false);
  });

  it("打开剧本窗口时不显示（那时用户要用工作台，别挡着）", () => {
    const store = fakeStorage();
    expect(shouldShowDesktopTips({ storage: store, scriptOpen: true })).toBe(false);
  });

  it("storage 不可用时安静地不显示（隐私模式）", () => {
    expect(shouldShowDesktopTips({ storage: null })).toBe(false);
    expect(() => markDesktopTipsSeen(null)).not.toThrow();
  });

  it("四条要点要讲清：双击打开 / 右键菜单 / 开始菜单 / 座位与复位", () => {
    expect(DESKTOP_TIPS).toHaveLength(4);
    const text = DESKTOP_TIPS.join("\n");
    expect(text).toContain("双击");
    expect(text).toContain("右键");
    expect(text).toContain("开始");
    // 收拾桌面：两条各管一件事（排列图标 / 关掉所有窗口），名字不能含糊
    expect(text).toContain("排列图标");
    expect(text).toContain("关掉所有窗口");
    expect(text).not.toContain("重置桌面布局");
  });
});
