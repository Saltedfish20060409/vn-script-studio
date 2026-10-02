/**
 * 写作区 → Agent 的选区快照策略。
 *
 * 浏览器在焦点离开 textarea 时会折叠 DOM 选区；若立刻把空选区写进 React state，
 * Agent 侧「选区 N 字」与改写/审稿作用域会一起丢。规则：
 *
 * - DOM 有非空选区 → 更新快照
 * - DOM 折叠且编辑器仍聚焦 → 用户点了光标，清空快照
 * - DOM 折叠且编辑器未聚焦 → 焦点已去 Agent 等处，**保留**快照
 */

export type SelectionRange = { from: number; to: number };

export type SelectionSnapshot = {
  text: string;
  range: SelectionRange | null;
};

export function nextSelectionSnapshot(opts: {
  prev: SelectionSnapshot;
  domFrom: number;
  domTo: number;
  value: string;
  editorFocused: boolean;
}): SelectionSnapshot {
  const { prev, domFrom, domTo, value, editorFocused } = opts;
  if (domFrom < domTo) {
    return {
      text: value.slice(domFrom, domTo),
      range: { from: domFrom, to: domTo },
    };
  }
  // collapsed
  if (editorFocused) {
    return { text: "", range: null };
  }
  return prev;
}

/** 在焦点即将离开编辑器前（如 Agent 输入框 mousedown capture）强制抓取。 */
export function captureSelectionFromTextarea(ta: {
  selectionStart: number;
  selectionEnd: number;
  value: string;
}): SelectionSnapshot | null {
  const from = ta.selectionStart ?? 0;
  const to = ta.selectionEnd ?? 0;
  if (from >= to) return null;
  return {
    text: ta.value.slice(from, to),
    range: { from, to },
  };
}
