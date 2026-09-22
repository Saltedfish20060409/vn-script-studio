import { describe, expect, it } from "vitest";
import type { VnProject } from "../types/vn";
import {
  CHARACTER_RELATIONS,
  auditGraph,
  isKnownRelation,
  relationDef,
} from "./graphAudit";

function project(over: Partial<VnProject> = {}): VnProject {
  return {
    id: "p",
    title: "t",
    logline: "",
    genre: "",
    characters: [
      { id: "a", defineName: "a", displayName: "林夏", color: "#000" },
      { id: "b", defineName: "b", displayName: "周屿", color: "#000" },
      { id: "c", defineName: "c", displayName: "老陈", color: "#000" },
    ],
    chapters: [{ id: "ch1", title: "第一章", blocks: [] }],
    ...over,
  } as VnProject;
}

const codes = (p: VnProject) => auditGraph(p).issues.map((i) => i.code);

describe("关系词表", () => {
  it("对称词标成 symmetric，方向词标成 directional", () => {
    expect(relationDef("朋友")?.kind).toBe("symmetric");
    expect(relationDef("父亲")?.kind).toBe("directional");
    expect(relationDef("夫妻")?.kind).toBe("symmetric");
  });
  it("方向词有反向说法（界面建议用）", () => {
    expect(relationDef("师父")?.inverse).toBe("徒弟");
    expect(relationDef("上司")?.inverse).toBe("下属");
  });
  it("词表里没有重复标签", () => {
    const labels = CHARACTER_RELATIONS.map((r) => r.label);
    expect(new Set(labels).size).toBe(labels.length);
  });
  it("自由文本不算已知", () => {
    expect(isKnownRelation("债主")).toBe(false);
  });
});

describe("角色关系检查", () => {
  it("自指关系报 error", () => {
    const p = project({
      characterLinks: [{ id: "l1", fromId: "a", toId: "a", label: "朋友" }],
    });
    expect(codes(p)).toContain("self_link");
  });

  it("指向已删角色的关系报 error", () => {
    const p = project({
      characterLinks: [{ id: "l1", fromId: "a", toId: "ghost", label: "朋友" }],
    });
    expect(codes(p)).toContain("dangling_link");
  });

  it("对称关系双向各存一条 → 提醒重复（warn），不是矛盾", () => {
    const p = project({
      characterLinks: [
        { id: "l1", fromId: "a", toId: "b", label: "朋友" },
        { id: "l2", fromId: "b", toId: "a", label: "朋友" },
      ],
    });
    const a = auditGraph(p);
    expect(a.issues.map((i) => i.code)).toContain("duplicate_symmetric_link");
    expect(a.counts.error).toBe(0);
  });

  it("方向性关系双向出现 → 判为矛盾（error）", () => {
    const p = project({
      characterLinks: [
        { id: "l1", fromId: "a", toId: "b", label: "父亲" },
        { id: "l2", fromId: "b", toId: "a", label: "父亲" },
      ],
    });
    const a = auditGraph(p);
    const hit = a.issues.find((i) => i.code === "contradictory_direction");
    expect(hit?.severity).toBe("error");
    expect(hit?.message).toContain("林夏");
  });

  it("同向重复也提醒", () => {
    const p = project({
      characterLinks: [
        { id: "l1", fromId: "a", toId: "b", label: "师徒" },
        { id: "l2", fromId: "a", toId: "b", label: "师徒" },
      ],
    });
    expect(codes(p)).toContain("duplicate_link");
  });

  it("词表外的自由写法只提示 info，且限量", () => {
    const links = Array.from({ length: 6 }, (_, i) => ({
      id: `l${i}`,
      fromId: "a",
      toId: "b",
      label: `自定义写法${i}`,
    }));
    const a = auditGraph(project({ characterLinks: links }), { unknownLabelLimit: 2 });
    expect(a.issues.filter((i) => i.code === "unknown_relation_label")).toHaveLength(2);
  });

  it("干净的关系图不报任何问题", () => {
    const p = project({
      characterLinks: [
        { id: "l1", fromId: "a", toId: "b", label: "朋友" },
        { id: "l2", fromId: "c", toId: "a", label: "父亲" },
      ],
    });
    const a = auditGraph(p);
    expect(a.issues).toEqual([]);
    expect(a.size.relations).toBe(2);
  });
});

describe("地点通路检查", () => {
  it("自指通路报 error", () => {
    const p = project({
      locations: [{ id: "L1", name: "站台" }],
      locationLinks: [{ id: "p1", fromId: "L1", toId: "L1", relation: "adjacent" }],
    });
    expect(codes(p)).toContain("self_path");
  });

  it("包含关系成环报 error 并给出环", () => {
    const p = project({
      locations: [
        { id: "L1", name: "雨城" },
        { id: "L2", name: "车站" },
        { id: "L3", name: "站台" },
      ],
      locationLinks: [
        { id: "p1", fromId: "L1", toId: "L2", relation: "contains" },
        { id: "p2", fromId: "L2", toId: "L3", relation: "contains" },
        { id: "p3", fromId: "L3", toId: "L1", relation: "inside" },
      ],
    });
    const hit = auditGraph(p).issues.find((i) => i.code === "containment_cycle");
    expect(hit?.severity).toBe("error");
    expect(hit?.message).toContain("雨城");
  });

  it("相邻（非包含）绕圈不算错：通路本来可以成环", () => {
    const p = project({
      locations: [
        { id: "L1", name: "甲" },
        { id: "L2", name: "乙" },
        { id: "L3", name: "丙" },
      ],
      locationLinks: [
        { id: "p1", fromId: "L1", toId: "L2", relation: "adjacent" },
        { id: "p2", fromId: "L2", toId: "L3", relation: "adjacent" },
        { id: "p3", fromId: "L3", toId: "L1", relation: "adjacent" },
      ],
    });
    expect(codes(p)).not.toContain("containment_cycle");
  });
});

describe("时间线 / 变量 / 伏笔", () => {
  it("节点挂在已删章节上会提醒", () => {
    const p = project({
      timeline: [{ id: "t1", title: "相遇", order: 1, chapterRef: "gone" }],
    });
    expect(codes(p)).toContain("timeline_missing_chapter");
  });

  it("排序号撞车会提示并列", () => {
    const p = project({
      timeline: [
        { id: "t1", title: "甲", order: 1, chapterRef: "ch1" },
        { id: "t2", title: "乙", order: 1, chapterRef: "ch1" },
      ],
    });
    const hit = auditGraph(p).issues.find((i) => i.code === "timeline_order_tie");
    expect(hit?.severity).toBe("info");
  });

  it("变量绑到已删角色报 error", () => {
    const p = project({
      variables: [
        {
          id: "v1",
          name: "好感度",
          key: "aff",
          type: "number",
          value: 0,
          bindCharacterId: "ghost",
        },
      ],
    });
    expect(codes(p)).toContain("variable_dangling_bind");
  });

  it("干净的账本/时间线不报问题", () => {
    const p = project({
      timeline: [{ id: "t1", title: "相遇", order: 1, chapterRef: "ch1" }],
      variables: [
        {
          id: "v1",
          name: "好感度",
          key: "aff",
          type: "number",
          value: 0,
          bindCharacterId: "a",
        },
      ],
      writingLedger: {
        chapterFacts: [],
        characterStates: [],
        foreshadows: [{ id: "f1", hook: "红伞", plantedChapter: "ch1", status: "open" }],
      },
    } as Partial<VnProject>);
    expect(auditGraph(p).issues).toEqual([]);
  });

  it("图规模数字给得出来（给作者一个直观感受）", () => {
    const p = project({
      characterLinks: [{ id: "l1", fromId: "a", toId: "b", label: "朋友" }],
      timeline: [{ id: "t1", title: "x", order: 1 }],
    });
    const a = auditGraph(p);
    expect(a.size).toEqual({
      characters: 3,
      relations: 1,
      locations: 0,
      paths: 0,
      timeline: 1,
      variables: 0,
    });
  });
});
