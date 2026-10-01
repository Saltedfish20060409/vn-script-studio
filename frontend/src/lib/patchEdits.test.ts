/**
 * 定点改写的逐条勾选：改动粒度 = 可勾选粒度。
 *
 * 这组测试钉的是"勾哪几条就写哪几条"——包括最容易写错的边界：
 * 一条都不勾时不该产出空动作（后端会把空 edits 当失败报出来），
 * 以及**非定点改写的动作不该被勾选表顺手改掉语义**。
 */
import { describe, expect, it } from "vitest";

import {
  filterPatchActions,
  hasPatchEdits,
  isPatchAction,
  patchEditRows,
  patchPlanSummary,
} from "./patchEdits";
import type { AgentAction } from "../types/vn";

const PATCH: AgentAction = {
  op: "patch_script",
  chapterRef: "第一章",
  edits: [
    { find: "雪菜：「热的。」", replace: "雪菜：「这个是热的。」" },
    { find: "（她往怀里挪了一点。）", replace: "" },
  ],
} as unknown as AgentAction;

describe("把 patch_script 摊成可勾选的行", () => {
  it("每条 find/replace 一行，带稳定 id 与章名", () => {
    const rows = patchEditRows([PATCH]);
    expect(rows.map((r) => r.id)).toEqual(["0:0", "0:1"]);
    expect(rows[0].before).toBe("雪菜：「热的。」");
    expect(rows[0].after).toBe("雪菜：「这个是热的。」");
    expect(rows[0].chapterRef).toBe("第一章");
    // 删除型改动：replace 是空串（作者要能看出"这条是删掉"）
    expect(rows[1].after).toBe("");
  });

  it("认不出的条目跳过，不编行出来", () => {
    const rows = patchEditRows([
      { op: "patch_script", chapterRef: "第一章", edits: [{ replace: "只有新文" }, "字符串", null] },
      { op: "patch_script", edits: [{ find: "没写章名也要能给个兜底" }] },
    ] as unknown as AgentAction[]);
    expect(rows).toHaveLength(1);
    expect(rows[0].chapterRef).toBe("当前章");
  });

  it("没有定点改写时不摆勾选表", () => {
    expect(hasPatchEdits([{ op: "append_script", text: "正文" } as unknown as AgentAction])).toBe(
      false
    );
    expect(hasPatchEdits(undefined)).toBe(false);
    expect(isPatchAction({ op: "replace_script" } as unknown as AgentAction)).toBe(false);
  });

  it("标题摘要说清改哪几章、共几处", () => {
    expect(patchPlanSummary(patchEditRows([PATCH]))).toBe("定点改写 第一章：共 2 处");
    const two = patchEditRows([
      PATCH,
      { op: "patch_script", chapterRef: "第二章", edits: [{ find: "a", replace: "b" }] },
    ] as unknown as AgentAction[]);
    expect(patchPlanSummary(two)).toBe("定点改写 2 章：共 3 处");
    expect(patchPlanSummary([])).toBe("");
  });
});

describe("按勾选过滤", () => {
  it("只保留勾中的改动", () => {
    const out = filterPatchActions([PATCH], ["0:1"]);
    expect(out).toHaveLength(1);
    expect((out[0] as { edits: unknown[] }).edits).toEqual([
      { find: "（她往怀里挪了一点。）", replace: "" },
    ]);
  });

  it("一条都不勾时整条动作丢掉（不能留空 edits 给后端报错）", () => {
    expect(filterPatchActions([PATCH], [])).toEqual([]);
  });

  it("非定点改写的动作原样保留", () => {
    const other = { op: "append_script", chapterRef: "第一章", text: "往下写" };
    const out = filterPatchActions([other, PATCH] as unknown as AgentAction[], ["0:0"]);
    // 注意下标：other 是 0，PATCH 是 1 —— 勾 0:0 命中的是 other 的下标，PATCH 未勾中
    expect(out.map((a) => (a as { op: string }).op)).toEqual(["append_script"]);
    const out2 = filterPatchActions([other, PATCH] as unknown as AgentAction[], ["1:0"]);
    expect(out2.map((a) => (a as { op: string }).op)).toEqual(["append_script", "patch_script"]);
    expect((out2[1] as { edits: unknown[] }).edits).toHaveLength(1);
  });
});
