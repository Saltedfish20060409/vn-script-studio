/* eslint-disable react-refresh/only-export-components --
   这是组件台的入口文件（自己 createRoot 挂载），不是会被 HMR 复用的组件模块，
   "只导出组件"这条规则在这里是误报。 */

import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { DesktopView, type DesktopApp } from "../src/components/DesktopView";
import { MusicPlayerBar } from "../src/components/MusicPlayerBar";
import "../src/styles/globals.css";

/**
 * 桌面视图组件台：桌面只作启动器，选中作品后进入假稿纸（与生产 Word 壳一致）。
 * 跑法：npm run test:harness
 */

const PROJECTS = [
  { id: "p1", title: "雨夜站台", chapters: 12, updatedAt: "2026-09-17T09:00:00Z" },
  { id: "p2", title: "九幽诀", chapters: 0, updatedAt: "2026-09-10T09:00:00Z" },
  { id: "p3", title: "夏日回声" },
];

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

/** 假稿纸：模拟离开桌面后的 Word 壳主区 */
function FakeWorkbench({ title, tab }: { title: string; tab: string }) {
  const [hits, setHits] = useState(0);
  return (
    <div
      data-testid="fake-workbench"
      style={{
        minHeight: "100vh",
        padding: "1rem",
        overflow: "auto",
        background: "#f6f1e6",
      }}
    >
      <p data-testid="wb-title">稿纸：《{title}》</p>
      <p data-testid="wb-tab">当前面板：{tab}</p>
      <button
        type="button"
        data-testid="wb-button"
        onClick={() => setHits((n) => n + 1)}
      >
        点我
      </button>
      <span data-testid="wb-hits">{hits}</span>
      {Array.from({ length: 40 }, (_, i) => (
        <p key={i}>假正文行 {i + 1}</p>
      ))}
      <p data-testid="wb-tail">工作台底部</p>
    </div>
  );
}

function Harness({
  projects = PROJECTS,
}: {
  projects?: Array<{ id: string; title: string; chapters?: number; updatedAt?: string }>;
}) {
  const [inStudio, setInStudio] = useState(false);
  const [activeId, setActiveId] = useState(projects[0].id);
  const [tab, setTab] = useState("write");
  const [log, setLog] = useState<string[]>([]);

  function enterStudio(nextTab = "write") {
    setTab(nextTab);
    setInStudio(true);
  }

  if (inStudio) {
    return (
      <>
        <FakeWorkbench
          title={projects.find((p) => p.id === activeId)?.title ?? ""}
          tab={tab}
        />
        <pre data-testid="harness-log" style={{ display: "none" }}>
          {log.join("\n")}
        </pre>
      </>
    );
  }

  return (
    <>
      <DesktopView
        username="harness"
        projects={projects}
        activeProjectId={activeId}
        activeProjectTitle={projects.find((p) => p.id === activeId)?.title}
        apps={APPS}
        onOpenProject={(id) => {
          setActiveId(id);
          enterStudio("write");
          setLog((cur) => [...cur, `open:${id}`]);
        }}
        onNewProject={() => setLog((cur) => [...cur, "new"])}
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
          enterStudio(id);
          setLog((cur) => [...cur, `tab:${id}`]);
        }}
        resume={{ projectTitle: projects[0].title, chapterLabel: "第 3 章 · 夜雨" }}
        onResume={() => {
          setActiveId(projects[0].id);
          enterStudio("write");
          setLog((cur) => [...cur, "resume"]);
        }}
        onSwitchToStudioView={() => {
          enterStudio("write");
          setLog((cur) => [...cur, "studio"]);
        }}
        onLogout={() => setLog((cur) => [...cur, "logout"])}
      />
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
      {withMusic ? <MusicPlayerBar contextLabel="组件台" /> : null}
    </>
  </StrictMode>
);
