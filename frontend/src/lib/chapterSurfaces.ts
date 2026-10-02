/**
 * 一章的文本存在哪一面：正文档（`prose`）与脚本档（`blocks`）之间的写入规则。
 *
 * ## 背景（线上事故，2026-10-01，作者账号「搁浅de咸鱼」）
 *
 * 作者报的是：「我开了新对话、把之前不满意的原文删掉了，让它生成文字时用的**还是那段旧文**。」
 *
 * 查下来不是删除没生效，而是**同一章有两份存储**，而写入只动当前档位的那一面：
 *
 * - Agent 的 `append_script` / `replace_script`：按请求 `writing_surface`
 *   （或缺省「prose 非空 → prose」代理）写 prose 和/或 blocks（`core/agent.py`）；
 * - 编辑器在正文档档写 `prose`、在脚本档写 `blocks`（StudioApp.flushChapter 的旧实现）；
 * - 读侧两边都是 **prose 优先、prose 为空回落 blocks**：
 *   `core/agent_context.chapter_plain`（服务端，上下文/对照面板的"原文"）与
 *   可编辑正文档只读 `storedProse`（P4.5）；脚本投影用 `scriptPreview`。
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
 * **清空 UX（确认闸）**：当清空会连带清掉另一面非空正文时，UI 须先确认再调用
 * `flushChapterSurface`；用 `inspectClearImpact` 判定。本轮不提供「只清当前面」
 * （读侧 prose→blocks 回落会复活旧稿，需章级 sticky 另立 follow-up）。
 *
 * ## P4.5：禁止「回落 → 落盘」
 *
 * 空 prose 时编辑器不再填 `scriptPreview`；flush 四象限见 `flushChapterSurface`。
 * `enforceProseEngineSyntaxReject === false` 时恢复旧落盘行为（与后端硬拒同一 flag）。
 *
 * 这条规则必须落在**写入侧**：读侧的回落本身是必要的（纯脚本档工程 `prose` 一直是空的，
 * 不回落就什么都读不到），能分辨"作者删了"与"作者从来没用过这一面"的只有编辑动作本身。
 */

import { blocksToProse, scriptPreview } from "./scriptProse";
import { blocksToEditable, editableToBlocks } from "./scriptCodec";
import type { Character, ScriptBlock, VnProject } from "../types/vn";

/** 与 `components/StudioRibbon.WriteMode` 同形；放这里是为了让写规则可单测。 */
export type ChapterWriteMode = "prose" | "rpy";

export type FlushChapterOpts = {
  /**
   * P4.5 护栏（默认 true）。false = 紧急回滚：空 prose 也可把编辑器内容写入 prose
   * （含与 scriptPreview 字节级相同的文本）。
   */
  enforceProseEngineSyntaxReject?: boolean;
  /** 用于 scriptPreview 皮带比较；缺省用工程角色表 */
  characters?: Character[];
};

export type FlushChapterResult = {
  project: VnProject;
  /** 这次清空是否连带清掉了另一面（界面拿它给作者一句说明，别让动作是静默的）。 */
  clearedOther: boolean;
};

export type ClearImpact = {
  /** 清空会连带清掉另一面非空正文 → UI 须弹确认。 */
  needsConfirm: boolean;
  /** 另一面将被清掉的正文字数（trim 后）。 */
  otherCharCount: number;
  /** 取消确认时应写回编辑器的文本（当前面存盘内容）。 */
  restoreText: string;
  currentSurfaceLabel: string;
  otherSurfaceLabel: string;
};

/** 这一面里有没有"文本"（结构块与演出指令不算：它们渲染不出正文）。 */
function blocksHaveText(blocks: ScriptBlock[] | undefined): boolean {
  return blocksToProse(blocks, []).trim().length > 0;
}

function normNl(s: string): string {
  return s.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function surfaceLabels(mode: ChapterWriteMode): {
  currentSurfaceLabel: string;
  otherSurfaceLabel: string;
} {
  return mode === "prose"
    ? { currentSurfaceLabel: "正文档", otherSurfaceLabel: "脚本档" }
    : { currentSurfaceLabel: "脚本档", otherSurfaceLabel: "正文档" };
}

/**
 * 在真正 flush 之前：是否会因「清空当前档」连带清掉另一面非空正文。
 * 与 `flushChapterSurface` 的 `clearedOther` 语义对齐；四象限 no-op 不进闸。
 */
export function inspectClearImpact(
  project: VnProject,
  chapterId: string,
  text: string,
  mode: ChapterWriteMode,
  opts?: FlushChapterOpts
): ClearImpact {
  const labels = surfaceLabels(mode);
  const chars = opts?.characters ?? project.characters ?? [];
  const chapter = project.chapters.find((c) => c.id === chapterId);
  if (!chapter) {
    return {
      needsConfirm: false,
      otherCharCount: 0,
      restoreText: text,
      ...labels,
    };
  }

  const restoreText =
    mode === "prose"
      ? chapter.prose || ""
      : blocksToEditable(chapter.blocks ?? [], chars);

  if (text.trim()) {
    return {
      needsConfirm: false,
      otherCharCount: 0,
      restoreText,
      ...labels,
    };
  }

  // 干跑：与真实 flush 同一套判定（含 P4.5 no-op / flag 关路径）
  const { clearedOther } = flushChapterSurface(
    project,
    chapterId,
    text,
    mode,
    opts
  );
  if (!clearedOther) {
    return {
      needsConfirm: false,
      otherCharCount: 0,
      restoreText,
      ...labels,
    };
  }

  const otherCharCount =
    mode === "prose"
      ? blocksToProse(chapter.blocks, chars).trim().length
      : (chapter.prose || "").trim().length;

  return {
    needsConfirm: true,
    otherCharCount,
    restoreText,
    ...labels,
  };
}

/** 确认弹窗正文（可单测）。 */
export function clearBothSurfacesConfirmBody(impact: ClearImpact): string {
  return (
    `你正在清空「${impact.currentSurfaceLabel}」。` +
    `另一面「${impact.otherSurfaceLabel}」约 ${impact.otherCharCount} 字也会被清空，无法从本次操作恢复。`
  );
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
  mode: ChapterWriteMode,
  opts?: FlushChapterOpts
): FlushChapterResult {
  const emptied = !text.trim();
  let clearedOther = false;
  const enforce = opts?.enforceProseEngineSyntaxReject !== false;
  const chars = opts?.characters ?? project.characters ?? [];

  const chapters = project.chapters.map((chapter) => {
    if (chapter.id !== chapterId) return chapter;

    if (mode === "prose") {
      const hadProse = Boolean((chapter.prose || "").trim());

      if (enforce) {
        // 四象限（P4.5）：
        // | 存盘 prose | 编辑器 | 动作 |
        // | 空 | 空 | no-op（预览态，勿清 blocks） |
        // | 空 | === scriptPreview | no-op（皮带：勿把预览落盘） |
        // | 空 | 其它非空 | 只写 prose |
        // | 非空 | 空 | 清两面（2026-10-01 事故规则） |
        // | 非空 | 非空 | 只写 prose |
        //
        // 稀有误判：作者手写正文与当前 scriptPreview **字节级相同**时，会被当成预览、
        // 不写入 prose。概率极低；改一字即可落盘。禁止为「修复」这条而放走行级模糊相等。
        if (!hadProse) {
          if (emptied) return chapter;
          const preview = scriptPreview(chapter, chars);
          if (normNl(text) === normNl(preview)) return chapter;
          return { ...chapter, prose: text };
        }
        if (emptied) {
          // 作者删光正文档 → 仍清两面（2026-10-01 事故规则）
          const hadBlocksText = blocksHaveText(chapter.blocks);
          clearedOther = hadBlocksText;
          return {
            ...chapter,
            prose: "",
            blocks: [],
            rpyFromProseHash: undefined,
          };
        }
        return { ...chapter, prose: text };
      }

      // flag 关：旧行为（可把 fallback 落盘）
      if (!emptied) return { ...chapter, prose: text };
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
