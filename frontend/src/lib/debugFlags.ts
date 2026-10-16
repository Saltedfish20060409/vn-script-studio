/**
 * 开发者 / 站主调试开关（localStorage）。
 *
 * 账本面板是给 Agent 记忆用的内部观测面，不对普通作者推广。
 * 需要检查「记忆是否随正文更新」时：
 *   localStorage.setItem("vn.debugLedger", "1")
 * 然后刷新；关掉：removeItem 或设 "0"。
 */

const LEDGER_KEY = "vn.debugLedger";

export function isDebugLedgerEnabled(): boolean {
  try {
    const v = localStorage.getItem(LEDGER_KEY);
    return v === "1" || v === "true";
  } catch {
    return false;
  }
}

/** 文件菜单里账本项的展示文案（仅调试开时出现）。 */
export const DEBUG_LEDGER_LABEL = "账本 / 摘要（调试）";
