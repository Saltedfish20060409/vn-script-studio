import { useState } from "react";
import {
  MENU_KEYS_HINT,
  markKeyboardHintSeen,
  shouldShowKeyboardHint,
} from "../lib/shortcuts";
import styles from "./ShortcutHintBar.module.css";

/**
 * 写作页的「菜单支持键盘」一次性提示条。
 *
 * 起因是个真问题：`Alt+F/E/R/V`、`↑↓`、`Esc` 上一版只写进了代码和 `title`——
 * 界面上一个字都没说，等于给内部人用的暗号。菜单标题上现在常驻助记键，
 * 但"打开之后还能用 ↑↓ 和 Esc"这件事在标题上放不下，所以进这里说一句。
 *
 * 与「三步上手」同一套机制：只出现一次，关掉就记在本机，不再出现。
 * 每次进写作页都弹一条说明，会变成噪音——一次性提示的价值全在"只出现一次"。
 */
export function ShortcutHintBar() {
  const [open, setOpen] = useState(() => shouldShowKeyboardHint());
  if (!open) return null;

  return (
    <div
      className={styles.bar}
      role="region"
      aria-label="键盘快捷键提示"
      data-testid="shortcut-hint"
    >
      <span className={styles.title}>键盘</span>
      <span className={styles.text}>{MENU_KEYS_HINT}</span>
      <span className={styles.more}>
        其余的（查找 / 标记批改 / 专注）在「文件 → 帮助 / FAQ」的「键盘快捷键」一节
      </span>
      <button
        type="button"
        className={styles.close}
        data-testid="shortcut-hint-close"
        aria-label="不再显示"
        onClick={() => {
          markKeyboardHintSeen();
          setOpen(false);
        }}
      >
        ×
      </button>
    </div>
  );
}
