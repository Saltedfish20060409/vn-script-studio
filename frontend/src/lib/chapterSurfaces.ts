/**
 * 一章的文本存在哪一面：正文档（`prose`）与脚本档（`blocks`）之间的写入规则。
 *
 * ## 背景（线上事故，2026-10-01，作者账号「搁浅de咸鱼」）
 *
 * 作者报的是：「我开了新对话、把之前不满意的原文删掉了，让它生成文字时用的**还是那段旧文**。」
 *
 * 查下来不是删除没生效，而是**同一章有两份存储**，而写入只动当前档位的那一面：
 *
 * - Agent 的 `append_script` / `replace_script` 只写 `blocks`（`core/agent.py`）；
 * - 编辑器在正文档档写 `prose`、在脚本档写 `blocks`（StudioApp.flushChapter 的旧实现）；
 * - 读侧两边都是 **prose 优先、prose 为空回落 blocks**：
 *   `core/agent_context.chapter_plain`（服务端，上下文/对照面板的"原文"）与
 *   `lib/scriptProse.chapterProse`（编辑器里显示的那份）。
 *
 * 于是"文本其实存在 blocks 里、作者却在正文档里把它删了"这条路上，三件事一起发生：
 * 1. 写入的是**本来就空**的 `prose` → 本地 JSON 一点没变；
 * 2. 防抖保存前的 `diffProjectAgainst` 判定"无变化" → **连 PUT 都不发**（工作区一点没写）；
 * 3. 而所有读侧又从 `blocks` 回落到那份稿子 —— 作者眼里删掉了，服务端与模型眼里它还在，
 *    模型于是**接着那段"已删除"的原文往下写**。
 *
 * ## 规则
 *
 * **清空当前档 = 这一章没有文本了，另一面也一起清**（并清掉 `rpyFromProseHash`）。
 * 非空编辑仍然只动当前档——"正文档写正文、脚本档留手调脚本"的并行用法不受影响。
 *
 * 这条规则必须落在**写入侧**：读侧的回落本身是必要的（纯脚本档工程 `prose` 一直是空的，
 * 不回落就什么都读不到），能分辨"作者删了"与"作者从来没用过这一面"的只有编辑动作本身。
 */

import { blocksToProse } from "./scriptProse";
import { editableToBlocks } from "./scriptCodec";
import type { ScriptBlock, VnProject } from "../types/vn";

/** 与 `components/StudioRibbon.WriteMode` 同形；放这里是为了让写规则可单测。 */
export type ChapterWriteMode = "prose" | "rpy";

export type FlushChapterResult = {
  project: VnProject;
  /** 这次清空是否连带清掉了另一面（界面拿它给作者一句说明，别让动作是静默的）。 */
  clearedOther: boolean;
};

/** 这一面里有没有"文本"（结构块与演出指令不算：它们渲染不出正文）。 */
function blocksHaveText(blocks: ScriptBlock[] | undefined): boolean {
  return blocksToProse(blocks, []).trim().length > 0;
}

/**
 * 把编辑器里这一档的文本写进工程（唯一入口：`StudioApp` 与 `buildLatestProject` 都走它）。
 *
 * @param text 编辑器里的全文（`""` 或空白 = 作者清空了这一档）
 * @param mode 作者当前在写哪一档
 */
export function flushChapterSurface(
  project: VnProject,
  chapterId: string,
  text: string,
  mode: ChapterWriteMode
): FlushChapterResult {
  const emptied = !text.trim();
  let clearedOther = false;

  const chapters = project.chapters.map((chapter) => {
    if (chapter.id !== chapterId) return chapter;

    if (mode === "prose") {
      if (!emptied) return { ...chapter, prose: text };
      // 清空正文档：脚本档那份是同一章的另一面表示，留着它旧稿就会从回落里复活。
      // 已经是空的（prose 空 + blocks 无文本 + 无派生标记）就原样返回，
      // 免得白造一次"变化"让自动保存发一次空 PUT。
      const hadProse = Boolean((chapter.prose || "").trim());
      const hadBlocksText = blocksHaveText(chapter.blocks);
      if (!hadProse && !hadBlocksText && !chapter.rpyFromProseHash) return chapter;
      clearedOther = hadBlocksText;
      return {
        ...chapter,
        prose: "",
        blocks: [],
        rpyFromProseHash: undefined,
      };
    }

    // 脚本档：清空时 blocks 回到"新建章节"那种只剩 label start 的形态
    const blocks = editableToBlocks(text);
    if (!emptied) return { ...chapter, blocks };
    const hadProse = Boolean((chapter.prose || "").trim());
    if (!hadProse) return { ...chapter, blocks };
    clearedOther = true;
    return { ...chapter, blocks, prose: "" };
  });

  return { project: { ...project, chapters }, clearedOther };
}
