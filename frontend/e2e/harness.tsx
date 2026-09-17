/* eslint-disable react-refresh/only-export-components --
   这是组件台的入口文件（自己 createRoot 挂载），不是会被 HMR 复用的组件模块，
   "只导出组件"这条规则在这里是误报。 */

import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { DesktopView, type DesktopApp } from "../src/components/DesktopView";
import { MusicPlayerBar } from "../src/components/MusicPlayerBar";
import "../src/styles/globals.css";

/**
 * 桌面视图的组件台（只给开发/测试用，**不进生产构建**：vite 只以 index.html 为入口）。
 *
 * 为什么要它：桌面这一层是纯前端交互（拖动换座位、双击开剧本、右键菜单、任务栏、
 * 以及"剧本窗口打开时下面的工作台还点得动"），单元测试只能覆盖纯函数，覆盖不到
 * "点到元素上了没有"。这个页面用假数据把 DesktopView + 一个假工作台挂起来，
 * 让 Playwright 能在真实浏览器里验证这些交互、并截图。
 *
 * 跑法：npm run test:harness（见 playwright.harness.config.ts）
 */

const PROJECTS = [
  { id: "p1", title: "雨夜站台", chapters: 12, updatedAt: "2026-09-17T09:00:00Z" },
  { id: "p2", title: "九幽诀", chapters: 0, updatedAt: "2026-09-10T09:00:00Z" },
  // 没有章数/时间信息：验证"不画角标、提示也不编数字"
  { id: "p3", title: "夏日回声" },
];

/** 剧本超过这个数时，「更多剧本」图标用来复核入口 */
const MANY_PROJECTS = Array.from({ length: 9 }, (_, i) => ({
  id: `q${i}`,
  title: `长篇${i + 1}`,
}));

const APPS: DesktopApp[] = [
  {
    id: "library",
    label: "剧本库",
    glyph: "🗂️",
    defaultRect: { x: 120, y: 90, w: 520, h: 380 },
    render: () => (
      <p style={{ padding: "1rem" }} data-testid="library-window">
        剧本库（组件台占位）
      </p>
    ),
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

/**
 * 假工作台：模仿真实 shell 的几何（正好占住标题栏与任务栏之间的工作区、自己滚）。
 * 关键测试点是那个按钮 —— 桌面层如果没做"事件穿透"，它就是点不动的。
 */
function FakeWorkbench({ title, tab }: { title: string; tab: string }) {
  const [hits, setHits] = useState(0);
  return (
    <div
      data-testid="fake-workbench"
      style={{
        position: "fixed",
        top: 30,
        left: 0,
        right: 0,
        bottom: 46,
        zIndex: 0,
        overflowY: "auto",
        padding: "1rem",
      }}
    >
      <p style={{ margin: "0 0 0.6rem" }}>工作台：{title}</p>
      <p data-testid="wb-tab">当前篇章：{tab}</p>
      <button type="button" data-testid="wb-button" onClick={() => setHits((n) => n + 1)}>
        工作台按钮（点了应是 {hits + 1}）
      </button>
      <p data-testid="wb-hits">{hits}</p>
      {/* 让工作台自己可滚：桌面视图里滚的是它，不是整个文档 */}
      <div style={{ height: "220vh" }} aria-hidden />
      <p data-testid="wb-tail">工作台底部</p>
    </div>
  );
}

function Harness({ projects = PROJECTS }: { projects?: Array<{ id: string; title: string }> }) {
  const [scriptOpen, setScriptOpen] = useState(false);
  const [activeId, setActiveId] = useState(projects[0].id);
  const [tab, setTab] = useState("write");
  const [log, setLog] = useState<string[]>([]);

  return (
    <>
      <DesktopView
        username="harness"
        projects={projects}
        activeProjectId={activeId}
        activeProjectTitle={projects.find((p) => p.id === activeId)?.title}
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
        onRenameProject={(id) => setLog((cur) => [...cur, `rename:${id}`])}
        onDuplicateProject={(id) => setLog((cur) => [...cur, `duplicate:${id}`])}
        onDeleteProject={(id) => setLog((cur) => [...cur, `delete:${id}`])}
        scriptTabs={[
          { id: "write", label: "写作" },
          { id: "world", label: "设定" },
          { id: "voice", label: "角色工坊" },
          { id: "map", label: "地图" },
          { id: "system", label: "剧情状态" },
          { id: "project", label: "项目" },
        ]}
        onOpenScriptTab={(id) => {
          setTab(id);
          setScriptOpen(true);
          setLog((cur) => [...cur, `tab:${id}`]);
        }}
        resume={{ projectTitle: projects[0].title, chapterLabel: "第 3 章 · 夜雨" }}
        onResume={() => {
          setActiveId(projects[0].id);
          setScriptOpen(true);
          setLog((cur) => [...cur, "resume"]);
        }}
        onSwitchToStudioView={() => setLog((cur) => [...cur, "studio"])}
        onLogout={() => setLog((cur) => [...cur, "logout"])}
      />
      {scriptOpen ? (
        <FakeWorkbench title={projects.find((p) => p.id === activeId)?.title ?? ""} tab={tab} />
      ) : null}
      <pre data-testid="harness-log" style={{ display: "none" }}>
        {log.join("\n")}
      </pre>
    </>
  );
}

const params = new URLSearchParams(window.location.search);
const withMusic = params.get("music") === "1";
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <>
      {withMusic ? null : (
        <Harness projects={params.get("many") === "1" ? MANY_PROJECTS : PROJECTS} />
      )}
      {/* ?music=1：单独量底部音乐条的高度（它固定在底部，跟着桌面一起渲染会挡任务栏） */}
      {withMusic ? <MusicPlayerBar contextLabel="组件台" /> : null}
    </>
  </StrictMode>
);
