import { describe, expect, it } from "vitest";
import {
  PROJECT_CONFLICT_DETAIL,
  RESTORE_DIRTY_CONFIRM,
  RESTORE_GUARD_MS,
  RESTORE_GUARD_IN_FLIGHT_UNTIL,
  clearRestoreGuard,
  extendRestoreGuardOnSuccess,
  isEditorDirtyVsSaved,
  isRestoreGuardActive,
  openRestoreGuardAtRequest,
  shouldBlockPersistForRestoreGuard,
  shouldSkipPersistBecauseClean,
} from "./restoreGuard";
import type { VnProject } from "../types/vn";

function project(partial?: Partial<VnProject>): VnProject {
  return {
    id: "p1",
    title: "t",
    logline: "",
    genre: "",
    characters: [],
    chapters: [
      {
        id: "ch1",
        title: "一",
        blocks: [{ type: "label", id: "start", name: "start" }],
        prose: "正文A",
      },
    ],
    ...partial,
  } as unknown as VnProject;
}

describe("restoreGuard 保护窗时序", () => {
  it("T0 请求发出即开窗（in-flight）", () => {
    const t0 = 1_000_000;
    const until = openRestoreGuardAtRequest(t0);
    expect(until).toBe(RESTORE_GUARD_IN_FLIGHT_UNTIL);
    expect(isRestoreGuardActive(until, t0)).toBe(true);
    expect(isRestoreGuardActive(until, t0 + 60_000)).toBe(true);
  });

  it("补1：API 延迟 8s 返回前，保护窗已生效（persist 被禁）", () => {
    const t0 = 1_000_000;
    let until = openRestoreGuardAtRequest(t0);
    // 模拟恢复 API 耗时 8s；期间多次尝试 persist
    for (const elapsed of [0, 1000, 4000, 7999]) {
      expect(
        shouldBlockPersistForRestoreGuard(until, t0 + elapsed),
        `at +${elapsed}ms`
      ).toBe(true);
    }
    // 成功返回：再满 5s
    const t1 = t0 + 8000;
    until = extendRestoreGuardOnSuccess(until, t1);
    expect(until).toBe(t1 + RESTORE_GUARD_MS);
    expect(shouldBlockPersistForRestoreGuard(until, t1)).toBe(true);
    expect(shouldBlockPersistForRestoreGuard(until, t1 + RESTORE_GUARD_MS - 1)).toBe(
      true
    );
    expect(shouldBlockPersistForRestoreGuard(until, t1 + RESTORE_GUARD_MS)).toBe(
      false
    );
  });

  it("失败立即清窗", () => {
    const t0 = 1_000_000;
    openRestoreGuardAtRequest(t0);
    const until = clearRestoreGuard();
    expect(until).toBe(0);
    expect(isRestoreGuardActive(until, t0 + 100)).toBe(false);
    expect(shouldBlockPersistForRestoreGuard(until, t0 + 100)).toBe(false);
  });

  it("成功后从 now 起再满 N 秒", () => {
    const t0 = 1_000;
    const prev = openRestoreGuardAtRequest(t0);
    const t1 = t0 + 8000;
    expect(extendRestoreGuardOnSuccess(prev, t1)).toBe(t1 + RESTORE_GUARD_MS);
  });
});

describe("restoreGuard dirty / clean", () => {
  it("编辑器与上次保存正文档一致 → 不脏", () => {
    const saved = project();
    expect(
      isEditorDirtyVsSaved({
        editorText: "正文A",
        saved,
        chapterId: "ch1",
        mode: "prose",
        characters: [],
      })
    ).toBe(false);
  });

  it("编辑器改过 → 脏", () => {
    const saved = project();
    expect(
      isEditorDirtyVsSaved({
        editorText: "正文A改了",
        saved,
        chapterId: "ch1",
        mode: "prose",
        characters: [],
      })
    ).toBe(true);
  });

  it("补5：恢复后 lastSaved=restored，立即保存 → 因无 diff 跳过 PUT", () => {
    const restored = project({
      chapters: [
        {
          id: "ch1",
          title: "一",
          blocks: [{ type: "narration", text: "雨" }],
          prose: "实验室稿".repeat(10),
        },
      ],
    } as Partial<VnProject>);
    expect(
      shouldSkipPersistBecauseClean({
        lastSaved: restored,
        candidate: restored,
      })
    ).toBe(true);
  });

  it("有改动则不 skip", () => {
    const saved = project();
    const dirty = project({
      chapters: [
        {
          id: "ch1",
          title: "一",
          blocks: [{ type: "label", id: "start", name: "start" }],
          prose: "改过了",
        },
      ],
    } as Partial<VnProject>);
    expect(
      shouldSkipPersistBecauseClean({ lastSaved: saved, candidate: dirty })
    ).toBe(false);
  });
});

describe("冲突文案", () => {
  it("含刷新与保留本地后果说明", () => {
    expect(PROJECT_CONFLICT_DETAIL).toContain("刷新将获取最新数据");
    expect(PROJECT_CONFLICT_DETAIL).toContain("保留本地将覆盖服务器版本");
    expect(PROJECT_CONFLICT_DETAIL).toContain("对方未保存的内容会丢失");
  });
});

describe("dirty confirm 文案存在", () => {
  it("export 常量供 UI 使用", () => {
    expect(RESTORE_DIRTY_CONFIRM).toContain("丢弃当前未保存");
  });
});
