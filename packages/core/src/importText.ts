import type { ScriptBlock, VnProject } from "./types.js";
import { normalizeProject } from "./project.js";

/** Create a project from imported Word/text/.rpy content. */
export function projectFromPlainText(title: string, text: string): VnProject {
  const cleaned = text.replace(/\r\n/g, "\n").trim();
  const lines = cleaned.split("\n").map((l) => l.trimEnd());

  const looksRenpy = lines.some((l) =>
    /^(label\s+\w+\s*:|scene\s+|define\s+\w+|menu\b)/i.test(l.trim())
  );

  let blocks: ScriptBlock[];
  if (looksRenpy) {
    blocks = [
      { type: "comment", text: "从脚本文件导入" },
      { type: "raw", code: cleaned },
    ];
  } else {
    blocks = [
      { type: "label", id: "start", name: "start" },
      { type: "comment", text: "以下内容由文档导入，可改写成 Ren'Py 对白" },
      ...lines
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line): ScriptBlock => {
          const dlg = line.match(/^(.{1,12})[：:]\s*(.+)$/);
          if (dlg) {
            return { type: "narration", text: `${dlg[1]}：${dlg[2]}` };
          }
          return { type: "narration", text: line };
        }),
    ];
  }

  return normalizeProject({
    id: `proj-${Date.now()}`,
    title,
    chapters: [
      {
        id: "ch1",
        title: "导入稿",
        synopsis: "从文件导入，待整理",
        blocks,
      },
    ],
    characters: [],
    bible: {
      notes: `导入于 ${new Date().toLocaleString()}`,
    },
  });
}
