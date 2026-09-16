import { describe, expect, it } from "vitest";
import { diffProjectAgainst } from "./projectDiff";
import { normalizeProject } from "./vnLocal";
import type { LoreEntry } from "../types/vn";

const entry: LoreEntry = { id: "le1", title: "青云门", body: "东域正道之首", keywords: ["青云"] };

function base() {
  return normalizeProject({ id: "p1", title: "T" });
}

describe("设定条目必须能存下去（保存链路上的两个坑）", () => {
  it("normalizeProject 不会把 loreEntries 丢掉", () => {
    // normalizeProject 是白名单式的：漏一个字段就等于保存时把它抹掉
    const p = normalizeProject({ id: "p1", title: "T", loreEntries: [entry] });
    expect(p.loreEntries).toHaveLength(1);
    expect(p.loreEntries?.[0].title).toBe("青云门");
  });

  it("改了条目会体现在 scoped save 的 sections 里", () => {
    // 服务端只合并客户端声明的 sections，没声明就等于没改（静默丢失）
    const before = base();
    const after = normalizeProject({ ...before, loreEntries: [entry] });
    const diff = diffProjectAgainst(before, after);
    expect(diff.sections).toContain("loreEntries");
    expect(diff.hasChanges).toBe(true);
  });

  it("条目没变时不算改动（避免无意义的保存与冲突弹窗）", () => {
    const before = normalizeProject({ id: "p1", title: "T", loreEntries: [entry] });
    const after = normalizeProject({ id: "p1", title: "T", loreEntries: [{ ...entry }] });
    expect(diffProjectAgainst(before, after).hasChanges).toBe(false);
  });

  it("空数组与缺省等价（不会因为 [] 与 undefined 反复判为改动）", () => {
    const without = normalizeProject({ id: "p1", title: "T" });
    const empty = normalizeProject({ id: "p1", title: "T", loreEntries: [] });
    expect(diffProjectAgainst(without, empty).hasChanges).toBe(false);
  });
});
