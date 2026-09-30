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

  it("普通改章请求**不带**选方向意图（弹窗不再自动弹）", () => {
    // 用户反馈"弹窗很多余"，所以默认路径必须走 chapter_revise 直接改，
    // 只有下面那几句显式说法才进方向面板
    for (const t of [
      "帮我改这一章",
      "这章回炉重写吧",
      "改写第一章",
      "据此修改第一章",
    ]) {
      expect(inferAgentIntent(t).kind).not.toBe("revise_pick");
    }
  });

  it("显式说「选个方向」→ revise_pick（方向面板的唯一入口）", () => {
    for (const t of [
      "选个方向",
      "选个方向改这一章",
      "按方向改",
      "选一个改法",
      "挑个模式",
    ]) {
      expect(inferAgentIntent(t).kind).toBe("revise_pick");
    }
  });

  it("「选个方向改这一章」不会被 broad 的改章规则抢走", () => {
    // 这条顺序很关键：revise_pick 必须在 chapter_revise 之前判断，
    // 否则含"改这一章"的句子会被后者先接住，面板永远打不开
    expect(inferAgentIntent("选个方向改这一章").kind).toBe("revise_pick");
  });

  it("长文里明确说了「帮我改稿」→ 仍然是改稿（判据是说的内容，不是长度）", () => {
    const long = "请帮我改稿。" + "这是一段很长的话。".repeat(60);
    expect(long.length).toBeGreaterThan(500);
    expect(inferAgentIntent(long).kind).toBe("chapter_revise");
  });

  it("长文只是**聊到**改 → chat（旧版 >500 字带个改字就切改稿）", () => {
    const long =
      "这是编辑给我的反馈，我贴上来你看看。" +
      "他说按这个方向改会更好，但我想先听听你的判断。".repeat(40);
    expect(long.length).toBeGreaterThan(500);
    expect(inferAgentIntent(long).kind).toBe("chat");
  });
});

describe("inferAgentIntent：改稿模式必须由作者明确要求", () => {
  it("说出动作 + 对象才进改稿", () => {
    for (const t of [
      "帮我改这一章",
      "帮我改一下这一章",
      "改写第一章",
      "把这章的正文重写一遍",
      "帮我润色这一章",
      "据此修改第一章",
      "麻烦按这份意见改一下第三章",
    ]) {
      expect(inferAgentIntent(t).kind).toBe("chapter_revise");
    }
  });

  it("不带对象也成立的显式指令（改稿 / 回炉）→ chapter_revise", () => {
    expect(inferAgentIntent("改稿").kind).toBe("chapter_revise");
    expect(inferAgentIntent("帮我改稿").kind).toBe("chapter_revise");
    expect(inferAgentIntent("这章回炉吧").kind).toBe("chapter_revise");
  });

  it("选中一段再说一句也算改稿（线上漏过的说法）", () => {
    // 实测那条原句：因为对象列表里只有「这一段」没有「这段」，它没被认成改稿，
    // 只回了一段点评——作者要的是改稿。
    for (const t of [
      "帮我把林夏登场这段改得更细腻",
      "帮我改这段",
      "这句重写一下",
      "把这几段润色一遍",
      "这部分改一下",
    ]) {
      expect(inferAgentIntent(t).kind).toBe("chapter_revise");
    }
  });

  it("选区说法不会被评价句 / 出处句误用", () => {
    for (const t of [
      "这一段改得不错",
      "这一段写得怎么样",
      "帮我看这一段值不值",
      "这段改写自朋友的小说",
    ]) {
      expect(inferAgentIntent(t).kind).not.toBe("chapter_revise");
    }
  });

  it("只是**聊到**这一章 → chat（不再自己切进改稿模式）", () => {
    for (const t of [
      "这一章有什么问题？",
      "帮我看看这一章的分析",
      "这一章的节奏我感觉有点慢",
      "第三章的节奏有点慢",
      "这一章写得怎么样",
      "今天天气怎么样",
    ]) {
      expect(inferAgentIntent(t).kind).toBe("chat");
    }
  });

  it("征询口气（怎么改 / 要不要改）→ chat，不是让谁动手", () => {
    for (const t of [
      "这一章怎么改？",
      "这一章如何改写",
      "这一章要不要改写",
      "该不该重写这一章",
      "这一章要不要按你的建议改写？",
    ]) {
      expect(inferAgentIntent(t).kind).toBe("chat");
    }
  });

  it("明确不要动手 → 不切改稿", () => {
    for (const t of [
      "这一章先别改",
      "不要重写这一章",
      "这一章不用改",
      "先别改这一章，只给意见",
    ]) {
      expect(inferAgentIntent(t).kind).not.toBe("chapter_revise");
    }
    // "只给意见" 走审稿意见路径，不生成改稿预览
    expect(inferAgentIntent("先别改这一章，只给意见").kind).toBe("critique_only");
  });

  it("带附件只是聊到改稿 → chat（旧版带附件提到改写就切改稿）", () => {
    expect(inferAgentIntent("这是编辑给的改稿意见，你先看看", 1).kind).toBe("chat");
    expect(inferAgentIntent("这段改写自朋友的小说，你帮我看看", 1).kind).toBe("chat");
  });

  it("说了动作、同时限制范围（不要改对白）→ 仍然是改稿", () => {
    expect(inferAgentIntent("帮我改这一章，不要改对白").kind).toBe("chapter_revise");
  });

  it("没有改稿动作的模糊说法 → chat；说出「润」才是润色", () => {
    expect(inferAgentIntent("再软一点").kind).toBe("chat");
    expect(inferAgentIntent("再轻一点").kind).toBe("chat");
    expect(inferAgentIntent("再润一版。").kind).toBe("chapter_polish");
  });

  it("「不要改写第三章」不会被当成锁定角色", () => {
    const r = inferAgentIntent("不要改写第三章");
    expect(r.kind).not.toBe("chapter_lock_name");
    expect(r.kind).not.toBe("chapter_revise");
  });

  it("「别动这个想法」这类指代不是角色名，不写进锁定偏好", () => {
    for (const t of ["别动这个想法，我还没想好", "不要改我的思路", "先别动这些"]) {
      expect(inferAgentIntent(t).kind).not.toBe("chapter_lock_name");
    }
  });
});

describe("inferAgentIntent：设定 / 事实 / 评审 / 附件", () => {
  it("带附件且提到设定 → settings_ingest", () => {
    const r = inferAgentIntent("帮我整理设定并写进圣经", 1);
    expect(r.kind).toBe("settings_ingest");
  });

  it("带附件且提到角色卡 → settings_ingest", () => {
    expect(inferAgentIntent("根据附件整理角色卡", 1).kind).toBe("settings_ingest");
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

describe("inferAgentIntent：提到名词 ≠ 下命令（写入设定 / 事实扫描 / 自动写作）", () => {
  // 原样复现作者踩到的坑：带附件问"跟人物设定对得上吗、有没有矛盾"，
  // 旧版因为句子里有"设定"两个字直接切进"写入设定页"——那是个真改工程的流程。
  const ATTACHED_REVIEW_ASK =
    "可以怎么续写？能不能提供一些方向？也请你先检查下前面这部分跟人物设定是否对的上、前后有没有矛盾、是否符合视觉小说的特点等等";

  it("带附件问「跟人物设定对得上吗 / 有没有矛盾」→ chat，不进设定页", () => {
    expect(inferAgentIntent(ATTACHED_REVIEW_ASK, 1)).toEqual({ kind: "chat" });
  });

  it("带附件提到设定对象但**没有写入动作** → chat", () => {
    for (const t of [
      "根据附件看看这段跟人物设定对不对",
      "附件里的世界观跟正文冲突吗",
      "帮我看看角色卡写的对不对",
      "这些设定怎么整理进库里？",
      "先别写进设定，先看看有没有矛盾",
    ]) {
      expect(inferAgentIntent(t, 1).kind).toBe("chat");
    }
  });

  it("说出写入动作才算入库 → settings_ingest", () => {
    for (const t of [
      "按附件整理设定条目",
      "根据附件更新设定",
      "把附件里的资料录入设定库",
      "帮我整理角色卡写进圣经",
    ]) {
      expect(inferAgentIntent(t, 1).kind).toBe("settings_ingest");
    }
  });

  it("只是聊到人物关系 → chat；说出扫描动作才扫", () => {
    expect(inferAgentIntent("这一章的人物关系有点乱，帮我看看").kind).toBe("chat");
    expect(inferAgentIntent("人物关系要怎么整理？").kind).toBe("chat");
    expect(inferAgentIntent("整理人物关系").kind).toBe("facts_scan");
    expect(inferAgentIntent("扫描一下时间线").kind).toBe("facts_scan");
    expect(inferAgentIntent("根据附件整理人物关系", 1).kind).toBe("facts_scan");
  });

  it("只是讨论写作计划 → chat；说「规划并生成」才是自动写作", () => {
    expect(inferAgentIntent("请看看我的写作计划怎么写").kind).toBe("chat");
    expect(inferAgentIntent("请帮我规划并生成第一章").kind).toBe("pipeline");
  });
});
