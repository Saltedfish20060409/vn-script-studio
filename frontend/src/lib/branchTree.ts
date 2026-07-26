import type { ScriptBlock, VnProject } from "../types/vn";

export interface BranchNode {
  id: string;
  kind: "label" | "menu" | "choice" | "jump" | "end";
  title: string;
  children: BranchNode[];
}

/** Build a lightweight branch tree from menu/jump/label structure. */
export function buildBranchTree(project: VnProject, chapterId?: string): BranchNode[] {
  const chapters = chapterId
    ? project.chapters.filter((c) => c.id === chapterId)
    : project.chapters;

  const roots: BranchNode[] = [];

  for (const ch of chapters) {
    const chapterRoot: BranchNode = {
      id: `ch-${ch.id}`,
      kind: "label",
      title: ch.title,
      children: walkBlocks(ch.blocks, ch.id),
    };
    roots.push(chapterRoot);
  }
  return roots;
}

function walkBlocks(blocks: ScriptBlock[], prefix: string): BranchNode[] {
  const nodes: BranchNode[] = [];
  let i = 0;
  while (i < blocks.length) {
    const b = blocks[i];
    if (b.type === "label") {
      nodes.push({
        id: `${prefix}-label-${b.name}-${i}`,
        kind: "label",
        title: `label ${b.name}`,
        children: [],
      });
    } else if (b.type === "menu") {
      const menuNode: BranchNode = {
        id: `${prefix}-menu-${b.id}-${i}`,
        kind: "menu",
        title: b.prompt ? `选项：${b.prompt}` : `menu ${b.id}`,
        children: b.choices.map((c, ci) => ({
          id: `${prefix}-choice-${b.id}-${ci}`,
          kind: "choice" as const,
          title: c.text,
          children: c.jump
            ? [
                {
                  id: `${prefix}-jump-${c.jump}-${ci}`,
                  kind: "jump" as const,
                  title: `→ ${c.jump}`,
                  children: [],
                },
              ]
            : [],
        })),
      };
      nodes.push(menuNode);
    } else if (b.type === "jump") {
      nodes.push({
        id: `${prefix}-jump-${b.target}-${i}`,
        kind: "jump",
        title: `jump ${b.target}`,
        children: [],
      });
    } else if (b.type === "return") {
      nodes.push({
        id: `${prefix}-end-${i}`,
        kind: "end",
        title: "return",
        children: [],
      });
    }
    i += 1;
  }
  return nodes;
}
