import { describe, expect, it } from "vitest";
import { HELP_DISCLAIMER, HELP_FAQ, HELP_QUICK } from "./helpContent";
import { defaultWelcome, normalizeMessages } from "./agentFormat";

/**
 * 文案长度护栏。
 *
 * 为什么要有：产品的上手复杂度很大一部分不是"功能多"，而是"要读的字多"。
 * 这类文案会随时间自然膨胀（每次加功能就补一句），所以用测试把上限钉住：
 * **必要的信息一句都不能少，但不必要的解释不能留在屏幕上。**
 *
 * 上限怎么定的：按"一屏能看完"来算——常驻段落 ≤ 2 行，FAQ 答案（点击后才展开）≤ 6 行。
 * 要突破上限就该先问：这是新增的必要信息，还是只是解释？
 */
describe("文案长度护栏（可读性）", () => {
  it("帮助面板常驻段落：每条不超过 90 字", () => {
    for (const s of HELP_QUICK) {
      expect(s.body.length, `${s.title} 太长`).toBeLessThanOrEqual(90);
    }
  });

  it("帮助面板免责声明不超过 70 字", () => {
    expect(HELP_DISCLAIMER.length).toBeLessThanOrEqual(70);
  });

  it("FAQ 答案（点击才展开）每条不超过 220 字", () => {
    for (const item of HELP_FAQ) {
      expect(item.a.length, `${item.q} 的答案太长`).toBeLessThanOrEqual(220);
    }
  });

  it("FAQ 问题都短（问题本身是常驻可见的）", () => {
    for (const item of HELP_FAQ) {
      expect(item.q.length, item.q).toBeLessThanOrEqual(24);
    }
  });

  it("Agent 开场白不超过 120 字（每次新对话都看得见）", () => {
    const welcome = defaultWelcome();
    expect(welcome.length).toBe(1);
    expect(welcome[0].content.length).toBeLessThanOrEqual(120);
  });

  it("文案里不出现给开发者看的词", () => {
    const all = [
      HELP_DISCLAIMER,
      ...HELP_QUICK.map((s) => s.body),
      ...HELP_FAQ.map((i) => i.a),
      ...defaultWelcome().map((m) => m.content),
    ].join("\n");
    for (const leak of [
      "uvicorn",
      "dev.bat",
      "token 上限",
      "语义向量",
      "JSON 模式",
      "npm",
      "后端进程",
    ]) {
      expect(all.includes(leak), `文案里泄漏了开发细节：${leak}`).toBe(false);
    }
  });
});

describe("开场白版本判定（改文案时踩过的坑）", () => {
  const current = defaultWelcome();

  it("当前这一版开场白不算「旧的」——否则每次加载都会白重写一遍", () => {
    const got = normalizeMessages([
      { role: "assistant", content: current[0].content },
      { role: "user", content: "接着写" },
    ]);
    expect(got[0].content).toBe(current[0].content);
    expect(got.length).toBe(2);
  });

  it("上一版的开场白会被换成当前这一版", () => {
    const old =
      "我是这部作品的驻场责编（通用文学编辑）。我会默认按一套面向轻小说 / 视觉小说的写作要点帮你看稿——比如对白要能演得动。";
    const got = normalizeMessages([
      { role: "assistant", content: old },
      { role: "user", content: "接着写" },
    ]);
    expect(got[0].content).toBe(current[0].content);
    // 真实对话历史一字不动
    expect(got[1].content).toBe("接着写");
  });

  it("用户自己聊出来的历史不会被当成开场白改写", () => {
    const msgs = [
      { role: "user" as const, content: "帮我看这段" },
      { role: "assistant" as const, content: "好，我看看。" },
    ];
    expect(normalizeMessages(msgs)).toEqual(msgs);
  });
});
