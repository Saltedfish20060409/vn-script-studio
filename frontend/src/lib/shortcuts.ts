/**
 * 键盘快捷键的**唯一数据源**。
 *
 * 为什么收在一处：这些键以前只活在代码和各自的 `title` 里——等于给内部人用的暗号
 * （用户原话："没有在界面上告诉任何人"）。现在同一批键要在三处露脸：
 * ① 顶栏菜单标题上的助记键（桌面软件的惯例：常驻可见）；
 * ② 写作页的一次性提示条；
 * ③ 帮助 / FAQ 与使用指南的「键盘快捷键」一节。
 * 各写一份必然漂移——显示的是一个键、真正生效的是另一个，比不显示更糟。
 * 所以这里同时供"显示"和"绑定"用（见 StudioRibbon 的 HOTKEY 由 MENU_MNEMONICS 推导）。
 */

export type MenuId = "file" | "home" | "review" | "view";

export type MenuMnemonic = {
  id: MenuId;
  /** 菜单标题（与 StudioRibbon 上显示的一致） */
  label: string;
  /** Alt+ 后面那个字母（小写，比较用） */
  letter: string;
};

/**
 * 四个菜单的助记键。
 *
 * `开始` 用 E 而不是 H：Word 里「开始」是 Alt+H，但那一栏在这里装的其实是
 * "写作方式 / 查找 / 专注"这些**编辑类**动作，用 E（Edit）更好记，
 * 而且这一版已经在 e2e 里钉住了 Alt+E（改字母要同时改用例与文案，不值得）。
 */
export const MENU_MNEMONICS: ReadonlyArray<MenuMnemonic> = [
  { id: "file", label: "文件", letter: "f" },
  { id: "home", label: "开始", letter: "e" },
  { id: "review", label: "审阅", letter: "r" },
  { id: "view", label: "视图", letter: "v" },
];

/** `Alt+F` 这样的显示串（从 letter 推导，不另写一份） */
export function menuKeys(m: MenuMnemonic): string {
  return `Alt+${m.letter.toUpperCase()}`;
}

/** 一句里要列全四个键时用（`Alt+F/E/R/V`） */
export const MENU_KEYS_SHORT = `Alt+${MENU_MNEMONICS.map((m) =>
  m.letter.toUpperCase()
).join("/")}`;

/** 打开菜单之后的键盘操作（三个菜单都一样，写成一句省地方） */
export const MENU_NAV_HINT = "↑↓ 选择、Esc 关闭";

export type Shortcut = { keys: string; what: string };

/**
 * 写作页里真正用得到的几个键。
 *
 * 只放"日常会按到"的：查找、标记批改、专注。
 * 地图画笔的 E、Ctrl+Z 这类属于各自面板（那些面板里已经写在按钮上），不在这里重复。
 */
export const WRITE_SHORTCUTS: ReadonlyArray<Shortcut> = [
  { keys: "Ctrl+F", what: "查找 / 替换（浏览器自带的搜不到稿纸里的正文）" },
  { keys: "Ctrl+M", what: "把选中的一段标成「要改」，随后在它旁边直接处理" },
  { keys: "Ctrl+\\", what: "专注写作：全屏只留稿子，再按一次退出" },
];

/** 写作页一次性提示条的那一句（只讲菜单键盘，Ctrl 那些进帮助页） */
export const MENU_KEYS_HINT = `菜单支持键盘：${MENU_KEYS_SHORT} 开菜单、${MENU_NAV_HINT}`;

const HINT_SEEN_KEY = "vnss-keyboard-hint-v1";

/**
 * 写作页提示条要不要显示：只显示一次（localStorage 记住）。
 * 跟桌面小抄 / 三步上手同一套机制——一次性提示的价值全在"只出现一次"。
 */
export function shouldShowKeyboardHint(
  storage?: Pick<Storage, "getItem"> | null
): boolean {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  if (!store) return false;
  try {
    return store.getItem(HINT_SEEN_KEY) !== "1";
  } catch {
    return false;
  }
}

/** 关掉就永久关掉（同一个浏览器不再出现）。 */
export function markKeyboardHintSeen(
  storage?: Pick<Storage, "setItem"> | null
): void {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  try {
    store?.setItem(HINT_SEEN_KEY, "1");
  } catch {
    /* 隐私模式下写不进去也不该崩 */
  }
}
