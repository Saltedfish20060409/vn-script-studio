/**
 * branchTree 分支树构建单元测试
 *
 * 覆盖 buildBranchTree：章节根节点、label/menu/choice/jump/end
 * 节点的 id/kind/title/children 结构、chapterId 过滤、空章节等场景。
 */
import { describe, it, expect } from "vitest";
import type { VnProject } from "../types/vn";
import { buildBranchTree } from "./branchTree";

const project: VnProject = {
  id: "p1",
  title: "测试工程",
  characters: [],
  updatedAt: "",
  chapters: [
    {
      id: "c1",
      title: "第一章",
      blocks: [
        { type: "label", id: "start", name: "start" },
        {
          type: "menu",
          id: "m1",
          prompt: "走哪边？",
          choices: [
            { text: "左", jump: "left" },
            { text: "右" },
          ],
        },
        { type: "jump", target: "left" },
        { type: "return" },
      ],
    },
    { id: "c2", title: "第二章", blocks: [] },
  ],
};

describe("buildBranchTree：章节根节点", () => {
  it("每个章节生成一个 label 类型的根节点，id 带 ch- 前缀", () => {
    const roots = buildBranchTree(project);
    expect(roots).toHaveLength(2);
    expect(roots[0].id).toBe("ch-c1");
    expect(roots[0].kind).toBe("label");
    expect(roots[0].title).toBe("第一章");
    expect(roots[1].id).toBe("ch-c2");
    expect(roots[1].title).toBe("第二章");
  });

  it("chapterId 过滤后仅返回对应章节", () => {
    const roots = buildBranchTree(project, "c2");
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe("ch-c2");
    expect(roots[0].children).toEqual([]);
  });

  it("不存在的 chapterId 返回空数组", () => {
    expect(buildBranchTree(project, "nope")).toEqual([]);
  });

  it("无章节时返回空数组", () => {
    const empty: VnProject = {
      id: "p",
      title: "空",
      characters: [],
      updatedAt: "",
      chapters: [],
    };
    expect(buildBranchTree(empty)).toEqual([]);
  });
});

describe("buildBranchTree：块节点结构", () => {
  const ch = buildBranchTree(project, "c1")[0];

  it("label 块生成 label 节点，id 含 章节前缀-块索引", () => {
    const node = ch.children[0];
    expect(node).toMatchObject({
      id: "c1-label-start-0",
      kind: "label",
      title: "label start",
    });
    expect(node.children).toEqual([]);
  });

  it("menu 块生成 menu 节点，title 带 选项：prompt 前缀", () => {
    const node = ch.children[1];
    expect(node.kind).toBe("menu");
    expect(node.id).toBe("c1-menu-m1-1");
    expect(node.title).toBe("选项：走哪边？");
  });

  it("menu 的每个选项生成 choice 子节点，带跳转时挂 jump 孙节点", () => {
    const menu = ch.children[1];
    expect(menu.children).toHaveLength(2);

    const left = menu.children[0];
    expect(left).toMatchObject({
      id: "c1-choice-m1-0",
      kind: "choice",
      title: "左",
    });
    expect(left.children).toHaveLength(1);
    expect(left.children[0]).toMatchObject({
      id: "c1-jump-left-0",
      kind: "jump",
      title: "→ left",
    });

    const right = menu.children[1];
    expect(right).toMatchObject({
      id: "c1-choice-m1-1",
      kind: "choice",
      title: "右",
    });
    expect(right.children).toEqual([]);
  });

  it("顶层 jump 块生成 jump 节点", () => {
    const node = ch.children[2];
    expect(node).toMatchObject({
      id: "c1-jump-left-2",
      kind: "jump",
      title: "jump left",
    });
  });

  it("return 块生成 end 节点", () => {
    const node = ch.children[3];
    expect(node).toMatchObject({
      id: "c1-end-3",
      kind: "end",
      title: "return",
    });
  });

  it("无 prompt 的 menu title 回退为 menu {id}", () => {
    const p: VnProject = {
      id: "p",
      title: "t",
      characters: [],
      updatedAt: "",
      chapters: [
        {
          id: "c",
          title: "章",
          blocks: [
            { type: "menu", id: "m2", choices: [{ text: "A" }] },
          ],
        },
      ],
    };
    const menu = buildBranchTree(p)[0].children[0];
    expect(menu.title).toBe("menu m2");
  });

  it("非分支块（对话/旁白/scene 等）不生成节点", () => {
    const p: VnProject = {
      id: "p",
      title: "t",
      characters: [],
      updatedAt: "",
      chapters: [
        {
          id: "c",
          title: "章",
          blocks: [
            { type: "scene", image: "bg" },
            { type: "dialogue", characterId: "lx", text: "hi" },
            { type: "narration", text: "旁白" },
            { type: "comment", text: "注" },
          ],
        },
      ],
    };
    const nodes = buildBranchTree(p)[0].children;
    expect(nodes).toEqual([]);
  });
});
