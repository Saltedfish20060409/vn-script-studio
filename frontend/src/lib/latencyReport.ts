/**
 * 把 `/admin/llm-latency` 的原始统计翻成"人能读的几行"（纯函数，便于单测）。
 *
 * 三条纪律（都是后端已经守住的，展示层不能把它们弄丢）：
 *
 * 1. **没有样本 ≠ 0**：`count === 0` 时显示"没有样本"，绝不显示 `p95 0.0s`
 *    （那会让人以为"快得不用管"）。
 * 2. **缺的信号不显示**：本地模型拿不到 logprobs、老版本后端没有 `promptChars`，
 *    这些字段缺失就整列不显示，不用 0 顶替。
 * 3. **边界要跟着数字走**：`scope` 是后端写明的"进程内、重启清零、多 worker 不合并"，
 *    它必须显示在数字旁边——否则 p99 每次刷新都不一样会让人以为统计坏了。
 */
import type { LatencyQuantiles, LatencySeries } from "../api/admin";

export type SeriesRow = {
  key: string;
  /** "deepseek-flash · 思考档 · 写正文" 之类，给人看 */
  label: string;
  count: number;
  /** "p50 12.3s · p95 48.1s · p99 96.0s · 最大 210s"（无样本时为空） */
  latency: string;
  /** "提示词 p50 4.8万 字 · 最大 9.6万 字"（缺字段时为空） */
  prompt: string;
  /** "首字 p95 18.2s" */
  firstToken: string;
  /** "超时 3.1%"（0 也显示，但注明是 0 次） */
  tail: string;
  /** 截断率（上下文系列才有） */
  truncation: string;
};

const TIER_LABEL: Record<string, string> = { think: "思考档", fast: "普通档" };

function seconds(value?: number): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  if (value >= 100) return `${Math.round(value)}s`;
  if (value >= 10) return `${value.toFixed(1)}s`;
  return `${value.toFixed(2)}s`;
}

function chars(value?: number): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  if (value >= 10000) return `${(value / 10000).toFixed(1)} 万字`;
  return `${Math.round(value)} 字`;
}

function quantiles(q: LatencyQuantiles | undefined): string {
  if (!q || !q.count) return "";
  return `p50 ${seconds(q.p50)} · p95 ${seconds(q.p95)} · p99 ${seconds(q.p99)} · 最大 ${seconds(q.max)}`;
}

/** 上下文系列的第一个字段是**字符数**而不是秒——单位混了会显示成"p95 47000.0s"。 */
function charQuantiles(q: LatencyQuantiles | undefined): string {
  if (!q || !q.count) return "";
  return `拼装 p50 ${chars(q.p50)} · p95 ${chars(q.p95)} · 最大 ${chars(q.max)}`;
}

function rate(hits?: number, total?: number, label = "超时"): string {
  if (typeof hits !== "number" || !total) return "";
  const pct = ((hits / total) * 100).toFixed(1);
  return hits === 0 ? `${label} 0 次` : `${label} ${hits} 次（${pct}%）`;
}

/** 把统计口径的 key 翻成人话；认不出来的照原样显示（不隐藏）。 */
export function seriesLabel(key: string): string {
  const [head, mid, tail] = key.split("|");
  if (head === "context") return `上下文拼装 · ${tail ?? mid ?? "未知任务"}`;
  const parts = [head];
  if (mid && TIER_LABEL[mid]) parts.push(TIER_LABEL[mid]);
  else if (mid) parts.push(mid);
  if (tail) parts.push(tail);
  return parts.join(" · ");
}

/** 一行汇总；没有任何可用数字时返回 null（调用方据此不显示这一行）。 */
export function seriesRow(key: string, series: LatencySeries | undefined): SeriesRow | null {
  if (!series) return null;
  const isContext = key.startsWith("context|");
  const count = typeof series.count === "number" ? series.count : 0;
  const row: SeriesRow = {
    key,
    label: seriesLabel(key),
    count,
    // 上下文系列的 total 是**字符数**，模型系列是**秒**：单位必须按口径分开算，
    // 否则会把 4.7 万字符显示成 "p95 47000.0s"
    latency: isContext ? charQuantiles(series.total) : quantiles(series.total),
    prompt: series.promptChars?.count
      ? `提示词 p50 ${chars(series.promptChars.p50)} · 最大 ${chars(series.promptChars.max)}`
      : "",
    firstToken: series.firstToken?.count ? `首字 p95 ${seconds(series.firstToken.p95)}` : "",
    tail: rate(series.timeouts, count, "超时"),
    truncation: isContext ? rate(series.truncated, count, "被裁") : "",
  };
  const hasNumbers = Boolean(
    row.latency || row.prompt || row.firstToken || row.tail || row.truncation
  );
  return hasNumbers ? row : null;
}

/** 全部口径（样本多的排前面，与后端一致）。 */
export function buildRows(series: Record<string, LatencySeries> | undefined): SeriesRow[] {
  if (!series) return [];
  return Object.keys(series)
    .map((key) => seriesRow(key, series[key]))
    .filter((row): row is SeriesRow => row !== null)
    .sort((a, b) => b.count - a.count);
}
