/**
 * 管理员面板的"耗时/上下文"卡片：把统计翻成人话的三条纪律都要守住。
 *
 * 1. **没有样本 ≠ 0**：`count: 0` 的行整行不显示，绝不给 `p95 0.0s`；
 * 2. **缺的信号不显示**：老后端没有 `promptChars`、本地模型没有 logprobs 时，
 *    对应那一段就是空的（不用 0 顶替）；
 * 3. **边界跟着数字**：`scope`（进程内、重启清零、多 worker 不合并）由后端给出，
 *    界面上要原样显示——否则"每次刷新 p99 都不一样"会被当成 bug。
 */
import { describe, expect, it } from "vitest";

import type { LatencySeries } from "../api/admin";
import { buildRows, seriesLabel, seriesRow } from "./latencyReport";

describe("seriesLabel", () => {
  it("把模型口径翻成人话", () => {
    expect(seriesLabel("deepseek-flash|think|write")).toBe("deepseek-flash · 思考档 · write");
    expect(seriesLabel("deepseek-flash|fast|llm")).toBe("deepseek-flash · 普通档 · llm");
  });

  it("上下文口径单独成一种说法", () => {
    expect(seriesLabel("context|continue")).toBe("上下文拼装 · continue");
  });

  it("认不出来的照原样显示，不隐藏", () => {
    expect(seriesLabel("weird|thing")).toBe("weird · thing");
  });
});

describe("seriesRow", () => {
  it("有样本时给出耗时、提示词体积与超时率", () => {
    const series: LatencySeries = {
      count: 32,
      total: { count: 32, p50: 12.34, p95: 48.1, p99: 96, max: 210 },
      promptChars: { count: 32, p50: 48000, max: 96000 },
      timeouts: 1,
    };
    const row = seriesRow("deepseek-flash|think|write", series);
    expect(row).not.toBeNull();
    expect(row!.latency).toBe("p50 12.3s · p95 48.1s · p99 96.0s · 最大 210s");
    expect(row!.prompt).toBe("提示词 p50 4.8 万字 · 最大 9.6 万字");
    expect(row!.tail).toBe("超时 1 次（3.1%）");
  });

  it("没有样本时整行返回 null（不显示 0 秒）", () => {
    expect(seriesRow("m|fast|llm", { count: 0, note: "没有样本" })).toBeNull();
  });

  it("缺 promptChars 时不显示提示词那一段", () => {
    const row = seriesRow("m|fast|llm", { count: 3, total: { count: 3, p50: 1, p95: 1, p99: 1, max: 1 } });
    expect(row!.prompt).toBe("");
    expect(row!.latency).not.toBe("");
  });

  it("零超时也如实说「0 次」，而不是省略", () => {
    const row = seriesRow("m|fast|llm", { count: 5, total: { count: 5, p50: 1, p95: 1, p99: 1, max: 1 }, timeouts: 0 });
    expect(row!.tail).toBe("超时 0 次");
  });

  it("上下文口径用字符数，不冒充分位秒数（单位混了会显示成 47000s）", () => {
    const row = seriesRow("context|continue", {
      count: 10,
      total: { count: 10, p50: 12000, p95: 47000, p99: 48000, max: 48000 },
      truncated: 3,
    });
    expect(row!.latency).toBe("拼装 p50 1.2 万字 · p95 4.7 万字 · 最大 4.8 万字");
    expect(row!.latency).not.toContain("s ·");
    expect(row!.truncation).toBe("被裁 3 次（30.0%）");
    // 上下文样本不记"超时"（那是模型调用的事），所以这里就该是空的——不是显示 0
    expect(row!.tail).toBe("");
    expect(row!.prompt).toBe("");
  });

  it("首字耗时只在流式样本存在时显示", () => {
    const row = seriesRow("m|fast|llm", {
      count: 2,
      total: { count: 2, p50: 30, p95: 40, p99: 40, max: 40 },
      firstToken: { count: 2, p50: 12, p95: 18.24, p99: 18.24, max: 18.24 },
    });
    expect(row!.firstToken).toBe("首字 p95 18.2s");
  });
});

describe("buildRows", () => {
  it("按样本数降序，并丢掉空行", () => {
    const rows = buildRows({
      "a|fast|llm": { count: 3, total: { count: 3, p50: 1, p95: 1, p99: 1, max: 1 } },
      "b|fast|llm": { count: 9, total: { count: 9, p50: 1, p95: 1, p99: 1, max: 1 } },
      "c|fast|llm": { count: 0, note: "没有样本" },
    });
    expect(rows.map((r) => r.key)).toEqual(["b|fast|llm", "a|fast|llm"]);
  });

  it("空对象不炸", () => {
    expect(buildRows({})).toEqual([]);
    expect(buildRows(undefined)).toEqual([]);
  });
});
