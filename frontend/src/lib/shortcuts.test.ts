import { describe, expect, it } from "vitest";
import GUIDE_MD from "./guide.md?raw";
import { HELP_SHORTCUTS } from "./helpContent";
import {
  MENU_KEYS_HINT,
  MENU_KEYS_SHORT,
  MENU_MNEMONICS,
  markKeyboardHintSeen,
  menuKeys,
  shouldShowKeyboardHint,
} from "./shortcuts";

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

describe("快捷键数据源", () => {
  it("四个菜单各有一个助记键，且不重复", () => {
    const letters = MENU_MNEMONICS.map((m) => m.letter);
    expect(new Set(letters).size).toBe(4);
    expect(MENU_MNEMONICS.map((m) => m.label)).toEqual(["文件", "开始", "审阅", "视图"]);
  });

  it("显示串由字母推导（不另写一份，避免印的和绑的不一样）", () => {
    for (const m of MENU_MNEMONICS) {
      expect(menuKeys(m)).toBe(`Alt+${m.letter.toUpperCase()}`);
    }
    expect(MENU_KEYS_SHORT).toBe("Alt+F/E/R/V");
    expect(MENU_KEYS_HINT).toContain(MENU_KEYS_SHORT);
    expect(MENU_KEYS_HINT).toContain("↑↓");
    expect(MENU_KEYS_HINT).toContain("Esc");
  });
});

describe("帮助页的「键盘快捷键」一节", () => {
  it("菜单助记键与写作快捷键都在里面，且没有重复的键", () => {
    const keys = HELP_SHORTCUTS.map((s) => s.keys);
    for (const m of MENU_MNEMONICS) expect(keys).toContain(menuKeys(m));
    for (const k of ["Ctrl+F", "Ctrl+M", "Ctrl+\\"]) expect(keys).toContain(k);
    expect(new Set(keys).size).toBe(keys.length);
    for (const s of HELP_SHORTCUTS) expect(s.what.length).toBeGreaterThan(0);
  });
});

/**
 * 使用指南（/guide 那一篇 markdown）与代码里的键位对齐。
 *
 * 为什么不靠人记得改：这份文档是**用户真会去查**的地方，
 * 写着一个按了没反应的键，比不写更糟（用户会以为自己按错了）。
 */
describe("使用指南与键位对齐", () => {
  it("有一节「键盘快捷键」", () => {
    expect(GUIDE_MD).toContain("## 键盘快捷键");
  });

  it("代码里认的每个键，指南里都写了", () => {
    for (const s of HELP_SHORTCUTS) {
      expect(GUIDE_MD.includes(s.keys), `指南里缺了 ${s.keys}`).toBe(true);
    }
  });
});

describe("写作页一次性提示条", () => {
  it("没关过就显示，关过就不再显示", () => {
    const store = fakeStorage();
    expect(shouldShowKeyboardHint(store)).toBe(true);
    markKeyboardHintSeen(store);
    expect(shouldShowKeyboardHint(store)).toBe(false);
  });

  it("storage 不可用（隐私模式）时安静地不显示，也不报错", () => {
    expect(shouldShowKeyboardHint(null)).toBe(false);
    expect(() => markKeyboardHintSeen(null)).not.toThrow();
  });
});
