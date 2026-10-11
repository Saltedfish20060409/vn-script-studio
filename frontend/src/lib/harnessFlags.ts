/** 写作 harness 本机开关（LLM 子代理等）。 */

const LLM_SUB_KEY = "vnss-llm-subagent-v1";

export function loadLlmSubagentEnabled(): boolean {
  try {
    return (localStorage.getItem(LLM_SUB_KEY) || "").trim() === "1";
  } catch {
    return false;
  }
}

export function saveLlmSubagentEnabled(on: boolean): void {
  try {
    localStorage.setItem(LLM_SUB_KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
}
