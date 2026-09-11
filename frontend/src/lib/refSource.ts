/**
 * 渠道归因（?ref=bili / douyin / github …）— 首次归因，90 天有效。
 *
 * 规则：
 * - 只在**第一次**带 ref 访问时写入（后续访问不覆盖），避免用户后来点了别的链接
 *   把原始来源冲掉；
 * - 只接受短标识（字母/数字/下划线/连字符），其他一律忽略（防注入、防乱码）；
 * - 注册时把它作为 ref 一起提交，后端写入 users.signup_source。
 */

const REF_KEY = "vnss-ref";
const REF_AT_KEY = "vnss-ref-at";
const REF_TTL_MS = 90 * 24 * 3600 * 1000;
const REF_RE = /^[a-zA-Z0-9_-]{1,64}$/;

/** 从 URL 抓取并保存首次来源；应在应用启动时调用一次。 */
export function captureRef(): void {
  if (typeof window === "undefined") return;
  try {
    const params = new URLSearchParams(window.location.search);
    const raw = (params.get("ref") || "").trim().toLowerCase();
    if (!raw || !REF_RE.test(raw)) return;
    const existing = localStorage.getItem(REF_KEY);
    const at = Number(localStorage.getItem(REF_AT_KEY) || "0");
    const expired = !at || Date.now() - at > REF_TTL_MS;
    if (existing && !expired) return; // 首次归因：已有且未过期就保留
    localStorage.setItem(REF_KEY, raw.slice(0, 64));
    localStorage.setItem(REF_AT_KEY, String(Date.now()));
  } catch {
    /* storage 不可用则跳过归因 */
  }
}

/** 读取已保存的来源（过期返回 undefined）。 */
export function getRef(): string | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const value = localStorage.getItem(REF_KEY);
    if (!value) return undefined;
    const at = Number(localStorage.getItem(REF_AT_KEY) || "0");
    if (!at || Date.now() - at > REF_TTL_MS) return undefined;
    return REF_RE.test(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

/** 仅测试用。 */
export function __resetRefForTest(): void {
  try {
    localStorage.removeItem(REF_KEY);
    localStorage.removeItem(REF_AT_KEY);
  } catch {
    /* ignore */
  }
}
