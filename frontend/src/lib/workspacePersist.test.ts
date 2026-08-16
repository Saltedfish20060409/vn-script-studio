/**
 * workspacePersist 工作区持久化单元测试
 *
 * node 环境下用 vi.stubGlobal 注入 localStorage mock，覆盖
 * loadWorkspace/saveWorkspace 的默认值合并、旧版 projectId 迁移、
 * 损坏 JSON 兜底、sideOpen 布尔保留等行为。
 */
import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import {
  loadWorkspace,
  saveWorkspace,
  workspaceDefaults,
} from "./workspacePersist";

const KEY = "vnss-workspace-v1";
const LEGACY_PROJECT_KEY = "vnss-active-project-id";

/** 最小 localStorage 内存实现 */
function createMockStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => {
      store.set(k, String(v));
    },
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", createMockStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadWorkspace：读取", () => {
  it("无任何存储时返回空对象", () => {
    expect(loadWorkspace()).toEqual({});
  });

  it("主键损坏时回退旧版 projectId", () => {
    const storage = localStorage as unknown as ReturnType<typeof createMockStorage>;
    storage.setItem(KEY, "{oops");
    storage.setItem(LEGACY_PROJECT_KEY, "p9");
    expect(loadWorkspace()).toEqual({ projectId: "p9" });
  });

  it("主键损坏且无旧版键时返回空对象", () => {
    const storage = localStorage as unknown as ReturnType<typeof createMockStorage>;
    storage.setItem(KEY, "not-json");
    expect(loadWorkspace()).toEqual({});
  });

  it("主键内容是 JSON null 时返回空对象", () => {
    const storage = localStorage as unknown as ReturnType<typeof createMockStorage>;
    storage.setItem(KEY, "null");
    expect(loadWorkspace()).toEqual({});
  });

  it("仅有旧版 projectId 时迁移为 projectId", () => {
    const storage = localStorage as unknown as ReturnType<typeof createMockStorage>;
    storage.setItem(LEGACY_PROJECT_KEY, "legacy-1");
    expect(loadWorkspace()).toEqual({ projectId: "legacy-1" });
  });
});

describe("saveWorkspace：写入与合并", () => {
  it("首次保存后读取到完整快照与默认值", () => {
    saveWorkspace({ projectId: "p1", chapterId: "c1", tab: "map" });
    const loaded = loadWorkspace();
    expect(loaded).toMatchObject({
      projectId: "p1",
      chapterId: "c1",
      tab: "map",
      writeSub: "script",
      worldSub: "characters",
      systemSub: "variables",
      projectSub: "library",
      sideOpen: true,
      agentSize: "normal",
    });
    expect(typeof loaded.updatedAt).toBe("number");
  });

  it("保存时同步写入旧版 projectId 键", () => {
    saveWorkspace({ projectId: "p1" });
    const storage = localStorage as unknown as ReturnType<typeof createMockStorage>;
    expect(storage.getItem(LEGACY_PROJECT_KEY)).toBe("p1");
  });

  it("增量 patch 与上次快照合并，未提供字段保留旧值", () => {
    saveWorkspace({ projectId: "p1", chapterId: "c1", tab: "map" });
    saveWorkspace({ tab: "world" });
    const loaded = loadWorkspace();
    expect(loaded.tab).toBe("world");
    expect(loaded.projectId).toBe("p1");
    expect(loaded.chapterId).toBe("c1");
    expect(loaded.writeSub).toBe("script");
  });

  it("sideOpen=false 显式布尔被保留", () => {
    saveWorkspace({ projectId: "p1", sideOpen: false });
    saveWorkspace({ tab: "voice" });
    expect(loadWorkspace().sideOpen).toBe(false);
  });

  it("写入的 JSON 可完整读回（含子 tab 字段）", () => {
    saveWorkspace({
      projectId: "p1",
      chapterId: "c1",
      tab: "system",
      systemSub: "sprites",
      agentSize: "large",
    });
    const loaded = loadWorkspace();
    expect(loaded.tab).toBe("system");
    expect(loaded.systemSub).toBe("sprites");
    expect(loaded.agentSize).toBe("large");
  });

  it("重复保存只覆盖同一条主键记录", () => {
    saveWorkspace({ projectId: "p1" });
    saveWorkspace({ projectId: "p2", tab: "map" });
    const storage = localStorage as unknown as ReturnType<typeof createMockStorage>;
    const raw = storage.getItem(KEY)!;
    const parsed = JSON.parse(raw);
    expect(parsed.projectId).toBe("p2");
    expect(parsed.tab).toBe("map");
    expect(parsed.chapterId).toBe("");
  });
});

describe("workspaceDefaults：默认值", () => {
  it("返回默认快照字段", () => {
    expect(workspaceDefaults()).toEqual({
      tab: "write",
      writeSub: "script",
      worldSub: "characters",
      systemSub: "variables",
      projectSub: "library",
      sideOpen: true,
      agentSize: "normal",
    });
  });

  it("每次调用返回新对象引用（防外部篡改）", () => {
    expect(workspaceDefaults()).not.toBe(workspaceDefaults());
  });
});
