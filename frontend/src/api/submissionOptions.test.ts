import { describe, expect, it, vi } from "vitest";

/**
 * 投稿包导出的查询参数映射。
 *
 * 这里钉的是一条容易搞反的约定：**开关型参数只在"关掉"时才出现在查询串里**
 * （`indent=0` / `page_break=0` / `counts=0` / `ruby=0`），因为后端的默认值是开。
 * 写反的表现是"用户勾了却没用"，而且后端不会报错——只能靠测试发现。
 *
 * `ruby` 这条尤其要守住：它决定注音写成 Word 原生注音（`w:ruby`）还是
 * `漢字（かんじ）` 括号文本。原生注音的基准词只在 `w:rubyBase` 里，
 * 简单取文本的工具会漏掉——所以"回退"必须是一条**明确的**请求，不能是默认行为。
 */
const rawFetch = vi.fn(async () => ({ blob: async () => new Blob() }));
vi.mock("./http", () => ({
  authedRawFetch: (...args: unknown[]) => rawFetch(...(args as [])),
  apiFetch: vi.fn(),
  buildApiHeaders: () => ({}),
  tzOffsetMinutes: () => 480,
}));

import { exportSubmission } from "./projects";

function lastUrl(): string {
  const calls = rawFetch.mock.calls as unknown as string[][];
  return calls[calls.length - 1][0];
}

describe("exportSubmission 的查询参数", () => {
  it("默认不带开关参数（后端默认即投稿常用排版）", async () => {
    await exportSubmission("p1", {});
    const url = lastUrl();
    expect(url).toBe("/projects/p1/export/submission");
  });

  it("关掉原生注音时才带 ruby=0", async () => {
    await exportSubmission("p1", { nativeRuby: false });
    expect(lastUrl()).toContain("ruby=0");
  });

  it("显式开启原生注音不带参数（默认值就是开）", async () => {
    await exportSubmission("p1", { nativeRuby: true });
    expect(lastUrl()).not.toContain("ruby=");
  });

  it("其它开关同样只在关掉时出现", async () => {
    await exportSubmission("p1", {
      indent: false,
      pageBreak: false,
      counts: false,
      synopsis: true,
      split: true,
      author: "  张三  ",
      contact: "a@b.c",
    });
    const url = lastUrl();
    expect(url).toContain("indent=0");
    expect(url).toContain("page_break=0");
    expect(url).toContain("counts=0");
    expect(url).toContain("synopsis=1");
    expect(url).toContain("split=1");
    // 作者名要去掉首尾空格（编辑拿到的信息页不能带多余空白）
    expect(url).toContain("author=%E5%BC%A0%E4%B8%89");
    expect(url).toContain("contact=a%40b.c");
  });
});
