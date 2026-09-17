/* eslint-disable react-refresh/only-export-components --
   这是组件台的入口文件（自己 createRoot 挂载），不是会被 HMR 复用的组件模块，
   "只导出组件"这条规则在这里是误报。 */

import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { DesktopView, type DesktopApp } from "../src/components/DesktopView";
import "../src/styles/globals.css";

/**
 * 桌面视图的组件台（只给开发/测试用，**不进生产构建**：vite 只以 index.html 为入口）。
 *
 * 为什么要它：桌面这一层是纯前端交互（拖动换座位、双击开剧本、任务栏），
 * 单元测试只能覆盖纯函数，覆盖不到"点到元素上了没有"。这个页面用假数据把
 * DesktopView 挂起来，让 Playwright 能在真实浏览器里验证这些交互、并截图。
 *
 * 跑法：npm run test:harness（见 playwright.harness.config.ts）
 */

const PROJECTS = [
  { id: "p1", title: "雨夜站台" },
  { id: "p2", title: "九幽诀" },
  { id: "p3", title: "夏日回声" },
];

const APPS: DesktopApp[] = [
  {
    id: "library",
    label: "剧本库",
    glyph: "🗂️",
    onDesktop: true,
    defaultRect: { x: 120, y: 90, w: 520, h: 380 },
    render: () => <p style={{ padding: "1rem" }}>剧本库（组件台占位）</p>,
  },
  {
    id: "agent",
    label: "AI 责编",
    glyph: "🧠",
    onDesktop: true,
    defaultRect: { x: 200, y: 70, w: 520, h: 460 },
    render: () => <p style={{ padding: "1rem" }}>AI 责编（组件台占位）</p>,
  },
  {
    id: "settings",
    label: "系统设置",
    glyph: "⚙️",
    defaultRect: { x: 160, y: 60, w: 560, h: 420 },
    render: () => <p style={{ padding: "1rem" }}>系统设置（组件台占位）</p>,
  },
  {
    id: "notice",
    label: "更新公告",
    glyph: "📢",
    run: () => {
      document.body.dataset.notice = "1";
    },
  },
];

function Harness() {
  const [scriptOpen, setScriptOpen] = useState(false);
  const [activeId, setActiveId] = useState(PROJECTS[0].id);
  const [log, setLog] = useState<string[]>([]);

  return (
    <>
      <DesktopView
        username="harness"
        projects={PROJECTS}
        activeProjectId={activeId}
        activeProjectTitle={PROJECTS.find((p) => p.id === activeId)?.title}
        apps={APPS}
        scriptOpen={scriptOpen}
        onOpenProject={(id) => {
          setActiveId(id);
          setScriptOpen(true);
          setLog((cur) => [...cur, `open:${id}`]);
        }}
        onNewProject={() => setLog((cur) => [...cur, "new"])}
        onCloseScript={() => setScriptOpen(false)}
        onScriptMinimize={() => setScriptOpen(false)}
        onSwitchToStudioView={() => setLog((cur) => [...cur, "studio"])}
        onLogout={() => setLog((cur) => [...cur, "logout"])}
      />
      {/* 组件台里替掉真实的工作台：显示"打开了哪个剧本"，证明双击真的传对了 id */}
      {scriptOpen ? (
        <div
          data-testid="fake-workbench"
          style={{ position: "fixed", inset: "30px 0 46px", zIndex: 1, padding: "1rem" }}
        >
          工作台：{PROJECTS.find((p) => p.id === activeId)?.title}
        </div>
      ) : null}
      <pre data-testid="harness-log" style={{ display: "none" }}>
        {log.join("\n")}
      </pre>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Harness />
  </StrictMode>
);
