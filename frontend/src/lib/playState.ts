import type { ScriptBlock } from "../types/vn";

/** Blocks that produce a visible step (others are anchors/code). */
export const VISIBLE = new Set([
  "scene",
  "narration",
  "dialogue",
  "menu",
  "show",
  "hide",
]);

export type PlayState = {
  index: number;
  stack: ScriptBlock[][];
  resume: number[];
};

export const PLAY_START: PlayState = { index: 0, stack: [], resume: [] };

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

export function advance(
  state: PlayState,
  blocks: ScriptBlock[]
): { state: PlayState; ended: boolean } {
  const scope = scopeOf(state, blocks);
  const ni = nextVisible(scope, state.index + 1);
  if (ni !== null) return { state: { ...state, index: ni }, ended: false };
  if (state.stack.length) {
    const stack = state.stack.slice(0, -1);
    const resume = state.resume.slice(0, -1);
    const top = stack.length ? stack[stack.length - 1] : blocks;
    const resumeAt = state.resume[state.resume.length - 1];
    const ri = nextVisible(top, resumeAt);
    if (ri !== null) return { state: { index: ri, stack, resume }, ended: false };
    return { state: { index: 0, stack, resume }, ended: false };
  }
  return { state, ended: true };
}

export function choose(
  state: PlayState,
  blocks: ScriptBlock[],
  choice: { jump?: string; blocks?: ScriptBlock[] },
  labelIndex: Map<string, number>
): { state: PlayState; ended: boolean } {
  if (choice.jump) {
    const target = labelIndex.get(choice.jump);
    if (target !== undefined) return { state: { index: target, stack: [], resume: [] }, ended: false };
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
