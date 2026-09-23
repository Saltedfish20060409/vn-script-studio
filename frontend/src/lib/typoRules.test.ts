import { describe, expect, it } from "vitest";
import { TYPO_RULES, findTypos, typoMessage } from "./typoRules";

describe("词表本身的约束", () => {
  it("每条规则的错写与正确写法都非空且不相同", () => {
    for (const rule of TYPO_RULES) {
      expect(rule.wrong.trim().length, JSON.stringify(rule)).toBeGreaterThan(0);
      expect(rule.right.trim().length, JSON.stringify(rule)).toBeGreaterThan(0);
      expect(rule.wrong, JSON.stringify(rule)).not.toBe(rule.right);
    }
  });

  it("没有重复的错写形式（重复说明词表被写重了）", () => {
    const wrongs = TYPO_RULES.map((r) => r.wrong);
    expect(new Set(wrongs).size).toBe(wrongs.length);
  });

  it("正确写法不会同时出现在错写清单里（A→B 与 B→A 会互相打架）", () => {
    const wrongs = new Set(TYPO_RULES.map((r) => r.wrong));
    for (const rule of TYPO_RULES) {
      expect(wrongs.has(rule.right), `${rule.right} 不该出现在错写清单`).toBe(false);
    }
  });

  it("错写形式不是正确写法的子串（子串规则会重复报同一次错误）", () => {
    for (const rule of TYPO_RULES) {
      expect(rule.right.includes(rule.wrong), JSON.stringify(rule)).toBe(false);
    }
  });

  it("词表足够覆盖高频成语（不能只有三五条充数）", () => {
    expect(TYPO_RULES.length).toBeGreaterThanOrEqual(60);
  });
});

describe("findTypos 命中", () => {
  it("命中成语别字并给出位置", () => {
    const text = "他迫不急待地推开门。";
    const hits = findTypos(text);
    expect(hits).toHaveLength(1);
    expect(hits[0].wrong).toBe("迫不急待");
    expect(hits[0].right).toBe("迫不及待");
    expect(text.slice(hits[0].offset, hits[0].offset + hits[0].length)).toBe("迫不急待");
  });

  it("一句话里多处命中，按位置排序", () => {
    const hits = findTypos("一如继往地按耐不住，又好象很镇定。");
    expect(hits.map((h) => h.wrong)).toEqual(["一如继往", "按耐不住", "好象"]);
    expect(hits[0].offset).toBeLessThan(hits[1].offset);
    expect(hits[1].offset).toBeLessThan(hits[2].offset);
  });

  it("同一个别字出现多次要全部报出来", () => {
    expect(findTypos("迫不急待，真的很迫不急待。")).toHaveLength(2);
  });

  it("写对的成语不报", () => {
    expect(findTypos("他迫不及待地推开门，一如既往地沉默。")).toEqual([]);
  });

  it("干净正文零命中（这条决定了它敢不敢开给作者看）", () => {
    const clean = [
      "雨停的时候，站台的灯还亮着。",
      "「走吧，」她说，「反正末班车已经过去了。」",
      "他点了点头——那种没什么意义的、习惯性的点头。",
      "他仿佛又看见了那年夏天，尽管他并不想看见。",
    ].join("\n");
    expect(findTypos(clean)).toEqual([]);
  });

  it("人名地名不会被误报（词表里没有专名）", () => {
    // 常见角色名/地名里含"象、采、既"等易混字，规则不得命中
    expect(findTypos("林夏、陆然、雨见町、篠原灯、九条莲都到了。")).toEqual([]);
  });

  it("空文本不抛异常", () => {
    expect(findTypos("")).toEqual([]);
  });

  it("typoMessage 能直接显示给作者", () => {
    const [hit] = findTypos("迫不急待");
    const message = typoMessage(hit);
    expect(message).toContain("迫不急待");
    expect(message).toContain("迫不及待");
    expect(message).toContain("成语");
  });
});

describe("刻意不收的那些（防止以后有人「顺手加上」）", () => {
  it("语境依赖的易混词不会报（反应/反映 这类要模型判断，不是词表）", () => {
    // 这两句都是正确用法，任何一条被报出来都说明词表越界了
    expect(findTypos("他反映了这个情况。")).toEqual([]);
    expect(findTypos("他的反应很快。")).toEqual([]);
    expect(findTypos("这幅图象很清楚。")).toEqual([]);
    expect(findTypos("这份份量太重了。")).toEqual([]);
  });
});
