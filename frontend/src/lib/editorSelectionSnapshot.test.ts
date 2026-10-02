import { describe, expect, it } from "vitest";
import {
  captureSelectionFromTextarea,
  nextSelectionSnapshot,
  type SelectionSnapshot,
} from "./editorSelectionSnapshot";
import { withAgentSelection } from "./markHighlight";

const empty: SelectionSnapshot = { text: "", range: null };

describe("nextSelectionSnapshot", () => {
  it("非空 DOM 选区 → 更新快照", () => {
    const next = nextSelectionSnapshot({
      prev: empty,
      domFrom: 2,
      domTo: 5,
      value: "0123456789",
      editorFocused: true,
    });
    expect(next).toEqual({ text: "234", range: { from: 2, to: 5 } });
  });

  it("选中 → 点 Agent 输入框（折叠 + 编辑器失焦）→ 快照仍在", () => {
    const prev: SelectionSnapshot = {
      text: "选中段",
      range: { from: 0, to: 3 },
    };
    const next = nextSelectionSnapshot({
      prev,
      domFrom: 3,
      domTo: 3,
      value: "选中段后面还有字",
      editorFocused: false,
    });
    expect(next).toEqual(prev);
    // 持久高亮与「选区 N 字」同源：快照 range 仍驱动镜像 agentSelection
    expect(withAgentSelection([], next.range)).toEqual([
      {
        id: "__agent_selection__",
        from: 0,
        to: 3,
        active: true,
        role: "agentSelection",
      },
    ]);
  });

  it("折叠且编辑器仍聚焦 → 清空（点了光标）", () => {
    const prev: SelectionSnapshot = {
      text: "选中段",
      range: { from: 0, to: 3 },
    };
    const next = nextSelectionSnapshot({
      prev,
      domFrom: 1,
      domTo: 1,
      value: "选中段",
      editorFocused: true,
    });
    expect(next).toEqual(empty);
  });
});

describe("captureSelectionFromTextarea", () => {
  it("mousedown 前抓取非空选区", () => {
    expect(
      captureSelectionFromTextarea({
        selectionStart: 1,
        selectionEnd: 4,
        value: "abcdef",
      })
    ).toEqual({ text: "bcd", range: { from: 1, to: 4 } });
  });

  it("折叠则返回 null", () => {
    expect(
      captureSelectionFromTextarea({
        selectionStart: 2,
        selectionEnd: 2,
        value: "abcdef",
      })
    ).toBeNull();
  });
});
