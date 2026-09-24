import { describe, expect, it } from "vitest";
import {
  RULE_BASIS,
  SCENE_SEPARATOR,
  applyPairOnKey,
  countIssues,
  expandReplacement,
  findMatches,
  goalProgress,
  lintProse,
  nextMatch,
  parseScenes,
  replaceAllMatches,
  replaceRange,
} from "./editorAssist";
// 字数口径由 wordCount.ts 提供（与后端 writing_stats.py 对齐），这里不再复制一份
import { countWords } from "./wordCount";

/**
 * 规则依据守卫（GB/T 15834-2011 那一层）。
 *
 * 为什么要有：这些提示过去只有"我们觉得该这样"，作者没有可以争辩的东西。
 * 现在每条规则都必须写出**公开可查的依据**（国标/行业标准/W3C 排版需求），
 * 或者如实标成"作品自身的一致性"。新加规则忘了写依据，这个测试就红。
 */
describe("规则依据（不允许没有出处的规则）", () => {
  /** 跑一批会命中各种规则的文本，收集实际产生过的 code。 */
  const CODES = new Set(
    [
      lintProse("他说：「今天不写了。\n所以呢。"), // 引号不配对
      lintProse("你好,世界"), // 半角标点
      lintProse("他说--不对"), // -- 破折号
      lintProse("他—走了"), // 单个 —
      lintProse("她说..."), // 半角省略号
      lintProse("好的。。。"), // 。。。
      lintProse("他 说了一句。"), // 汉字间空格
      lintProse("他 说了一句。   "), // 行尾空格
      lintProse("2019-2020 年间"), // 数字区间半角连字符
      lintProse("二〇一九年的秋天"), // 汉字年份
      lintProse("大约10几个人"), // 阿拉伯数字 + 几
      lintProse("那是3、4年前的事"), // 阿拉伯数字 + 顿号表概数
      lintProse("带来了……等等东西"), // 省略号 + 等
      lintProse("我在读《钟声与《第七个抽屉》》。"), // 书名号嵌套
      lintProse("他说：“她叫我“小澪”。”"), // 引号嵌套
      lintProse("他迫不急待地推开门。"), // 别字
    ].flatMap((issues) => issues.map((i) => i.code))
  );

  it("每一条实际会报出来的规则都登记了依据", () => {
    expect(CODES.size).toBeGreaterThanOrEqual(15);
    for (const code of CODES) {
      const basis = RULE_BASIS[code];
      expect(basis, `规则 ${code} 没有登记依据`).toBeTruthy();
      expect(basis.length, `规则 ${code} 的依据太短，等于没写`).toBeGreaterThan(8);
    }
  });

  it("依据指向的是可查的规范或如实说明，不是空话", () => {
    for (const [code, basis] of Object.entries(RULE_BASIS)) {
      expect(basis.trim().length, code).toBeGreaterThan(8);
      // 要么给出公开规范，要么如实写成"作品自身的一致性/无规范依据"
      const ok =
        basis.includes("GB/T") ||
        basis.includes("CY/T") ||
        basis.includes("clreq") ||
        basis.includes("作品自身") ||
        basis.includes("编辑规范") ||
        basis.includes("无规范依据") ||
        basis.includes("通用写法");
      expect(ok, `${code} 的依据看不出出处：${basis}`).toBe(true);
    }
  });

  it("每条 issue 上都带着它的依据（界面上要能直接显示）", () => {
    for (const issue of lintProse("他迫不急待地说--完了。   ")) {
      expect(issue.basis, issue.code).toBe(RULE_BASIS[issue.code]);
    }
  });
});

describe("数字用法与中英间距（GB/T 15835 / CY/T 154）", () => {
  it("汉字年份报，阿拉伯年份与「三年/那一年」不报", () => {
    expect(lintProse("二〇一九年的秋天").some((i) => i.code === "cjk_year_digits")).toBe(true);
    expect(lintProse("2019 年的秋天").some((i) => i.code === "cjk_year_digits")).toBe(false);
    expect(lintProse("三年后，那一年他十九岁。").some((i) => i.code === "cjk_year_digits")).toBe(
      false
    );
  });

  it("「10几个」报，「十几个」「10多个人」不报", () => {
    expect(lintProse("大约10几个人").some((i) => i.code === "arabic_with_ji")).toBe(true);
    expect(lintProse("大约十几个人").some((i) => i.code === "arabic_with_ji")).toBe(false);
    expect(lintProse("大约10多个人").some((i) => i.code === "arabic_with_ji")).toBe(false);
  });

  it("「3、4年前」报，「第3、4章」不报", () => {
    expect(lintProse("那是3、4年前的事").some((i) => i.code === "arabic_dunhao_range")).toBe(true);
    expect(lintProse("请翻到第3、4章").some((i) => i.code === "arabic_dunhao_range")).toBe(false);
    expect(lintProse("那是三四年前的事").some((i) => i.code === "arabic_dunhao_range")).toBe(false);
  });

  it("数字区间用半角连字符报，英文连字符不报", () => {
    expect(lintProse("2019-2020 年间").some((i) => i.code === "dash_ascii_range")).toBe(true);
    expect(lintProse("well-known 的 SARS-CoV-2").some((i) => i.code === "dash_ascii_range")).toBe(
      false
    );
  });

  it("新规则都带依据（不是只有后端才有出处）", () => {
    for (const issue of lintProse("二〇一九年，大约10几个人，那是3、4年前。")) {
      expect(issue.basis, issue.code).toContain("GB/T 15835-2011");
    }
  });
});

describe("lintProse 引号配对", () => {  it("一段里引号数量不等 → error，并给出两种数量", () => {
    const issues = lintProse("他说：「今天不写了。\n所以呢。");
    const hit = issues.find((i) => i.code === "quote_unbalanced");
    expect(hit?.level).toBe("error");
    expect(hit?.message).toContain("1 个「「」");
    expect(hit?.message).toContain("0 个「」」");
  });

  it("对白跨行但段落内配对完整 → 不报（不能按行判）", () => {
    const issues = lintProse("他说：\n「今天不写了，因为外面在下雨，\n而且我实在写不动了。」");
    expect(issues.some((i) => i.code === "quote_unbalanced")).toBe(false);
  });

  it("空行分段：两段各自配对完整 → 不报", () => {
    const text = "「一」\n\n『二』\n\n“三”";
    expect(lintProse(text).some((i) => i.code === "quote_unbalanced")).toBe(false);
  });

  it("全角括号不配对也报", () => {
    const issues = lintProse("他笑了（其实没笑");
    expect(issues.some((i) => i.code === "quote_unbalanced" && i.message.includes("（"))).toBe(true);
  });
});

describe("lintProse 标点笔误", () => {
  it("半角逗号贴汉字 → warn", () => {
    const issues = lintProse("你好,世界");
    expect(issues.some((i) => i.code === "punct_halfwidth_near_cjk")).toBe(true);
  });

  it("英文句子里正常的半角标点不报", () => {
    const issues = lintProse("Hello, world! It's fine.");
    expect(issues.some((i) => i.code === "punct_halfwidth_near_cjk")).toBe(false);
  });

  it("`--` 报，`---`（Markdown 分隔线）不报", () => {
    expect(lintProse("他说--不对").some((i) => i.code === "dash_ascii_double")).toBe(true);
    expect(lintProse("上文\n---\n下文").some((i) => i.code === "dash_ascii_double")).toBe(false);
  });

  it("单个 — 贴汉字报，成双 —— 不报，年份区间 2019—2020 不报", () => {
    expect(lintProse("他—走了").some((i) => i.code === "dash_single_em")).toBe(true);
    expect(lintProse("他——走了").some((i) => i.code === "dash_single_em")).toBe(false);
    expect(lintProse("2019—2020 年间").some((i) => i.code === "dash_single_em")).toBe(false);
  });

  it("`...` 贴汉字报，英文里的 ... 不报", () => {
    expect(lintProse("她说…不，她说...").some((i) => i.code === "ellipsis_ascii_dots")).toBe(true);
    expect(lintProse("wait... what?").some((i) => i.code === "ellipsis_ascii_dots")).toBe(false);
  });

  it("`。。。` 报，正常句号不报", () => {
    expect(lintProse("好的。。。").some((i) => i.code === "ellipsis_fullwidth_period")).toBe(true);
    expect(lintProse("好的。然后呢。").some((i) => i.code === "ellipsis_fullwidth_period")).toBe(false);
  });

  it("汉字之间的空格与行尾空格是 info", () => {
    const issues = lintProse("他 说了一句。\n下一行。   ");
    expect(issues.find((i) => i.code === "space_between_cjk")?.level).toBe("info");
    expect(issues.find((i) => i.code === "trailing_space")?.level).toBe("info");
  });

  it("干净正文一条都不报", () => {
    const text = [
      "雨停的时候，站台的灯还亮着。",
      "“走吧，”她说，“反正末班车已经过去了。”",
      "他点了点头——那种没什么意义的、习惯性的点头。",
      "「那明天呢？」",
      "他没有回答。……或许答案本来就不重要。",
    ].join("\n\n");
    expect(lintProse(text)).toEqual([]);
  });

  it("常见别字并进体检里（词表口径，见 typoRules）", () => {
    const issues = lintProse("他迫不急待地推开门。");
    const hit = issues.find((i) => i.code === "typo_confusion");
    expect(hit?.level).toBe("warn");
    expect(hit?.message).toContain("迫不及待");
    expect(hit?.line).toBe(1);
  });

  it("lineOf 对别字也算得对（第几行要能跳过去）", () => {
    const issues = lintProse("第一行。\n第二行，迫不急待。\n第三行。");
    expect(issues.find((i) => i.code === "typo_confusion")?.line).toBe(2);
  });

  it("位置信息能对上原文（offset/line/snippet）", () => {
    const text = "第一行没问题\n第二行有 半角逗号,在这里\n第三行";
    const hit = lintProse(text).find((i) => i.code === "punct_halfwidth_near_cjk");
    expect(hit?.line).toBe(2);
    expect(text.slice(hit!.offset, hit!.offset + hit!.length)).toBe(hit!.snippet);
  });

  it("空文本不抛异常", () => {
    expect(lintProse("")).toEqual([]);
  });

  it("countIssues 按级别汇总", () => {
    const counts = countIssues(lintProse("「没闭合\n他 说,好。。。"));
    expect(counts.error).toBeGreaterThan(0);
    expect(counts.warn).toBeGreaterThan(0);
    expect(counts.info).toBeGreaterThan(0);
  });

  it("别字级别是 warn，不混进 info 里（作者该看见它）", () => {
    const counts = countIssues(lintProse("迫不急待"));
    expect(counts.warn).toBe(1);
  });
});

describe("findMatches", () => {
  it("默认不区分大小写，返回全部命中", () => {
    expect(findMatches("Abc abc ABC", "abc")).toEqual([
      { from: 0, to: 3 },
      { from: 4, to: 7 },
      { from: 8, to: 11 },
    ]);
  });

  it("区分大小写时只命中一致的", () => {
    expect(findMatches("Abc abc", "abc", { caseSensitive: true })).toEqual([{ from: 4, to: 7 }]);
  });

  it("空查询返回空数组（不是 null）", () => {
    expect(findMatches("abc", "")).toEqual([]);
  });

  it("正则模式支持分组查找", () => {
    expect(findMatches("第1章 第22章", "第\\d+章", { regex: true })).toEqual([
      { from: 0, to: 3 },
      { from: 4, to: 8 },
    ]);
  });

  it("非法正则返回 null（界面显示「正则写错了」而不是崩）", () => {
    expect(findMatches("abc", "([", { regex: true })).toBeNull();
  });

  it("零宽正则会终止（不死循环）", () => {
    expect(findMatches("abc", "", { regex: true })).toEqual([]);
    expect(findMatches("abc", "(?=b)", { regex: true })).toEqual([{ from: 1, to: 1 }]);
  });

  it("查汉字同样按字面找", () => {
    expect(findMatches("林夏走进来，林夏坐下。", "林夏")).toEqual([
      { from: 0, to: 2 },
      { from: 6, to: 8 },
    ]);
  });
});

describe("替换", () => {
  it("replaceRange 越界会夹到范围内", () => {
    expect(replaceRange("abc", -5, 99, "X")).toBe("X");
    expect(replaceRange("abc", 1, 2, "X")).toBe("aXc");
  });

  it("replaceRange 用空前缀做删除", () => {
    expect(replaceRange("abc", 1, 2, "")).toBe("ac");
  });

  it("全部替换返回次数，且从后往前替换不会错位", () => {
    const res = replaceAllMatches("他说...她说...", "...", "……");
    expect(res.count).toBe(2);
    expect(res.text).toBe("他说……她说……");
  });

  it("没有命中时原样返回、次数 0", () => {
    expect(replaceAllMatches("abc", "z", "y")).toEqual({ text: "abc", count: 0 });
  });

  it("正则替换（非法正则时原样返回）", () => {
    expect(replaceAllMatches("a1b2", "\\d", "#", { regex: true }).text).toBe("a#b#");
    expect(replaceAllMatches("a1b2", "([", "#", { regex: true })).toEqual({
      text: "a1b2",
      count: 0,
    });
  });

  it("正则替换支持 $1 捕获组（标准语义）", () => {
    const res = replaceAllMatches("林夏：走吧\n陆然：好", "(林夏|陆然)：", "[$1] ", {
      regex: true,
    });
    expect(res.count).toBe(2);
    expect(res.text).toBe("[林夏] 走吧\n[陆然] 好");
  });

  it("多行匹配要自己写 (?m) 式的选择项：^ 只匹配全文开头（界面不提供 m 开关）", () => {
    // 记录这个语义：作者在查找框写 ^ 时行为是"只匹配开头"，测试把它固定下来，
    // 免得以后误以为支持多行锚点。
    const res = findMatches("林夏：走吧\n陆然：好", "^(\\S+?)：", { regex: true });
    expect(res).toEqual([{ from: 0, to: 3 }]);
  });

  it("非正则替换里的 $1 按字面写进去（不展开）", () => {
    expect(replaceAllMatches("abc", "b", "$1").text).toBe("a$1c");
  });

  it("单处替换的展开与全部替换同语义，且不越出命中区间", () => {
    const text = "第1章 第22章";
    const ranges = findMatches(text, "第(\\d+)章", { regex: true })!;
    expect(expandReplacement(text, ranges[0], "第(\\d+)章", "Ch$1", { regex: true })).toBe("Ch1");
    expect(expandReplacement(text, ranges[1], "第(\\d+)章", "Ch$1", { regex: true })).toBe("Ch22");
  });

  it("非正则模式下 expandReplacement 原样返回替换文本", () => {
    expect(expandReplacement("abc", { from: 1, to: 2 }, "b", "$1")).toBe("$1");
  });
});

describe("nextMatch", () => {
  const ranges = [
    { from: 0, to: 2 },
    { from: 10, to: 12 },
    { from: 20, to: 22 },
  ];

  it("从光标往后找最近的", () => {
    expect(nextMatch(ranges, 5)).toEqual({ from: 10, to: 12 });
  });

  it("到末尾回绕到第一个", () => {
    expect(nextMatch(ranges, 30)).toEqual({ from: 0, to: 2 });
  });

  it("往回找时到开头回绕到最后一个", () => {
    expect(nextMatch(ranges, 5, -1)).toEqual({ from: 0, to: 2 });
    expect(nextMatch(ranges, 0, -1)).toEqual({ from: 20, to: 22 });
  });

  it("没有命中返回 null", () => {
    expect(nextMatch([], 0)).toBeNull();
  });
});

describe("applyPairOnKey 自动配对", () => {
  it("敲左引号且无选区 → 插入一对，光标在中间", () => {
    const res = applyPairOnKey("他说", 2, 2, "「");
    expect(res?.text).toBe("他说「」");
    expect(res?.caret).toBe(3);
  });

  it("敲左引号且有选区 → 把选区包起来，选区保留", () => {
    const res = applyPairOnKey("他说下雨了", 2, 4, "「");
    expect(res?.text).toBe("他说「下雨」了");
    expect(res?.selection).toEqual({ from: 3, to: 5 });
  });

  it("敲右引号且右边就是它 → 只跳过去，不重复插入", () => {
    const res = applyPairOnKey("「」", 1, 1, "」");
    expect(res?.text).toBe("「」");
    expect(res?.caret).toBe(2);
  });

  it("敲右引号但右边不是它 → 不接管（返回 null）", () => {
    expect(applyPairOnKey("「", 1, 1, "」")).toBeNull();
  });

  it("半角括号与方括号也配对", () => {
    expect(applyPairOnKey("", 0, 0, "(")?.text).toBe("()");
    expect(applyPairOnKey("", 0, 0, "[")?.text).toBe("[]");
  });

  it("普通字符不接管", () => {
    expect(applyPairOnKey("abc", 1, 1, "x")).toBeNull();
    expect(applyPairOnKey("abc", 1, 1, "Enter")).toBeNull();
  });

  it("已有内容时插入位置正确（插在中间不吞字）", () => {
    const res = applyPairOnKey("甲乙丙", 1, 1, "『");
    expect(res?.text).toBe("甲『』乙丙");
    expect(res?.caret).toBe(2);
  });
});

describe("parseScenes", () => {
  it("没有分隔符 → 整章是一个场景", () => {
    const scenes = parseScenes("他走进车站。\n\n雨还在下。");
    expect(scenes).toHaveLength(1);
    expect(scenes[0].explicit).toBe(false);
    expect(scenes[0].words).toBe(countWords("他走进车站。\n\n雨还在下。"));
  });

  it("◇◇◇ 分隔出多个场景", () => {
    const text = `第一场的内容。\n\n${SCENE_SEPARATOR}\n\n第二场的内容。`;
    const scenes = parseScenes(text);
    expect(scenes.map((s) => s.words)).toEqual([countWords("第一场的内容。"), countWords("第二场的内容。")]);
  });

  it("*** 与 --- 也认（作者两种都会写）", () => {
    expect(parseScenes("甲\n***\n乙\n---\n丙")).toHaveLength(3);
  });

  it("显式标题【…】会作为场景名，且是 explicit", () => {
    const scenes = parseScenes("【车站月台】\n雨停了。");
    expect(scenes[0].title).toBe("车站月台");
    expect(scenes[0].explicit).toBe(true);
    expect(scenes[0].words).toBe(countWords("雨停了。"));
  });

  it("`场景：xxx` 与 `第 3 场` 也认", () => {
    expect(parseScenes("场景：深夜的便利店\n灯还亮着。")[0].title).toBe("深夜的便利店");
    expect(parseScenes("第 3 场 告别\n他说再见。")[0].title).toBe("告别");
  });

  it("无标题场景用首行前若干字当标题", () => {
    const first = "雨停的时候站台的灯还亮着，他一直没走。";
    expect(parseScenes(first)[0].title).toBe(first.slice(0, 18));
  });

  it("偏移量能切回原文", () => {
    const text = `甲段。\n${SCENE_SEPARATOR}\n乙段。`;
    const scenes = parseScenes(text);
    expect(text.slice(scenes[1].from, scenes[1].to).trim()).toBe("乙段。");
  });

  it("空文本 → 空列表（界面显示「本章还没有分场」）", () => {
    expect(parseScenes("")).toEqual([]);
    expect(parseScenes("\n\n")).toEqual([]);
  });

  it("场景序号从 0 连续", () => {
    expect(parseScenes("甲\n◇◇◇\n乙\n◇◇◇\n丙").map((s) => s.index)).toEqual([0, 1, 2]);
  });
});

describe("goalProgress", () => {
  it("未达标时给出还差多少", () => {
    const p = goalProgress(1200, 3000);
    expect(p.remaining).toBe(1800);
    expect(p.done).toBe(false);
    expect(p.ratio).toBeCloseTo(0.4);
  });

  it("超标时 ratio 夹在 1、remaining 归 0", () => {
    const p = goalProgress(4000, 3000);
    expect(p.ratio).toBe(1);
    expect(p.remaining).toBe(0);
    expect(p.done).toBe(true);
  });

  it("没设目标（0/负数/NaN）视为不显示进度", () => {
    expect(goalProgress(100, 0)).toMatchObject({ target: 0, ratio: 1, remaining: 0 });
    expect(goalProgress(100, -5).target).toBe(0);
    expect(goalProgress(100, Number.NaN).target).toBe(0);
  });
});
