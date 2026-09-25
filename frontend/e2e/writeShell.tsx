/* eslint-disable react-refresh/only-export-components --
   组件台入口文件（自己 createRoot 挂载），不是会被 HMR 复用的组件模块。 */

import { StrictMode, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { StudioRibbon } from "../src/components/StudioRibbon";
import { WriteToolbar } from "../src/components/WriteToolbar";
import { copyFor } from "../src/lib/genreCopy";
import shellStyles from "../src/components/StudioApp.module.css";
import "../src/styles/globals.css";

/**
 * 写作业面组件台：**不挂后端，只挂"顶栏菜单 + 稿纸工具条"这一层的真实嵌套**。
 *
 * 为什么需要它：真实写作页里，"文件/开始/审阅/视图"四个菜单的下拉是绝对定位的，
 * 而下面那条剧本/工具条有 `position: relative; z-index: 70`。
 * 下拉被工具条盖住时，用户点不到菜单项——这类层叠 bug 靠读 CSS 很容易看错
 * （z-index 数字谁大谁小并不等于谁在上面：真正的决定因素是**各自的层叠上下文**）。
 * 所以这里按真实结构复刻一份：同一个 shell / layout / docLayout / docMain / panel
 * 嵌套 + 同一批 CSS Module，然后在真浏览器里用 elementFromPoint 判定谁在最上面。
 */

type Log = (line: string) => void;

function WriteShell({ genre, log }: { genre: "vn" | "novel"; log: Log }) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [writeMode, setWriteMode] = useState<"prose" | "rpy">("prose");
  const copy = copyFor(genre);

  return (
    <div className={`vnss-app ${shellStyles.shell} ${shellStyles.writeQuiet}`}>
      <StudioRibbon
        copy={copy}
        title="组件台 · 雨宫站台"
        username="harness"
        showFocusToggle
        writeMode={writeMode}
        showReviseActions={false}
        fileInputRef={fileInputRef}
        onTitleChange={() => {}}
        onFocusToggle={() => log("focus")}
        onNewProject={() => log("new")}
        onImportClick={() => {}}
        onFileChange={() => {}}
        onSaveChapter={() => log("save")}
        onExport={() => log("export")}
        exportLabel={copy.exportLabel}
        onOpenHelp={() => log("help")}
        onOpenSettings={() => log("settings")}
        onLogout={() => log("logout")}
        onOpenFilePage={(page) => log(`file:${page}`)}
        onOpenViewPanel={(panel) => log(`view:${panel}`)}
        onOpenAnalysis={() => log("analysis")}
        onOpenAgent={() => log("agent")}
        onWriteModeChange={setWriteMode}
        onGenerateRpy={() => log("generate")}
        onFind={() => log("find")}
        onOpenRevise={() => {}}
        onDiscardRevise={() => {}}
        onInsertScene={() => log("insertScene")}
      />

      {/* 与真实写作页同构：layout → main → docLayout → docMain → panel(section) → toolbar */}
      <div className={shellStyles.layout}>
        <main className={shellStyles.main}>
          <div className={shellStyles.docLayout}>
            <div className={shellStyles.docMain}>
              <section className={shellStyles.panel} data-testid="harness-doc-panel">
                <WriteToolbar
                  copy={copy}
                  writeMode={writeMode}
                  generating={false}
                  showReviseActions={false}
                  onWriteModeChange={setWriteMode}
                  onGenerateRpy={() => log("generate")}
                  onFind={() => log("find")}
                  onOpenRevise={() => {}}
                  onDiscardRevise={() => {}}
                  onDictateInsert={() => log("dictate")}
                />
                <div className={shellStyles.editor} data-testid="harness-paper">
                  雨停的时候，站台的灯还亮着。
                </div>
              </section>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function App() {
  const [lines, setLines] = useState<string[]>([]);
  const log: Log = (line) => setLines((cur) => [...cur, line]);
  const params = new URLSearchParams(window.location.search);
  const genre = params.get("genre") === "novel" ? "novel" : "vn";

  return (
    <StrictMode>
      <WriteShell genre={genre} log={log} />
      <pre data-testid="harness-log" style={{ display: "none" }}>
        {lines.join("\n")}
      </pre>
    </StrictMode>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
