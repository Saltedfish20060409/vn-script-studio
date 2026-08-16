/**
 * agentIntent 意图推断单元测试
 *
 * 覆盖 inferAgentIntent 的各类意图路由：流水线/风格检查/定稿/账本/
 * 头脑风暴/导师列表/润色/对照面板/锁定角色/改稿/设定入库/事实扫描/
 * 仅评审/附件辅助/兜底 chat，以及 mode 推断与长文本启发式。
 */
import { describe, it, expect } from "vitest";
import { inferAgentIntent } from "./agentIntent";

describe("inferAgentIntent：命令式快捷意图", () => {
  it("空文本无附件 → chat", () => {
    expect(inferAgentIntent("")).toEqual({ kind: "chat" });
  });

  it("空文本但有附件 → 兜底 chat", () => {
    expect(inferAgentIntent("", 1)).toEqual({ kind: "chat" });
  });

  it("流水线指令 → pipeline，并剥离指令前缀作为 note", () => {
    const r = inferAgentIntent("跑完整流水线：生成大纲");
    expect(r.kind).toBe("pipeline");
    expect(r.note).toBe("生成大纲");
  });

  it("【流水线】前缀 → pipeline", () => {
    const r = inferAgentIntent("【流水线】生成第一章大纲");
    expect(r.kind).toBe("pipeline");
    expect(r.note).toBe("生成第一章大纲");
  });

  it("规划并生成的描述 → pipeline", () => {
    const r = inferAgentIntent("请帮我规划并生成第一章");
    expect(r.kind).toBe("pipeline");
  });

  it("风格检查 / 文风体检 → style_lint", () => {
    expect(inferAgentIntent("风格检查").kind).toBe("style_lint");
    expect(inferAgentIntent("文风体检").kind).toBe("style_lint");
  });

  it("定稿 / 定稿入库 → finalize", () => {
    expect(inferAgentIntent("定稿").kind).toBe("finalize");
    expect(inferAgentIntent("定稿入库").kind).toBe("finalize");
  });

  it("账本入库指令 → ledger_digest", () => {
    expect(inferAgentIntent("更新账本").kind).toBe("ledger_digest");
    expect(inferAgentIntent("章节摘要入库").kind).toBe("ledger_digest");
  });

  it("头脑风暴 → brainstorm，带 note", () => {
    const r = inferAgentIntent("头脑风暴：校园恋爱怎么展开");
    expect(r.kind).toBe("brainstorm");
    expect(r.note).toBe("校园恋爱怎么展开");
    expect(inferAgentIntent("头脑风暴").kind).toBe("brainstorm");
  });

  it("导师列表指令 → list_mentors", () => {
    expect(inferAgentIntent("查看写作导师").kind).toBe("list_mentors");
    expect(inferAgentIntent("导师列表").kind).toBe("list_mentors");
  });
});

describe("inferAgentIntent：改稿后置命令与角色锁定", () => {
  it("再润一版 → chapter_polish，mode light_touch", () => {
    const r = inferAgentIntent("再润一版。");
    expect(r.kind).toBe("chapter_polish");
    expect(r.mode).toBe("light_touch");
  });

  it("轻润一下 → chapter_polish", () => {
    expect(inferAgentIntent("轻润一下").kind).toBe("chapter_polish");
  });

  it("打开对照 / 这段用原文 → chapter_open_review", () => {
    expect(inferAgentIntent("打开对照").kind).toBe("chapter_open_review");
    expect(inferAgentIntent("这段用原文").kind).toBe("chapter_open_review");
  });

  it("别动+角色名 → chapter_lock_name 且 lockName 正确", () => {
    const r = inferAgentIntent("别动林夏");
    expect(r.kind).toBe("chapter_lock_name");
    expect(r.lockName).toBe("林夏");
  });

  it("保留 XX 的戏 → chapter_lock_name", () => {
    const r = inferAgentIntent("保留林夏的戏");
    expect(r.kind).toBe("chapter_lock_name");
    expect(r.lockName).toBe("林夏");
  });
});

describe("inferAgentIntent：自然语言改稿与 mode", () => {
  it("据此修改第一章 → chapter_revise", () => {
    expect(inferAgentIntent("据此修改第一章").kind).toBe("chapter_revise");
  });

  it("帮我改这一章，只去说明书 → chapter_revise + cut_lecture", () => {
    const r = inferAgentIntent("帮我改这一章，只去说明书");
    expect(r.kind).toBe("chapter_revise");
    expect(r.mode).toBe("cut_lecture");
  });

  it("改写第一章，更有温度 → chapter_revise + human_warmth", () => {
    const r = inferAgentIntent("改写第一章，更有温度");
    expect(r.kind).toBe("chapter_revise");
    expect(r.mode).toBe("human_warmth");
  });

  it("章节回炉重写 → chapter_revise", () => {
    expect(inferAgentIntent("这章回炉重写吧").kind).toBe("chapter_revise");
  });

  it("长文本含改稿词（>500 字符）→ chapter_revise", () => {
    const long = "请帮我改稿。" + "这是一段很长的话。".repeat(60);
    expect(long.length).toBeGreaterThan(500);
    expect(inferAgentIntent(long).kind).toBe("chapter_revise");
  });
});

describe("inferAgentIntent：设定 / 事实 / 评审 / 附件", () => {
  it("带附件且提到设定 → settings_ingest", () => {
    const r = inferAgentIntent("帮我整理设定并写进圣经", 1);
    expect(r.kind).toBe("settings_ingest");
  });

  it("带附件且提到角色卡 → settings_ingest", () => {
    expect(inferAgentIntent("根据附件整理角色卡", 1).kind).toBe(
      "settings_ingest"
    );
  });

  it("带附件提到设定与关系时优先 facts_scan", () => {
    const r = inferAgentIntent("根据附件整理人物关系", 1);
    expect(r.kind).toBe("facts_scan");
  });

  it("整理人物关系 / 时间线 / scan_facts → facts_scan", () => {
    expect(inferAgentIntent("整理人物关系").kind).toBe("facts_scan");
    expect(inferAgentIntent("整理时间线").kind).toBe("facts_scan");
    expect(inferAgentIntent("scan_facts").kind).toBe("facts_scan");
  });

  it("只要意见不要改 → critique_only", () => {
    expect(inferAgentIntent("只要意见，不要改").kind).toBe("critique_only");
    expect(inferAgentIntent("修改意见").kind).toBe("critique_only");
    expect(inferAgentIntent("你觉得这个分析对吗").kind).toBe("critique_only");
  });

  it("长文本（>800 字符）含分析且未要求改写 → critique_only", () => {
    const long = "这段分析有问题。" + "的".repeat(850);
    expect(long.length).toBeGreaterThan(800);
    expect(inferAgentIntent(long).kind).toBe("critique_only");
  });

  it("无附件却引用附件 → chat（后续走错误提示路径）", () => {
    expect(inferAgentIntent("请根据附件整理世界观").kind).toBe("chat");
  });

  it("无法识别 → chat 且无 note", () => {
    const r = inferAgentIntent("今天天气怎么样");
    expect(r).toEqual({ kind: "chat" });
  });
});
