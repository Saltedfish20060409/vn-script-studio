import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  AGENT_SECTIONS,
  DEFAULT_EXCLUDED_SECTIONS,
  excludedSummary,
  loadExcludedSections,
  saveExcludedSections,
  toggleSection,
} from "./agentSections";

const BACKEND_AGENT_CONTEXT = fileURLToPath(
  new URL("../../../backend/app/core/agent_context.py", import.meta.url)
);
const BACKEND_AGENT_LOOP = fileURLToPath(
  new URL("../../../backend/app/core/agent_loop.py", import.meta.url)
);

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

describe("交给 AI 的资料开关", () => {
  it("key 与后端能摘的块对齐：多一个=勾没用，少一个=界面关不掉（读后端源码，不硬编码）", () => {
    // 这条原先硬编码了一份 14 项的清单，然后 commit 760de43 给界面加了「写作导师方法论」
    // 这个勾却没更新它 —— CI 从此一直红，而且**红得没有信息量**：清单是抄的，
    // 抄歪了只会说"数组长度不对"，说不出到底哪一半没接上。
    //
    // 现在改成读后端源码，两边不一致时红出来的就是**具体哪个 key**：
    //   前端多一个 → 后端不认它，那个勾摘了什么也不发生；
    //   前端少一个 → 后端能摘，但界面没有开关。
    const keys = AGENT_SECTIONS.map((s) => s.key);
    for (const s of AGENT_SECTIONS) expect(s.label.length).toBeGreaterThan(1);

    const ctx = readFileSync(BACKEND_AGENT_CONTEXT, "utf8");
    const start = ctx.indexOf("EXCLUDABLE_SECTIONS: Dict[str, str] = {");
    expect(start, "后端里找不到 EXCLUDABLE_SECTIONS 声明").toBeGreaterThan(-1);
    const rest = ctx.slice(start);
    const end = rest.indexOf("\n}");
    expect(end, "EXCLUDABLE_SECTIONS 没有在行首闭合").toBeGreaterThan(-1);
    const excludable = [
      ...rest.slice(0, end).matchAll(/"([A-Za-z]+)":\s*"/g),
    ].map((m) => m[1]);
    expect(excludable.length).toBeGreaterThan(10);

    // `mentor` 是**单独一条通道**：它不在那张表里，而由 agent_loop 手写判断
    // （`"mentor" in request.excludeSections`）。不把这条读进来，这个勾会被误判成"后端不认"。
    const loop = readFileSync(BACKEND_AGENT_LOOP, "utf8");
    const special = [
      ...loop.matchAll(/"([A-Za-z]+)"\s+in\s+\(request\.excludeSections/g),
    ].map((m) => m[1]);

    const known = new Set([...excludable, ...special]);
    const inert = keys.filter((k) => !known.has(k));
    expect(inert, `这些勾后端根本不认（摘了什么也不发生）：${inert.join("、")}`).toEqual([]);

    const noToggle = excludable.filter((k) => !keys.includes(k));
    expect(
      noToggle,
      `后端允许摘掉、界面却没有开关：${noToggle.join("、")}`
    ).toEqual([]);
  });

  it("切换只影响这一项", () => {
    const next = toggleSection([], "bible");
    expect(next).toEqual(["bible"]);
    expect(toggleSection(next, "bible")).toEqual([]);
  });

  it("存本机并读回来", () => {
    const store = fakeStorage();
    saveExcludedSections(["bible", "lore"], store);
    expect(loadExcludedSections(store)).toEqual(["bible", "lore"]);
  });

  it("默认不带写作导师块（1.6k 字、消融测不出收益），其余块照带", () => {
    // 后端同口径：没显式要就不注入（见 core/mentors.has_explicit_selection）。
    // 这里默认返回的那份，就是「⚙ 资料」面板上默认**没勾**的那几项。
    expect(DEFAULT_EXCLUDED_SECTIONS).toEqual(["mentor"]);
    expect(loadExcludedSections(fakeStorage())).toEqual(["mentor"]);
    expect(loadExcludedSections(null)).toEqual(["mentor"]);
  });

  it("坏数据 / 非数组 → 回落默认那份（不是「全带」）", () => {
    expect(loadExcludedSections(fakeStorage({ "vnss-agent-exclude-v1": "{不是 JSON" }))).toEqual(
      ["mentor"]
    );
    expect(
      loadExcludedSections(fakeStorage({ "vnss-agent-exclude-v1": JSON.stringify({ a: 1 }) }))
    ).toEqual(["mentor"]);
    // 存过的（哪怕是空数组：作者明确把导师块勾上了）照读，不要被默认值盖掉
    expect(
      loadExcludedSections(
        fakeStorage({ "vnss-agent-exclude-v1": JSON.stringify(["bible", 42, null]) })
      )
    ).toEqual(["bible"]);
    expect(
      loadExcludedSections(fakeStorage({ "vnss-agent-exclude-v1": JSON.stringify([]) }))
    ).toEqual([]);
  });

  it("storage 不可用时不抛", () => {
    expect(() => saveExcludedSections(["x"], null)).not.toThrow();
  });

  it("摘要文案", () => {
    expect(excludedSummary([])).toBe("");
    expect(excludedSummary(["a", "b"])).toContain("2");
  });
});
