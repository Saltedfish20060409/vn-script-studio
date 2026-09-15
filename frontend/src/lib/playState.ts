import type { IfBranch, MenuChoice, ScriptBlock } from "../types/vn";
import { evaluateCondition, parseCondition } from "./conditions";

/** Blocks that produce a visible step (others are anchors/code). */
export const VISIBLE = new Set([
  "scene",
  "narration",
  "dialogue",
  "menu",
  "show",
  "hide",
  "wait",
]);

/**
 * 瞬时指令：经过时立即生效、不产生停顿（音乐/音效/语音/变量/镜头/特效）。
 * 播放器会在推进过程中把它们收集起来统一应用（见 AdvanceResult.executed）。
 */
export const INSTANT = new Set([
  "music",
  "sound",
  "voice",
  "set",
  "camera",
  "effect",
]);

export type PlayState = {
  index: number;
  stack: ScriptBlock[][];
  resume: number[];
};

export type PlayContext = {
  /** 变量当前值（初始值来自项目 variables，播放中可被 set 指令改写） */
  variables?: Record<string, unknown>;
};

export type AdvanceResult = {
  state: PlayState;
  ended: boolean;
  /** 途中经过的瞬时指令（按顺序） */
  executed: ScriptBlock[];
  /** 是否发生了 label 跳转 */
  jumped: boolean;
  /** 是否因为跳转过多而疑似死循环 */
  looped: boolean;
};

/** SECURITY/QUALITY: cap total advance/jump steps before we declare a loop.
 *  A chapter that legitimately loops (e.g. menu cycles) could exceed this,
 *  but a pathological `jump start` self-loop would otherwise never end. */
export const MAX_PLAY_STEPS = 2000;

/**
 * 起点：index = -1 表示"还没演任何东西"，于是 advance 会从第 0 块开始扫描
 * （这样才能执行开头的音乐/镜头等瞬时指令，也不会漏掉第一句台词）。
 */
export const PLAY_START: PlayState = { index: -1, stack: [], resume: [] };

export type StepCount = { steps: number };

export function scopeOf(state: PlayState, blocks: ScriptBlock[]): ScriptBlock[] {
  return state.stack.length ? state.stack[state.stack.length - 1] : blocks;
}

export function nextVisible(
  blocks: ScriptBlock[],
  from: number
): number | null {
  for (let i = from; i < blocks.length; i++) {
    if (VISIBLE.has(blocks[i].type)) return i;
  }
  return null;
}

/** 条件成立的分支（按顺序取第一个匹配；空条件 = else）。都不匹配返回 null。 */
export function pickIfBranch(
  block: ScriptBlock,
  variables: Record<string, unknown>
): IfBranch | null {
  if (block.type !== "if") return null;
  for (const branch of block.branches || []) {
    const raw = (branch.condition || "").trim();
    if (!raw) return branch;
    try {
      if (evaluateCondition(parseCondition(raw), variables)) return branch;
    } catch {
      // 条件写错的分支在预览里按"不成立"处理（导出侧会显式注释掉，不会静默放行）
      continue;
    }
  }
  return null;
}

/** 菜单里当前应当显示的选项（过滤掉条件不成立的）。 */
export function visibleChoices(
  choices: MenuChoice[],
  variables: Record<string, unknown>
): MenuChoice[] {
  return (choices || []).filter((c) => {
    const raw = (c.condition || "").trim();
    if (!raw) return true;
    try {
      return evaluateCondition(parseCondition(raw), variables);
    } catch {
      return false;
    }
  });
}

/** Is there a `return` later in this scope (past `from`, ignoring comments)? */
function hasReturnAfter(blocks: ScriptBlock[], from: number): boolean {
  for (let i = from; i < blocks.length; i++) {
    const b = blocks[i];
    if (b.type === "return") return true;
    if (b.type === "comment" || b.type === "label") continue;
    if (VISIBLE.has(b.type) || b.type === "jump" || b.type === "if") return false;
  }
  return false;
}

/**
 * 推进到下一条"会停"的内容。
 *
 * 与旧版的区别（重要）：
 * - **线性 jump 会被跟随**。旧实现用 nextVisible 扫描，会把剧本中间的 `jump` 直接跳过，
 *   于是试玩会演出跳转目标之前那段本不该出现的正文——与 Ren'Py 的真实行为不一致。
 * - **if 分支会被进入**：按变量当前值选中分支，把分支正文压栈，演完后回到 if 之后。
 * - **瞬时指令随路收集**：音乐/音效/语音/变量/镜头/特效不产生停顿，但必须执行。
 */
export function advance(
  state: PlayState,
  blocks: ScriptBlock[],
  ctx: PlayContext = {},
  labelIndex?: Map<string, number>
): AdvanceResult {
  const variables = ctx.variables || {};
  const executed: ScriptBlock[] = [];
  let st = state;
  let jumped = false;

  for (let hop = 0; hop <= MAX_PLAY_STEPS; hop++) {
    const scope = scopeOf(st, blocks);
    let i = st.index + 1;
    let restart = false;

    while (i < scope.length) {
      const b = scope[i];

      if (INSTANT.has(b.type)) {
        executed.push(b);
        i += 1;
        continue;
      }

      if (b.type === "if") {
        const branch = pickIfBranch(b, variables);
        const body = branch?.blocks || [];
        if (body.length) {
          // 压栈并从分支头部重新扫描（分支内部可能还有瞬时/控制块）
          st = {
            index: -1,
            stack: [...st.stack, body],
            resume: [...st.resume, i + 1],
          };
          restart = true;
          break;
        }
        i += 1;
        continue;
      }

      if (b.type === "jump" && labelIndex) {
        const target = labelIndex.get(b.target);
        if (target !== undefined) {
          st = { index: target, stack: [], resume: [] };
          jumped = true;
          restart = true;
          break;
        }
        // 目标 label 不存在：预览里跳过（Ren'Py 会报错，作者靠导出后的报错发现）
        i += 1;
        continue;
      }

      if (b.type === "return") {
        return { state: st, ended: true, executed, jumped, looped: false };
      }

      if (VISIBLE.has(b.type)) {
        return {
          state: { ...st, index: i },
          ended: false,
          executed,
          jumped,
          looped: false,
        };
      }

      i += 1;
    }

    if (restart) continue;

    // 当前 scope 走到了尽头
    // 分支正文常以 return 收尾（Ren'Py 合法）：当前 scope 之后只有 return 时
    // 直接结束，而不是回退外层后把 index 归零重播（会死循环）。
    if (hasReturnAfter(scope, st.index + 1)) {
      return { state: st, ended: true, executed, jumped, looped: false };
    }
    // 逐层回退：嵌套分支（if 里套 if / menu）演完一层后，外层可能还有内容可续。
    // 旧实现只回退一层就判定"结束"，嵌套场景会提前收尾。
    //
    // 注意用 `index = resumeAt - 1` 回到外层再**继续扫描**，而不是直接跳到
    // nextVisible 的结果上——否则外层那几句之间的音乐/镜头等瞬时指令会被跳过。
    let stack = st.stack;
    let resume = st.resume;
    let resumed = false;
    while (stack.length) {
      // resume[last] 是"离开这一层后，在上一层继续的下标"
      const resumeAt = resume[resume.length - 1];
      stack = stack.slice(0, -1);
      resume = resume.slice(0, -1);
      const top = stack.length ? stack[stack.length - 1] : blocks;
      if (resumeAt <= top.length) {
        st = { index: resumeAt - 1, stack, resume };
        resumed = true;
        break;
      }
    }
    if (resumed) continue;
    // 全部回退完也没有可续内容 → 结束（不回 index 归零重播）
    return {
      state: { index: 0, stack: [], resume: [] },
      ended: true,
      executed,
      jumped,
      looped: false,
    };
  }

  // 跳转次数超限 → 判定疑似死循环
  return { state: st, ended: true, executed, jumped, looped: true };
}

export function choose(
  state: PlayState,
  blocks: ScriptBlock[],
  choice: { jump?: string; blocks?: ScriptBlock[] },
  labelIndex: Map<string, number>
): { state: PlayState; ended: boolean } {
  if (choice.jump) {
    const target = labelIndex.get(choice.jump);
    if (target !== undefined) {
      // 跳到 label 后，继续定位到该 label 之后第一个「可见」块：
      // 否则 current 落在 label 上 → 试玩 stage 空白（点击无法进入下一页）。
      const vi = nextVisible(blocks, target);
      return {
        state:
          vi !== null
            ? { index: vi, stack: [], resume: [] }
            : { index: target, stack: [], resume: [] },
        ended: vi === null,
      };
    }
    const scope = scopeOf(state, blocks);
    const ni = nextVisible(scope, state.index + 1);
    return {
      state: ni !== null ? { ...state, index: ni } : state,
      ended: ni === null,
    };
  }
  if (choice.blocks?.length) {
    const first = nextVisible(choice.blocks, 0);
    return {
      state: {
        index: first !== null ? first : 0,
        stack: [...state.stack, choice.blocks],
        resume: [...state.resume, state.index + 1],
      },
      ended: false,
    };
  }
  const scope = scopeOf(state, blocks);
  const ni = nextVisible(scope, state.index + 1);
  return {
    state: ni !== null ? { ...state, index: ni } : state,
    ended: ni === null,
  };
}
